# src/disaster_factor/core.py

# IMPORTS
from __future__ import annotations
from bs4 import BeautifulSoup
from pathlib import Path
import requests
import re
import csv
import json
import math
import time
import os
from contextlib import contextmanager
from time import perf_counter
from typing import Any, Optional, Tuple, List, Dict
from .helpers import serve_static_and_open
import logging

import logging
from pathlib import Path

LOG_FILE = Path("disaster_factor.log")

logger = logging.getLogger(__name__)

def setup_logging(*, debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    # Prevent duplicate logs if setup_logging() is called more than once
    root.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Terminal
    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(fmt)

    # File
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)

    root.addHandler(sh)
    root.addHandler(fh)



# ------------------------------------------------------------------------------------
# GENERAL utilities
# ------------------------------------------------------------------------------------

@contextmanager
def _timer(label: str, *, enabled: bool = True) -> None:
    start = perf_counter()
    try:
        yield
    finally:
        if enabled:
            elapsed = perf_counter() - start
            logger.info(f"[TIMER] {label}: {elapsed:.3f}s")

def _get_geocoding_api_key() -> str:
    """Get Google Geocoding API key from environment or user input."""

    api_key = os.getenv("GOOGLE_GEOCODING_API_KEY")
    if not api_key:
        logger.info("[GEOCODE] Google Geocoding API key not found in environment")
        api_key = input("Enter your Google Geocoding API key: ").strip()
        if not api_key:
            raise ValueError("Google Geocoding API key is required")
        os.environ["GOOGLE_GEOCODING_API_KEY"] = api_key
        logger.info("[GEOCODE] API key saved to environment for this session")
    return api_key


def _reverse_geocode(lat: float, lon: float) -> dict[str, str]:
    """Convert coordinates to city and country using Google Geocoding API V4 Beta."""

    try:
        api_key = _get_geocoding_api_key()

        # Google Reverse Geocoding API V4 Beta URL
        url = f"https://geocode.googleapis.com/v4beta/geocode/location/{lat},{lon}"
        params = {
            'key': api_key,
        }

        response = requests.get(url, params=params, timeout=10.0)
        response.raise_for_status()

        data = response.json()

        if not data.get('results'):
            return {
                'city': 'Unknown',
                'country': 'Unknown'
            }

        # Extract location components from first result
        result = data['results'][0]
        components = {comp['types'][0]: comp['longText']
                     for comp in result.get('addressComponents', [])
                     if comp.get('types')}

        location_info = {
            'city': components.get('locality', ''),
            'country': components.get('country', '')
        }

        # Fill missing city from formatted address if needed
        if not location_info['city'] and result.get('formattedAddress'):
            # Try to extract city from formatted address
            parts = result['formattedAddress'].split(',')
            if len(parts) >= 2:
                location_info['city'] = parts[0].strip()

        # Ensure we always return values
        if not location_info['city']:
            location_info['city'] = 'Unknown'
        if not location_info['country']:
            location_info['country'] = 'Unknown'

        return location_info

    except Exception as e:
        return {
            'city': 'Unknown',
            'country': 'Unknown'
        }


# ------------------------------------------------------------------------------------
# GDACS helpers
# ------------------------------------------------------------------------------------

def _find_text_suffix(tag, suffix: str) -> str:
    """Find first sub-tag whose name ends with suffix (case-insensitive) and return stripped text."""

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


def _extract_impact_url(eventdata_json: dict[str, Any]) -> str:
    """Step-3 JSON path: properties.impacts[0].resource.impact. Return "" if missing."""

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
    """Convert Step-4 scalar list to name->value mapping."""

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

def check_missing_impact_urls(eventdata_json: dict[str, Any]) -> tuple[bool, str]:
    """
    Check if a GDACS eventdata JSON contains at least one impact URL.

    Args:
        eventdata_json: The geteventdata JSON (step-3) for a disaster/event

    Returns:
        (has_impact_url, reason_if_missing)
    """
    props = eventdata_json.get("properties")
    if not isinstance(props, dict):
        return False, "Missing properties"

    impacts = props.get("impacts")
    if not isinstance(impacts, list) or not impacts:
        return False, "No impacts array"

    for impact in impacts:
        if not isinstance(impact, dict):
            continue
        resource = impact.get("resource")
        if isinstance(resource, dict):
            url = resource.get("impact")
            if isinstance(url, str) and url.strip():
                return True, ""

    return False, "No impact URL found in resources"

