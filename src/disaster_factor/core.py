# IMPORTS
from bs4 import BeautifulSoup
import requests
import re
import csv
import time

from .helpers import serve_static_and_open


def _extract_impact_urls_from_rss_items(items) -> tuple[list[str], list[str]]:
    """
    Internal helper.

    Given a list of <item> nodes from the GDACS RSS feed, extract:
      - impact_xmls: URLs whose resource id="impact_xml"
      - impact_data: URLs whose resource id="impact_data"
    """
    impact_xmls: list[str] = []
    impact_data: list[str] = []

    for item in items:
        # Some items simply have no <resources> block at all.
        if item.resources is None:
            continue

        resource_group = item.resources.find_all("resource")
        for res in resource_group:
            res_id = res.get("id")
            url = res.get("url")
            if not url:
                continue

            if res_id == "impact_xml":
                impact_xmls.append(url)
            elif res_id == "impact_data":
                impact_data.append(url)

    return impact_xmls, impact_data


def _parse_calculation_xmls(impact_xmls: list[str]) -> tuple[dict[int, dict[str, str]], int]:
    """
    Internal helper.

    Parse the 'calculation' XMLs to build the initial disasters dict.

    Returns:
      disasters: {counter -> {"city": str, "country": str, "type": str}}
      counter:   last used integer id (for continuing numbering later)
    """
    disasters: dict[int, dict[str, str]] = {}
    counter = 0

    xml_calculations: list[str] = []
    # NOTE: xml_contentdata is not used for the disasters dict in the current logic,
    # but we keep the split so behaviour matches the original implementation.
    xml_contentdata: list[str] = []

    for xml_url in impact_xmls:
        if "calculation" in xml_url:
            xml_calculations.append(xml_url)
        else:
            xml_contentdata.append(xml_url)

    for site in xml_calculations:
        resp_3 = requests.get(site)
        soup_3 = BeautifulSoup(resp_3.content, features="xml")
        datums = soup_3.find_all("datums")

        for d in datums:
            if d.get("alias") != "City":
                continue

            data = d.find_all("datum")

            for datum in data:
                disaster: dict[str, str] = {}
                scalars = datum.find_all("scalar")

                for scalar in scalars:
                    name_tag = scalar.find("name")
                    if not name_tag:
                        continue

                    name_text = name_tag.text
                    value_tag = scalar.find("value")

                    if name_text == "NAME" and value_tag is not None:
                        counter += 1
                        disaster["city"] = value_tag.text

                    elif name_text == "COUNTRY" and value_tag is not None:
                        disaster["country"] = value_tag.text
                        model_name_tag = soup_3.find("model-name")
                        if model_name_tag is not None:
                            # Disaster *type* is the model name (e.g. "VO", "EQ", etc.)
                            disaster["type"] = model_name_tag.text

                # Only store complete entries (city + country present)
                if "city" in disaster and "country" in disaster:
                    disasters[counter] = disaster

    return disasters, counter


def _parse_impact_data_locations(
    impact_data: list[str],
    disasters: dict[int, dict[str, str]],
    counter: int,
) -> tuple[dict[int, dict[str, str]], int]:
    """
    Internal helper.

    Parse the 'impact_data' HTML pages that link to locations.xml and
    extend the disasters dict with those locations.
    """
    for link in impact_data:
        resp_4 = requests.get(link)
        soup_4 = BeautifulSoup(resp_4.content, "lxml")

        if soup_4.pre is None:
            continue

        anchors = soup_4.pre.find_all("a")
        for a in anchors:
            if a.text != "final":
                continue

            href = a.get("href")
            if not href:
                continue

            url = "http://webcritech.jrc.ec.europa.eu" + href + "locations.xml"
            resp_5 = requests.get(url)
            soup_5 = BeautifulSoup(resp_5.content, features="xml")
            items = soup_5.find_all("item")

            for item in items:
                if item.cityName is None:
                    continue

                counter += 1
                disasters[counter] = {
                    "city": item.cityName.text,
                    "country": item.country.text,
                    # Original logic: disaster "type" is the locations.xml <title>, lowercased
                    "type": soup_5.title.text.lower(),
                }

    return disasters, counter


def recon() -> tuple[dict[int, dict[str, str]], int]:
    """
    R — RECON (DATA RETRIEVAL)

    Fetch disaster events from the GDACS RSS feed and return:
      - disasters: mapping of int -> {'city', 'country', 'type'}
      - total_red: count of red-level alerts (currently stubbed)

    Contract:
      Returns (disasters, total_red) exactly as described; callers must not
      depend on implementation details.
    """
    url = "http://www.gdacs.org/XML/RSS.xml"
    resp = requests.get(url)
    soup = BeautifulSoup(resp.content, features="xml")
    items = soup.find_all("item")

    # 1) From the RSS items, extract the URLs we care about.
    impact_xmls, impact_data = _extract_impact_urls_from_rss_items(items)

    # 2) Parse the XML "calculation" files to build initial disasters dict.
    disasters, counter = _parse_calculation_xmls(impact_xmls)

    # 3) Parse the "impact_data" pages that lead to locations.xml and extend disasters.
    disasters, counter = _parse_impact_data_locations(impact_data, disasters, counter)

    # NOTE: total_red is currently stubbed out; we keep it for future use.
    total_red = 0

    return disasters, total_red


