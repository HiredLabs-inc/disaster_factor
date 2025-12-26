# src/disaster_factor/core.py

# IMPORTS
from __future__ import annotations
from bs4 import BeautifulSoup
from pathlib import Path
import requests
import csv
import time
import os
from typing import Any

from .helpers import serve_static_and_open


# -----------------------------
# GDACS JSON pipeline helpers
# -----------------------------

def _find_text_suffix(tag, suffix: str) -> str:
    """
    Find first sub-tag whose name ends with suffix (case-insensitive) and return stripped text.
    """

    t = tag.find(lambda x: getattr(x, "name", None) and x.name.lower().endswith(suffix))
    return (t.text or "").strip() if t and t.text else ""


def _get_json(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """Fetch JSON and return as dict."""
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object at {url}, got {type(data).__name__}")
    return data


def _extract_impact_export_url(eventdata_json: dict[str, Any]) -> str:
    """
    Step-3 JSON path: properties.impacts[0].resource.impact. Return "" if missing.
    """

    props = eventdata_json.get("properties")
    if not isinstance(props, dict):
        return ""
    impacts = props.get("impacts")
    if not isinstance(impacts, list) or not impacts:
        return ""
    first = impacts[0]
    if not isinstance(first, dict):
        return ""
    resource = first.get("resource")
    if not isinstance(resource, dict):
        return ""
    impact_url = resource.get("impact")
    return impact_url if isinstance(impact_url, str) and impact_url else ""


def _scalars_to_dict(datum: dict[str, Any]) -> dict[str, str]:
    """
    Convert Step-4 scalar list to name->value mapping.
    """

    out: dict[str, str] = {}
    
    scalars = datum.get("scalars")
    if not isinstance(scalars, dict):
        return out
    scalar_list = scalars.get("scalar")
    if not isinstance(scalar_list, list):
        return out
    for s in scalar_list:
        if not isinstance(s, dict):
            continue
        name = s.get("name")
        value = s.get("value")
        if isinstance(name, str) and isinstance(value, str):
            out[name] = value

    return out


def _parse_impact_json_to_disasters(impact_json: dict[str, Any], eventtype: str, eventid: str, lat: str = None, long: str = None, comprehensive_aliases: bool = False) -> list[dict[str, str]]:
    """
    Step-4 impact JSON -> disasters list.
    
    Args:
        impact_json: GDACS impact JSON data
        eventtype: Type of disaster event
        eventid: ID of disaster event
        lat: Optional latitude override
        long: Optional longitude override
        comprehensive_aliases: If True, process ALL available aliases instead of priority aliases only
    """
    datums = impact_json.get("datums")
    if not isinstance(datums, list):
        return []

    # All known GDACS aliases from exhaustive discovery
    all_gdacs_aliases = ['airport', 'airports', 'alert', 'alert parameters', 'aru', 'city', 'country', 'hydro', 'input parameters', 'landtable', 'nuclear power plant', 'pop', 'ports', 'province', 'urbanareas']
    
    # Priority aliases for backward compatibility
    priority = ["city", "urbanareas", "aru", "province", "country"]

    blocks: dict[str, dict[str, Any]] = {}
    for block in datums:
        if not isinstance(block, dict):
            continue
        alias = block.get("alias")
        if isinstance(alias, str):
            blocks[alias.strip().casefold()] = block

    # Choose which aliases to process
    if comprehensive_aliases:
        # Process ALL available aliases that have data
        aliases_to_process = [alias for alias in all_gdacs_aliases if alias in blocks]
    else:
        # Use priority logic for backward compatibility
        aliases_to_process = []
        for a in priority:
            if a in blocks:
                aliases_to_process = [a]  # Only the first priority alias
                break
        if not aliases_to_process:
            return []

    disasters: list[dict[str, str]] = []
    
    # Process each alias separately
    for chosen_alias in aliases_to_process:
        chosen = blocks[chosen_alias]
        records = chosen.get("datum")
        if not isinstance(records, list) or not records:
            continue
            
        for datum in records:
            if not isinstance(datum, dict):
                continue

            s = _scalars_to_dict(datum)
            country = (
                s.get("CNTRY_NAME")
                or s.get("COUNTRY")
                or s.get("Country")
                or s.get("country")
                or s.get("CNTRY")
                or ""
            ).strip()

            if not country:
                continue

            # Extract city name for aliases that have location data
            if chosen_alias in ("aru", "city", "urbanareas", "province", "airport", "airports", "ports", "hydro", "nuclear power plant"):
                name = (
                    s.get("Name")
                    or s.get("NAME")
                    or s.get("CITY_NAME")
                    or s.get("cityname")
                    or s.get("URBAN_NAME")
                    or s.get("PROV_NAME")
                    or s.get("PROVINCE")
                    or s.get("ADMIN1")
                    or s.get("admin1")
                    or s.get("ADM1_NAME")
                    or s.get("AIRPORT_NAME")
                    or s.get("PORT_NAME")
                    or s.get("FACILITY_NAME")
                    or ""
                ).strip()
                city = name
            else:
                city = ""

            disasters.append({
                "city": city, 
                "country": country, 
                "type": eventtype,
                "eventid": eventid,
                "alias_source": chosen_alias,
                "latitude": lat,
                "longitude": long
            })

    return disasters


def _dedupe_disasters(disasters: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Deduplicate by (type,country,city), normalized.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for d in disasters:
        city = (d.get("city") or "").strip()
        country = (d.get("country") or "").strip()
        dtype = (d.get("type") or "").strip()
        key = (dtype.casefold(), country.casefold(), city.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "city": city, 
            "country": country, 
            "type": dtype,
            "eventid": d.get("eventid", ""),
            "alias_source": d.get("alias_source", ""),
            "latitude": d.get("latitude"),
            "longitude": d.get("longitude")
        })

    return out


# -----------------------------
# RAID pipeline
# -----------------------------

def recon(debug: bool = False, comprehensive_aliases: bool = False) -> tuple[list[dict[str, str]], int]:
    """
    R — RECON (DATA RETRIEVAL)

    GDACS JSON pipeline:
      RSS -> (eventtype,eventid,alertlevel) -> construct eventdata URL
      eventdata JSON -> impact export URL
      impact JSON -> disasters list

    Returns:
      (disasters, total_red)

    disasters: list[dict[str,str]] with keys {city, country, type}
    total_red: count of RSS items with alertlevel == "Red"
    """

    rss_url = "https://www.gdacs.org/XML/RSS.xml"

    resp = requests.get(rss_url, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, features="xml")
    items = soup.find_all("item")

    # Build events directly from eventtype/eventid; count total_red from alertlevel.
    events: list[dict[str, str]] = []
    total_red = 0
    for item in items:
        # Extract latitude and longitude from geo:Point
        geo_point = item.find("geo:Point")
        lat = None
        long = None
        if geo_point:
            lat_elem = geo_point.find("geo:lat")
            long_elem = geo_point.find("geo:long")
            lat = lat_elem.text if lat_elem else None
            long = long_elem.text if long_elem else None

        alert = _find_text_suffix(item, "alertlevel")
        if alert.casefold() == "red":
            total_red += 1

        eventtype = _find_text_suffix(item, "eventtype")
        eventid = _find_text_suffix(item, "eventid")
        if not eventtype or not eventid:
            continue

        eventdata_url = (
            "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
            f"?eventtype={eventtype}&eventid={eventid}"
        )
        events.append(
            {
            "eventtype": eventtype,
            "eventid": eventid,
            "eventdata_url": eventdata_url,
            "latitude": lat,
            "longitude": long,
            }
        )

    # Dev cap (optional)
    cap_raw = os.getenv("GDACS_DEV_CAP", "").strip()
    if cap_raw.isdigit() and int(cap_raw) > 0:
        cap = int(cap_raw)
        events = events[:cap]

    disasters: list[dict[str, str]] = []

    for idx, ev in enumerate(events, start=1):
        if debug and (idx == 1 or idx % 10 == 0):
            print(f"[RECON] progress {idx}/{len(events)}")

        eventtype = ev["eventtype"]
        eventid = ev["eventid"]
        eventdata_url = ev["eventdata_url"]

        try:
            eventdata_json = _get_json(ev["eventdata_url"], timeout=20)
        except Exception as e:
            continue

        impact_url = _extract_impact_export_url(eventdata_json)
        if not impact_url:
            continue

        try:
            impact_json = _get_json(impact_url, timeout=20)
        except Exception as e:
            continue

        disasters.extend(_parse_impact_json_to_disasters(impact_json, eventtype, eventid, ev.get("latitude"), ev.get("longitude"), comprehensive_aliases))

        # GDACS respect
        time.sleep(0.02)

    disasters = _dedupe_disasters(disasters)

    if debug:
        print("[RECON] disasters (deduped):", len(disasters))
        
        # Count disasters by type (eventtype)
        disaster_counts = {}
        for d in disasters:
            event_type = d.get('type', 'unknown')
            disaster_counts[event_type] = disaster_counts.get(event_type, 0) + 1
        
        # Print count for each disaster type
        print("\n[RECON] Disaster counts by type:")
        for event_type in sorted(disaster_counts.keys()):
            print(f"  {event_type}: {disaster_counts[event_type]}")
        
                
        print("\n[RECON] Disaster locations by alias source:")
        
        # Group disasters by alias source
        grouped = {}
        for d in disasters:
            alias = d.get('alias_source', 'unknown')
            if alias not in grouped:
                grouped[alias] = []
            grouped[alias].append(d)
        
        # Print grouped by alias
        for alias in sorted(grouped.keys()):
            print(f"\n  {alias.upper()} ({len(grouped[alias])} records):")
            for d in grouped[alias]:
                city = d.get('city', 'N/A')
                country = d.get('country', 'N/A')
                lat = d.get('latitude')
                long = d.get('longitude')
                
                # Format coordinates rounded to 4 decimal places
                lat_str = f"{float(lat):.3f}" if lat and lat.replace('.', '').isdigit() else "N/A"
                long_str = f"{float(long):.3f}" if long and long.replace('.', '').isdigit() else "N/A"
                
                print(f"    {city:25} | {country:15} | {lat_str:8} | {long_str:9}")

    return disasters, total_red


def assets() -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, str]]]:
    """
    A — ASSETS (DATA INPUT)

    Load company / contractor asset data (cities, countries, assets, etc.) from assets.csv

    The CSV is expected to have at least the columns:
      - asset_id    (anonymized unique ID, no PII)
      - city
      - country
      - type        (e.g. 'personnel', 'building', 'vehicle', ...)

    Returns:
      cities:    mapping[str, str]   optional lookup of city_id -> city name
      countries: mapping[str, str]   optional lookup of country_id -> country name
      assets_by_id: mapping[str, dict[str, str]]  core asset records used for
        impact matching. Each asset dict should at least contain
        ``city``, ``country``, and ``type``.
    """
    cities: dict[str, str] = {}
    countries: dict[str, str] = {}
    assets_by_id: dict[str, dict[str, str]] = {}

    csv_path = Path(__file__).resolve().parents[2] / "tests" / "data" / "assets.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"assets.csv not found at {csv_path}")

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            asset_id = (row.get("unique_id") or "").strip()
            if not asset_id:
                continue

            assets_by_id[asset_id] = row
            cities[asset_id] = (row.get("city") or "").strip()
            countries[asset_id] = (row.get("country") or "").strip()

    return cities, countries, assets_by_id