# def _print_coverage_analysis(matches, assets_by_id, impact_data):
    """Print detailed hierarchical coverage analysis."""

    # Method matching results
    polygon_matches = [m for m in matches if m['impact_method'] == 'POLYGON']
    alias_matches = [m for m in matches if m['impact_method'] == 'ALIAS']
    coordinate_matches = [m for m in matches if m['impact_method'] == 'COORDINATE']

    # Coverage calculations
    total_assets = len(assets_by_id)
    total_impacted = len(matches)

    # Print comprehensive analysis
    # print("\n" + "="*60)
    # print("HIERARCHICAL COVERAGE ANALYSIS")
    # print("="*60)

    # Method matching results
    # print("\n[INTEL] Method Matching Results:")
    # print(f"  Polygon method matched: {len(polygon_matches)} assets")
    # print(f"  Alias method matched: {len(alias_matches)} assets")
    # print(f"  Coordinate method matched: {len(coordinate_matches)} assets")
    # print(f"  Total assets impacted: {total_impacted}/{total_assets} ({total_impacted/total_assets*100:.1f}%)")

    # Coverage analysis
    # print("\n[INTEL] Method Coverage Analysis:")
    # print(f"  Polygon coverage: {len(polygon_matches)}/{total_assets} assets ({len(polygon_matches)/total_assets*100:.1f}%)")
    # print(f"  Alias coverage: {len(alias_matches)}/{total_assets} assets ({len(alias_matches)/total_assets*100:.1f}%)")
    # print(f"  Coordinate coverage: {len(coordinate_matches)}/{total_assets} assets ({len(coordinate_matches)/total_assets*100:.1f}%)")

    # Method effectiveness
    # print(f"\n[INTEL] Method Effectiveness:")
    # print(f"  1st: Polygon method ({len(polygon_matches)} matches)")
    # print(f"  2nd: Alias method ({len(alias_matches)} matches)")
    # print(f"  3rd: Coordinate method ({len(coordinate_matches)} matches)")

    # Keep only the headline counts (no coverage %, no effectiveness, no breakdown tables)
    # print(f"[INTEL] Assets loaded: {total_assets}")
    # print(f"[INTEL] Assets impacted: {total_impacted}")
    # print(f"[INTEL] Polygon matches: {len(polygon_matches)}")
    # print(f"[INTEL] Alias matches: {len(alias_matches)}")
    # print(f"[INTEL] Coordinate matches: {len(coordinate_matches)}")



# ------------------------------------------------------------------------------------
# POLYGON helpers
# ------------------------------------------------------------------------------------

def _extract_polygons_from_impact(impact_json: dict) -> List[List[Tuple[float, float]]]:
    """
    Extract polygons from impact JSON for analysis.

    VARIABLE LEGEND:
    datums   -> "datums"   -> Collection of geographic area objects from GDACS
    block    -> item in "datums" -> Entire object containing "alias" and "datum" fields
    records  -> "datum"    -> List of polygon data records within the block
    record   -> item in "datum" -> Single polygon record with coordinates
    """
    polygons = []
    datums = impact_json.get("datums", [])

    for block in datums:
        if isinstance(block, dict):
            records = block.get("datum", [])
            if isinstance(records, list):
                for record in records:
                    if isinstance(record, dict):
                        # Try all polygon extraction methods
                        shape_coords = _extract_shape_json(record)
                        if shape_coords:
                            polygons.append(shape_coords)
                            continue
                        bbox_coords = _extract_bounding_box(record)
                        if bbox_coords:
                            polygons.append(bbox_coords)
                            continue
                        wkt_coords = _extract_wkt_from_record(record)
                        if wkt_coords:
                            polygons.append(wkt_coords)
                            continue

    return polygons


def _extract_shape_json(record: dict) -> List[Tuple[float, float]]:
    """Extract coordinates from SHAPE_JSON field."""
    scalars_dict = _scalars_to_dict(record)
    value = scalars_dict.get("SHAPE_JSON")

    if not value:
        return []

    try:
        shape_data = json.loads(value)
        if shape_data.get("type") == "Polygon" and "coordinates" in shape_data:
            coords = shape_data["coordinates"][0]
            return [(coord[1], coord[0]) for coord in coords]
    except (json.JSONDecodeError, KeyError, IndexError):
        pass

    return []


def _extract_bounding_box(record: dict) -> List[Tuple[float, float]]:
    """Extract coordinates from boundinboxjson field."""
    scalars_dict = _scalars_to_dict(record)
    value = scalars_dict.get("boundiboxjson")

    if not value:
        return []

    try:
        shape_data = json.loads(value)
        if shape_data.get("type") == "Polygon" and "coordinates" in shape_data:
            coords = shape_data["coordinates"][0]
            return [(coord[1], coord[0]) for coord in coords]
    except (json.JSONDecodeError, KeyError, IndexError):
        pass

    return []


def _extract_wkt_from_record(record: dict) -> List[Tuple[float, float]]:
    """Extract WKT from SHAPE field."""
    scalars_dict = _scalars_to_dict(record)
    value = scalars_dict.get("SHAPE")

    if not value:
        return []

    return _parse_wkt_polygon(value)