def assets() -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, str]]]:
    """
    A — ASSETS (DATA INPUT)

    Load company / contractor asset data (cities, countries, assets, etc.)
    from a local CSV file (for example ``assets.csv``).

    The CSV is expected to have at least the columns:
      - asset_id    (anonymized unique ID, no PII)
      - city
      - country
      - type        (e.g. 'personnel', 'building', 'vehicle', ...)

    Returns:
      cities:    mapping[str, str]   – optional lookup of city_id -> city name
      countries: mapping[str, str]   – optional lookup of country_id -> country name
      assets_by_id: mapping[str, dict[str, str]] – core asset records used for
        impact matching. Each asset dict should at least contain
        ``city``, ``country``, and ``type``.
    """
    assets_by_id: dict[str, dict[str, str]] = {}

    try:
        with open("assets.csv", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                asset_id = row.get("asset_id")
                if not asset_id:
                    # Skip rows without a usable asset_id
                    continue
                # Normalise keys we care about; keep the rest as-is for flexibility.
                asset_record: dict[str, str] = {
                    "unique_id": asset_id,
                    "city": row.get("city", ""),
                    "country": row.get("country", ""),
                    "type": row.get("type", ""),
                }
                # Optionally keep any extra columns from the CSV:
                for k, v in row.items():
                    if k not in asset_record and v is not None:
                        asset_record[k] = v

                assets_by_id[asset_id] = asset_record
    except FileNotFoundError:
        assets_by_id = {}

    cities: dict[str, str] = {}     # e.g. city_id -> city name
    countries: dict[str, str] = {}  # e.g. country_id -> country name

    return cities, countries, assets_by_id


def intel(
    disasters: dict[int, dict[str, str]],
    cities: dict[str, str],
    countries: dict[str, str],
    assets_by_id: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], list[list[str]]]:
    """
    I — INTEL (DATA PROCESSING)

    Cross-reference disaster locations with company assets.
    """
    _ = (cities, countries)

    matches: list[dict[str, str]] = []
    outreach_list: list[list[str]] = []

    for disaster_id, disaster in disasters.items():
        loc_key = (disaster.get("city"), disaster.get("country"))

        impacted_asset_ids = [
            asset_id
            for asset_id, asset in assets_by_id.items()
            if (asset.get("city"), asset.get("country")) == loc_key
        ]

        for asset_id in impacted_asset_ids:
            asset = assets_by_id.get(asset_id, {})
            match = {
                "unique_id": asset.get("unique_id", asset_id),
                "city": disaster.get("city", ""),
                "country": disaster.get("country", ""),
                "type": disaster.get("type", ""),
                "asset_type": asset.get("type", ""),
            }
            matches.append(match)
            outreach_list.append([match["unique_id"], match["type"]])

    return matches, outreach_list


def disseminate(
    matches: list[dict[str, str]],
    outreach_list: list[list[str]],
    total_red: int,
    debug: bool = False,
) -> None:
    """
    D — DISSEMINATE (OUTPUT)

    - Print human-readable details about impacted assets.
    - Write the outreach CSV file.
    - Optionally launch the static dashboard UI (disabled in debug mode).
    """
    for match in matches:
        print(f'Asset unique id: {match.get("unique_id")}')
        print(
            f'Location: {match.get("city")}, {match.get("country")}'
        )
        if match.get("type") == "EQ":
            print("Disaster type: earthquake")
        else:
            print(f'Disaster type: {match.get("type")}')

    print("TOTAL NUMBER OF RED-LEVEL ALERTS:")
    print(total_red)

    if not debug:
        srv = serve_static_and_open()
        time.sleep(3)

    with open("affected.csv", "w", newline="", encoding="utf-8") as tempfile:
        csv_writer = csv.writer(tempfile)
        csv_writer.writerow(["unique_id", "disaster_type"])
        csv_writer.writerows(outreach_list)


def track_disasters(debug: bool = False) -> None:
    """
    Orchestrator for the full disaster tracking pipeline.

    RAID-style flow:
      R — recon()        : collect disaster intel
      A — assets()       : load asset inventory
      I — intel()        : assess impact
      D — disseminate()  : output / deliver intel product
    """
    disasters, total_red = recon()
    cities, countries, assets_by_id = assets()
    matches, outreach_list = intel(
        disasters, cities, countries, assets_by_id
    )
    disseminate(matches, outreach_list, total_red, debug=debug)