def intel(
    disasters: list[dict[str, str]],
    cities: dict[str, str],
    countries: dict[str, str],
    assets_by_id: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], list[list[str]]]:
    """
    I — INTEL (DATA PROCESSING)

    Cross-reference disaster locations with company assets.
    """
    matches: list[dict[str, str]] = []
    outreach_list: list[dict[str, str]] = []

    for asset_id, asset in assets_by_id.items():
        asset_city = (cities.get(asset_id) or "").strip().casefold()
        asset_country = (countries.get(asset_id) or "").strip().casefold()

        for d in disasters:
            d_city = (d.get("city") or "").strip().casefold()
            d_country = (d.get("country") or "").strip().casefold()
            d_type = (d.get("type") or "").strip()

            if not d_country or asset_country != d_country:
                continue

            # If disaster has a city/locality, require match; otherwise country-only match.
            if d_city and asset_city != d_city:
                continue

            matches.append(
                {
                    "unique_id": asset_id,
                    "city": cities.get(asset_id, ""),
                    "country": countries.get(asset_id, ""),
                    "event_type": d_type,
                }
            )
            outreach_list.append(asset)

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
    - Write the affected CSV file.
    - Launch the static dashboard UI (disabled in debug mode).
    """

    # Write affected.csv
    if matches:
        fieldnames = list(matches[0].keys())
    else:
        fieldnames = ["unique_id", "city", "country", "event_type"]

    affected_path = Path(__file__).resolve().parents[2] / "tests" / "data" / "affected.csv"

    with affected_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in matches:
            writer.writerow(row)

    # Serve dashboard static
    if not debug:
        serve_static_and_open()


def track_disasters(debug: bool = False) -> None:
    """
    Orchestrator for the full disaster tracking pipeline.

    RAID-style flow:
      R — recon()        : collect disaster intel
      A — assets()       : load asset inventory
      I — intel()        : assess impact
      D — disseminate()  : output / deliver intel product
    """
    disasters, total_red = recon(debug=debug)
    cities, countries, assets_by_id = assets()
    matches, outreach_list = intel(disasters, cities, countries, assets_by_id)
    disseminate(matches, outreach_list, total_red, debug=debug)