def _parse_wkt_polygon(wkt_string: str) -> List[Tuple[float, float]]:
    """Parse WKT POLYGON format."""
    if not wkt_string.startswith("POLYGON"):
        return []

    # Extract coordinates between parentheses
    start = wkt_string.find("(") + 1
    end = wkt_string.rfind(")")
    coords_str = wkt_string[start:end]

    # Split into coordinate pairs
    coord_pairs = coords_str.split(",")
    coords = []

    for pair in coord_pairs:
        try:
            # Split into lon, lat and convert to float
            parts = pair.strip().split()
            if len(parts) >= 2:
                lon = float(parts[0])
                lat = float(parts[1])
                coords.append((lat, lon))  # Convert to (lat, lon) format
        except (ValueError, IndexError):
            continue

    return coords if len(coords) >= 3 else []


def _point_in_polygon(lat: float, lon: float, polygon: List[Tuple[float, float]]) -> bool:
    """Ray casting algorithm for point-in-polygon test."""
    if len(polygon) < 3:
        return False

    x, y = lon, lat
    n = len(polygon)
    inside = False

    p1x, p1y = polygon[0][1], polygon[0][0]
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n][1], polygon[i % n][0]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y

    return inside


def _asset_in_polygons(asset_coords: Tuple[float, float], polygons: List[List[Tuple[float, float]]]) -> bool:
    """Check if asset coordinates are within any disaster polygons."""
    if not asset_coords or not polygons:
        return False

    for polygon in polygons:
        if _point_in_polygon(asset_coords[0], asset_coords[1], polygon):
            return True

    return False


def _polygon_analysis(asset_coords: tuple[float, float], impact_data: dict) -> dict[str, Any]:
    """Check if asset is impacted via polygon boundaries.

    Args:
        asset_coords: (latitude, longitude) tuple
        impact_data: dict mapping eventid → {impact_json, eventtype, coordinates}

    Returns:
        {'impacted': bool, 'event_id': str} or {'impacted': False}
    """
    for eventid, data in impact_data.items():
        polygons = _extract_polygons_from_impact(data['impact_json'])
        if polygons:
            if _asset_in_polygons(asset_coords, polygons):
                return {'impacted': True, 'event_id': eventid}

    return {'impacted': False}


# def _calculate_polygon_impact_score(asset: dict, polygons: List[List[Tuple[float, float]]]) -> float:
#     """Calculate impact score based on polygon analysis."""
#     # For polygon analysis, assets inside polygon get high score
#     # Could be enhanced based on distance to polygon center
#     return base_score



# ------------------------------------------------------------------------------------
# ALIAS helpers
# ------------------------------------------------------------------------------------

def _parse_impact_json_to_disasters(
    impact_json: dict[str, Any],
    eventtype: str,
    eventid: str,
    lat: str = None,
    long: str = None) -> list[dict[str, str]]:
    """
    Parse GDACS impact JSON into standardized disaster records.
    GDACS provides multiple data types (city, ports, airport, etc.) in each impact.
    Prioritizes by precision and uses only one type for consistent alias matching:
        city > urbanareas > ports > airport > aru
    Returns list of disaster records with country/city for asset matching.
    """

    # Priority aliases: city data is most precise for general asset matching
    priority = ["city", "urbanareas", "ports", "airport", "aru"]

    datums = impact_json.get("datums")
    if not isinstance(datums, list):
        return []

    # Find first block matching our priority hierarchy
    chosen_block = next(
        (block for block in datums
         if isinstance(block, dict)
         and block.get("alias", "").strip().casefold() in priority),
        None
    )
    if not chosen_block:
        return []

    chosen_alias = chosen_block.get("alias", "").strip().casefold()

    disasters: list[dict[str, str]] = []

    # Process only the chosen priority block (skip others for consistency)
    records = chosen_block.get("datum")
    if not isinstance(records, list) or not records:
        return disasters

    for datum in records:
        if not isinstance(datum, dict):
            continue
        s = _scalars_to_dict(datum)
        # Extract country using multiple possible GDACS field names
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

        # Extract city name based on the chosen data type
        if chosen_alias in ("city", "urbanareas", "ports", "airport", "aru"):
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
    """Deduplicate by (type,country,city), normalized."""
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
            # "alert_level" : d.get("alert_level", "")
        })

    return out


def _alias_analysis(asset_city: str, asset_country: str, disasters: list[dict[str, str]]) -> dict[str, Any]:
    """Check if asset is impacted by any disaster via alias matching.

    Args:
        asset_city: Asset city (casefolded)
        asset_country: Asset country (casefolded)
        disasters: List of disaster records

    Returns:
        {'impacted': bool, 'event_id': str} or {'impacted': False}
    """
    for d in disasters:
        d_city = (d.get("city") or "").strip().casefold()
        d_country = (d.get("country") or "").strip().casefold()

        if not d_country or asset_country != d_country:
            continue

        if d_city and asset_city != d_city:
            continue

        return {
            'impacted': True,
            'event_id': d.get("eventid", "unknown"),
            'disaster_city': d.get("city", "unknown"),
            'disaster_country': d.get("country", "unknown")
        }

    return {'impacted': False}



# ------------------------------------------------------------------------------------
# COORDINATE helpers
# ------------------------------------------------------------------------------------

def _extract_disaster_coordinates(impact_json: dict, event_id: str) -> List[Dict]:
    """Extract all disaster coordinates from impact data, with provenance."""
    coords: List[Dict] = []

    datums = impact_json.get("datums", [])
    for block in datums:
        if not isinstance(block, dict):
            continue

        alias = (block.get("alias") or "").strip().casefold()
        records = block.get("datum", [])
        if not isinstance(records, list):
            continue

        for record in records:
            if not isinstance(record, dict):
                continue
            coord = _extract_single_coordinate(record)
            if coord:
                coord["event_id"] = event_id
                coord["alias"] = alias
                coords.append(coord)

    return coords


def _dedupe_coordinates(coords: List[Dict], decimals: int = 4) -> List[Dict]:
    """Remove duplicate coordinates by rounding to specified precision.

    Args:
        coords: List of coordinate dictionaries with 'latitude' and 'longitude' keys
        decimals: Number of decimal places for precision (default=4, ~11m accuracy)

    Returns:
        List of unique coordinates with duplicates removed
    """
    seen = set()
    unique_coords = []

    for coord in coords:
        # Dedupe within provenance (don’t collapse different events into one)
        key = (
            coord.get("event_id", ""),
            coord.get("alias", ""),
            round(coord.get("latitude"), decimals),
            round(coord.get("longitude"), decimals)
        )
        if key not in seen:
            seen.add(key)
            unique_coords.append(coord)

    return unique_coords


def _extract_single_coordinate(record: dict) -> Optional[Dict]:
    """Extract a single coordinate from a datum record with strict field matching."""
    scalars_dict = _scalars_to_dict(record)

    lat: Optional[float] = None
    lon: Optional[float] = None
    # Strict, case-insensitive exact-name matching only
    lat_names = {"lat", "latitude"}
    lon_names = {"lon", "long", "longitude"}

    for name, value in scalars_dict.items():
        if value is None:
            continue
        s = str(value).strip()
        if not s:
            continue
        try:
            num = float(s)
        except Exception:
            continue

        key = str(name).strip().casefold()
        if key in lat_names:
            lat = num
        elif key in lon_names:
            lon = num

    # Numeric + range validation
    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0):
        return None
    if not (-180.0 <= lon <= 180.0):
        return None

    return {"latitude": lat, "longitude": lon}

def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in miles.

    Uses the haversine formula for great-circle distance on a sphere.
    Accuracy: ±0.5-1.0%

    Args:
        lat1, lon1: First point coordinates in decimal degrees
        lat2, lon2: Second point coordinates in decimal degrees

    Returns:
        Distance in miles (float)
    """
    R = 3959  # Earth's radius in miles (3958.8 exact, 3959 standard)

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
            math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    c = 2 * math.asin(math.sqrt(a))

    return R * c


def _coordinate_analysis(asset_coords: tuple[float, float], impact_data: dict, top_n: int = 5) -> dict[str, Any]:
    """Return the top-N nearest disaster impact coordinates to this asset.

    No boolean cutoff. Pure proximity ranking for downstream decision logic.

    Args:
        asset_coords: (latitude, longitude) tuple
        impact_data: dict mapping eventid → {impact_json, eventtype, coordinates}
        top_n: number of nearest candidates to return

    Returns:
        {
          'nearest': [
             {'event_id': str, 'alias': str, 'latitude': float, 'longitude': float, 'distance_miles': float},
             ...
          ]
        }  # empty list if none found / invalid asset coords
    """
    if not asset_coords or len(asset_coords) < 2:
        return {"nearest": []}
    if not isinstance(asset_coords[0], (int, float)) or not isinstance(asset_coords[1], (int, float)):
        return {"nearest": []}

    candidates: List[Dict] = []

    for eventid, data in (impact_data or {}).items():
        impact_json = (data or {}).get("impact_json") or {}
        coords = _extract_disaster_coordinates(impact_json, eventid)
        if coords:
            candidates.extend(coords)

    if not candidates:
        return {"nearest": []}

    # Dedupe BEFORE ranking
    candidates = _dedupe_coordinates(candidates)

    # Compute proximity for every candidate (global ranking)
    for c in candidates:
        c["distance_miles"] = _haversine_distance(
            float(asset_coords[0]), float(asset_coords[1]),
            float(c["latitude"]), float(c["longitude"])
        )

    candidates.sort(key=lambda c: (c["distance_miles"], c.get("event_id", ""), c.get("alias", ""), c["latitude"], c["longitude"]))

    nearest = [
        {
            "event_id": c.get("event_id", "unknown"),
            "alias": c.get("alias", ""),
            "latitude": c["latitude"],
            "longitude": c["longitude"],
            "distance_miles": c["distance_miles"],
        }
        for c in candidates[: max(0, int(top_n))]
    ]

    return {"nearest": nearest}

# ------------------------------------------------------------------------------------
# RAID pipeline
# ------------------------------------------------------------------------------------

def recon(debug: bool = False) -> tuple[list[dict[str, str]], int, dict[str, dict]]:
    """
    R — RECON (DATA RETRIEVAL)

    GDACS JSON pipeline with hierarchical data collection:
      RSS -> (eventtype,eventid,alertlevel) -> construct eventdata URL
      eventdata JSON -> impact URL
      impact JSON -> disasters list + preserve impact data

    Returns:
      (disasters, total_red, impact_data)

    disasters: list[dict[str,str]] with keys {city, country, type}
    total_red: count of RSS items with alertlevel == "Red"
    impact_data: dict mapping eventid -> {impact_json, eventtype, coordinates}
    """

    rss_url = "https://www.gdacs.org/XML/RSS.xml"

    resp = requests.get(rss_url, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, features="xml")
    items = soup.find_all("item")

    # Timing
    t_recon_start = perf_counter()
    t_eventdata_total = 0.0
    t_impact_total = 0.0
    t_eventdata_max = 0.0
    t_impact_max = 0.0
    slowest_eventdata = ""
    slowest_impact = ""
    eventdata_ok = 0
    impact_ok = 0

    # geo:Point audit (RSS-level coordinates)
    geo_point_total = 0
    geo_point_missing_tag = 0
    geo_point_missing_latlon = 0
    geo_point_non_numeric = 0
    geo_point_valid = 0

    # Build events directly from eventtype/eventid; count total_red from alertlevel.
    events: list[dict[str, str]] = []
    total_red = 0

    # Store impact data for hierarchical analysis
    impact_data: dict[str, dict] = {}
    for item in items:
        geo_point_total += 1

        # Extract latitude and longitude from geo:Point (RSS-level)
        geo_point = item.find("geo:Point")
        lat = None
        long = None

        if not geo_point:
            geo_point_missing_tag += 1
        else:
            lat_elem = geo_point.find("geo:lat")
            long_elem = geo_point.find("geo:long")

            lat_text = (lat_elem.text or "").strip() if lat_elem else ""
            long_text = (long_elem.text or "").strip() if long_elem else ""

            if not lat_text or not long_text:
                geo_point_missing_latlon += 1
            else:
                try:
                    float(lat_text)
                    float(long_text)
                    lat = lat_text
                    long = long_text
                    geo_point_valid += 1
                except ValueError:
                    geo_point_non_numeric += 1
                    
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
    
    # Ambiguity breaker: how many disaster-records are produced per eventid BEFORE dedupe
    raw_disasters_by_event: dict[str, int] = {}
    raw_disasters_total = 0

    disasters: list[dict[str, str]] = []

    missing_impact_url_count = 0
    missing_impact_url_reasons: dict[str, int] = {}
    missing_impact_url_events: list[tuple[str, str]] = []

    for idx, ev in enumerate(events, start=1):
        if debug and (idx == 1 or idx % 10 == 0):
            logger.debug(f"[RECON] progress {idx}/{len(events)}")

        eventtype = ev["eventtype"]
        eventid = ev["eventid"]
        eventdata_url = ev["eventdata_url"]

        # --- eventdata fetch timing ---
        t0 = perf_counter()
        try:
            eventdata_json = _get_json(ev["eventdata_url"], timeout=20)
            dt = perf_counter() - t0
            t_eventdata_total += dt
            eventdata_ok += 1
            if dt > t_eventdata_max:
                t_eventdata_max = dt
                slowest_eventdata = ev["eventdata_url"]
        except Exception:
            dt = perf_counter() - t0
            t_eventdata_total += dt
            continue

        has_impact, reason = check_missing_impact_urls(eventdata_json)
        if not has_impact:
            missing_impact_url_count += 1
            missing_impact_url_reasons[reason] = missing_impact_url_reasons.get(reason, 0) + 1
            missing_impact_url_events.append((eventtype, eventid))

        impact_url = _extract_impact_url(eventdata_json)
        if not impact_url:
            continue

        # --- impact fetch timing ---
        t0 = perf_counter()
        try:
            impact_json = _get_json(impact_url, timeout=20)
            dt = perf_counter() - t0
            t_impact_total += dt
            impact_ok += 1
            if dt > t_impact_max:
                t_impact_max = dt
                slowest_impact = impact_url
        except Exception:
            dt = perf_counter() - t0
            t_impact_total += dt
            continue
        # Parse disasters from impact JSON (alias data)
        parsed = _parse_impact_json_to_disasters(
            impact_json, eventtype, eventid, ev.get("latitude"), ev.get("longitude")
        )

        raw_disasters_total += len(parsed)
        raw_disasters_by_event[eventid] = raw_disasters_by_event.get(eventid, 0) + len(parsed)

        disasters.extend(parsed)

        # Store impact data for hierarchical polygon/coordinate analysis
        lat_str = ev.get("latitude")
        lon_str = ev.get("longitude")
        coordinates = None
        if lat_str and lon_str:
            try:
                lat = float(lat_str)
                lon = float(lon_str)
                coordinates = (lat, lon)
            except ValueError:
                coordinates = None

        impact_data[eventid] = {
            "impact_json": impact_json,
            "eventtype": eventtype,
            "coordinates": coordinates
        }

        # GDACS respect
        time.sleep(0.02)

        if debug and (idx == 1 or idx % 10 == 0):
            avg_eventdata = t_eventdata_total / max(eventdata_ok, 1)
            avg_impact = t_impact_total / max(impact_ok, 1)

            logger.debug(
                f"[RECON][TIMER] {idx}/{len(events)} "
                f"eventdata avg={avg_eventdata:.2f}s max={t_eventdata_max:.2f}s | "
                f"impact avg={avg_impact:.2f}s max={t_impact_max:.2f}s"
            )

    disasters = _dedupe_disasters(disasters)

    if debug:
        logger.debug("[RECON] Hierarchical Collection Summary:")
        logger.debug(f"  Impact events collected: {len(impact_data)}")
        logger.debug(f"  Disasters extracted: {len(disasters)}")
        logger.debug(f"  Red alert events: {total_red}")

        logger.debug("\n[RECON] geo:Point audit (RSS-level):")
    
        # Explain 104 RSS items vs "Disasters extracted"
        logger.debug("\n[RECON] Disaster-records per event (pre-dedupe):")
        if raw_disasters_by_event:
            counts = list(raw_disasters_by_event.values())
            avg = (sum(counts) / len(counts)) if counts else 0.0
            logger.debug(f"  Events with impact parsed: {len(raw_disasters_by_event)}")
            logger.debug(f"  Raw disaster-records total: {raw_disasters_total}")
            logger.debug(f"  Per-event records: min={min(counts)} avg={avg:.2f} max={max(counts)}")

            top = sorted(raw_disasters_by_event.items(), key=lambda kv: kv[1], reverse=True)[:10]
            logger.debug("  Top events by records:")
            for eid, n in top:
                logger.debug(f"   - {eid}: {n}")

            logger.debug("\n  NOTE: _dedupe_disasters() dedupes by (type,country,city) and ignores eventid.")
            logger.debug("  That means dedupe can collapse records across different events.")
        else:
            logger.debug("  No per-event disaster records were produced (unexpected).")

        logger.debug(f"  RSS items: {geo_point_total}")
        logger.debug(f"  Missing geo:Point tag: {geo_point_missing_tag}")
        logger.debug(f"  Missing geo:lat/geo:long: {geo_point_missing_latlon}")
        logger.debug(f"  Non-numeric geo:lat/geo:long: {geo_point_non_numeric}")
        logger.debug(f"  Valid geo:Point coordinates: {geo_point_valid}")

        logger.debug("\n[RECON] Missing impact URL analysis:")
        logger.debug(f"  Events missing impact URL: {missing_impact_url_count}/{len(events)}")
        for k, v in sorted(missing_impact_url_reasons.items(), key=lambda x: (-x[1], x[0])):
            logger.debug(f"   - {k}: {v}")
        if missing_impact_url_events:
            logger.debug("  Missing-impact events:")
            for et, eid in missing_impact_url_events:
                logger.debug(f"   - {et} {eid}")

        # Data quality validation
        valid_impact_data = sum(1 for data in impact_data.values() if data.get('impact_json'))
        valid_coordinates = sum(1 for data in impact_data.values() if data.get('coordinates'))
        logger.debug(f"  Valid impact JSON: {valid_impact_data}/{len(impact_data)}")
        logger.debug(f"  Event coordinates: {valid_coordinates}/{len(impact_data)}")

        # Show disaster details for debugging
        # print("\n[RECON] Disaster Events Processed:")
        # for eventid, data in impact_data.items():
        #     coords = data.get('coordinates')
        #     event_type = data.get('eventtype', 'unknown')
        #     if coords and isinstance(coords, tuple) and len(coords) == 2:
        #         print(f"  {eventid}: {event_type} at ({coords[0]:.4f}, {coords[1]:.4f})")
        #     else:
        #         print(f"  {eventid}: {event_type} (invalid coordinates: {coords})")

        # print("\n[RECON] Alias Disasters:")
        # for disaster in disasters[:5]:  # Show first 5
        #     city = disaster.get('city', 'N/A')
        #     country = disaster.get('country', 'N/A')
        #     event_type = disaster.get('type', 'N/A')
        #     print(f"  {city}, {country} - {event_type}")
        # if len(disasters) > 5:
        #     print(f"  ... and {len(disasters) - 5} more")
    
    total = perf_counter() - t_recon_start
    logger.info("\n[RECON][TIMER] totals:")
    logger.info(f"  recon total: {total:.2f}s")
    logger.info(f"  eventdata total: {t_eventdata_total:.2f}s (ok={eventdata_ok})")
    logger.info(f"  impact total: {t_impact_total:.2f}s (ok={impact_ok})")
    logger.info(f"  slowest eventdata: {t_eventdata_max:.2f}s {slowest_eventdata}")
    logger.info(f"  slowest impact: {t_impact_max:.2f}s {slowest_impact}")

    return disasters, total_red, impact_data


def assets() -> tuple[dict[str, str], dict[str, str], dict[str, Optional[Tuple[float, float]]], dict[str, dict[str, str]]]:
    """
    A — ASSETS (DATA INPUT)
    Load company / contractor asset data (cities, countries, assets, etc.) from assets.csv
    and read pre-geocoded coordinates.
    The CSV is expected to have at least the columns:
      - unique_id  (anonymized unique ID, no PII)
      - city
      - country
      - type       (e.g. 'personnel', 'building', 'vehicle', ...)
      - latitude   (pre-geocoded coordinates)""" """  """ """
      - longitude  (pre-geocoded coordinates)
    Returns:
      cities:       mapping[str, str]           optional lookup of asset_id -> city name
      countries:    mapping[str, str]           optional lookup of asset_id -> country name
      coordinates:  mapping[str, Tuple[float, float]]  asset_id -> (latitude, longitude)
      assets_by_id: mapping[str, dict[str, str]]  core asset records used for
        impact matching. Each asset dict should at least contain
        ``city``, ``country``, and ``type``.
    """
    cities: dict[str, str] = {}
    countries: dict[str, str] = {}
    coordinates: dict[str, Optional[Tuple[float, float]]] = {}
    assets_by_id: dict[str, dict[str, str]] = {}
    csv_path = Path(__file__).resolve().parents[2] / "tests" / "data" / "assets.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"assets.csv not found at {csv_path}")
    logger.info("[ASSETS] Loading assets with pre-geocoded coordinates...")

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        loaded_count = 0
        coord_count = 0

        for raw_row in reader:
            row = {(k.strip() if isinstance(k, str) else k): v for k, v in raw_row.items() if k}
            asset_id = (row.get("unique_id") or "").strip()
            if not asset_id:
                continue
            loaded_count += 1

            # Read pre-geocoded coordinates
            lat_str = (row.get("latitude") or "").strip()
            lon_str = (row.get("longitude") or "").strip()

            if lat_str and lon_str:
                try:
                    lat = float(lat_str)
                    lon = float(lon_str)
                    coordinates[asset_id] = (lat, lon)
                    coord_count += 1
                except ValueError:
                    logger.warning(f"[ASSETS] ⚠ Invalid coordinates for {asset_id}: {lat_str}, {lon_str}")
                    coordinates[asset_id] = None
            else:
                coordinates[asset_id] = None
            assets_by_id[asset_id] = row
            cities[asset_id] = (row.get("city") or "").strip()
            countries[asset_id] = (row.get("country") or "").strip()
    logger.info(f"[ASSETS] Loaded {loaded_count} assets with {coord_count} having valid coordinates")

    return cities, countries, coordinates, assets_by_id


def intel(
    disasters: list[dict[str, str]],
    cities: dict[str, str],
    countries: dict[str, str],
    coordinates: dict[str, Optional[Tuple[float, float]]],
    assets_by_id: dict[str, dict[str, str]],
    impact_data: dict = None
) -> tuple[list[dict[str, str]], list[list[str]]]:
    """
    I — INTEL (DATA PROCESSING)

    ASSET-Centric Analysis.
    Hierarchical cross-reference: Polygon → Alias → Coordinate.
    Priority: Polygon (100% accuracy) → Alias (70% accuracy) → Coordinate (25% accuracy)

    Args:
        impact_data: dict mapping eventid → {impact_json, eventtype, coordinates}
    """
    matches: list[dict[str, str]] = []
    outreach_list: list[dict[str, str]] = []

    for asset_id, asset in assets_by_id.items():
        asset_coords = coordinates.get(asset_id)
        asset_city = (cities.get(asset_id) or "").strip().casefold()
        asset_country = (countries.get(asset_id) or "").strip().casefold()

        has_coords = (
            isinstance(asset_coords, (tuple, list))
            and len(asset_coords) == 2
            and isinstance(asset_coords[0], (int, float))
            and isinstance(asset_coords[1], (int, float))
        )

        asset_impacted = False
        impact_method = None
        impacting_event = None
        impact_location = None

        # METHOD 1: Polygon Analysis (Primary Method) - Check ALL events
        if impact_data and has_coords and not asset_impacted:
            polygon_result = _polygon_analysis(asset_coords, impact_data)
            if polygon_result['impacted']:
                impact_method = "POLYGON"
                asset_impacted = True
                impacting_event = polygon_result['event_id']

        # METHOD 2: Alias Analysis (Secondary Method)
        if not asset_impacted:
            alias_result = _alias_analysis(asset_city, asset_country, disasters)
            if alias_result['impacted']:
                impact_method = "ALIAS"
                asset_impacted = True
                impacting_event = alias_result['event_id']

        # METHOD 3: Coordinate Analysis (Tertiary Method) - Check ALL events
        nearest_disaster_coords = []
        if not asset_impacted and has_coords:
            coord_result = _coordinate_analysis(asset_coords, impact_data, top_n=5)
            nearest_disaster_coords = coord_result.get("nearest", []) if isinstance(coord_result, dict) else []
            # Nearest candidates are attached for downstream matching rules / review.

        # Add impacted asset to results
        if asset_impacted:
            # Get event type from the impacting event
            event_type = "unknown"
            if impact_method == "ALIAS":
                # Find matching disaster to get event type
                for d in disasters:
                    if d.get("eventid") == impacting_event:
                        event_type = d.get("type", "unknown")
                        break
            elif impact_method != "ALIAS" and impacting_event in impact_data:
                event_type = impact_data[impacting_event]["eventtype"]

            match_record = {
                "unique_id": asset_id,
                "city": cities.get(asset_id, ""),
                "country": countries.get(asset_id, ""),
                "event_type": event_type,
                "event_id": impacting_event,
                "impact_method": impact_method,
                "coordinates": f"{asset_coords[0]:.4f}, {asset_coords[1]:.4f}"
            }

            # Add disaster location context for alias/polygon methods
            if impact_method == "ALIAS" and alias_result:
                match_record["disaster_city"] = alias_result.get('disaster_city', "Unknown")
                match_record["disaster_country"] = alias_result.get('disaster_country', "Unknown")
            elif impact_method == "POLYGON" and impacting_event in impact_data:
                match_record["disaster_city"] = "Polygon Boundary"
                match_record["disaster_country"] = "Unknown"

            matches.append(match_record)
            outreach_list.append(asset)
        else:
            # Not impacted by polygon/alias. Attach proximity candidates for later decision rules.
            if nearest_disaster_coords:
                asset["nearest_disaster_coords"] = nearest_disaster_coords

    return matches, outreach_list


def disseminate(
    matches: list[dict[str, str]],
    outreach_list: list[list[str]],
    total_red: int,
    assets_by_id: dict[str, dict[str, str]],
    impact_data: dict[str, dict],
    debug: bool = False,
) -> None:
    """
    D — DISSEMINATE (OUTPUT)

    - Print human-readable details about impacted assets,
    - With hierarchical coverage analysis.
    - Write the affected CSV file.
    - Launch the static dashboard UI (disabled in debug mode).
    """

    # if debug:
    #     _print_coverage_analysis(matches, assets_by_id, impact_data)

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

    RAID-style flow with hierarchical analysis:
      R — recon()        : collect disaster intel + impact data
      A — assets()       : load company assets with coordinates
      I — intel()        : hierarchical impact assessment (Polygon → Alias → Coordinate)
      D — disseminate()  : output / deliver intel product

      Timed operations:
        assets() load
        recon() collect
        intel() analyze
        disseminate() output
    """

    setup_logging(debug=debug)
    logger.info("=" * 80)
    logger.info("DISASTER FACTOR - HIERARCHICAL IMPACT ANALYSIS")
    logger.info("=" * 80)

    # Load enhanced assets with coordinates
    with _timer("assets() load", enabled=True):
        cities, countries, coordinates, assets_by_id = assets()

    # Collect disaster intel with impact data for hierarchical analysis
    with _timer("recon() collect", enabled=True):
        disasters, total_red, impact_data = recon(debug)

    # Hierarchical impact assessment: Polygon → Alias → Coordinate
    with _timer("intel() analyze", enabled=True):
        matches, outreach_list = intel(disasters, cities, countries, coordinates, assets_by_id, impact_data)

    # Output results
    with _timer("disseminate() output", enabled=True):
        disseminate(matches, outreach_list, total_red, assets_by_id, impact_data, debug)
