# src/disaster_factor/core.py

# IMPORTS
from __future__ import annotations
from bs4 import BeautifulSoup
from pathlib import Path
import requests
import csv
import json
import math
import time
import os
from typing import Any
from .helpers import serve_static_and_open
from typing import Optional, Tuple



# ------------------------------------------------------------------------------------
# GENERAL utilities
# ------------------------------------------------------------------------------------

def _get_geocoding_api_key() -> str:
    """
    Get Google Geocoding API key from environment or user input.
    
    Returns:
        str: Valid Google Geocoding API key
        
    Raises:
        ValueError: If no API key is available
    """
    api_key = os.getenv("GOOGLE_GEOCODING_API_KEY")
    if not api_key:
        print("[GEOCODE] Google Geocoding API key not found in environment")
        api_key = input("Enter your Google Geocoding API key: ").strip()
        if not api_key:
            raise ValueError("Google Geocoding API key is required")
        os.environ["GOOGLE_GEOCODING_API_KEY"] = api_key
        print("[GEOCODE] API key saved to environment for this session")
    return api_key


# ------------------------------------------------------------------------------------
# GDACS helpers
# ------------------------------------------------------------------------------------

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


def _print_coverage_analysis(matches, assets_by_id, impact_data):
    """Print detailed hierarchical coverage analysis."""
    
    # Method matching results
    polygon_matches = [m for m in matches if m['impact_method'] == 'POLYGON']
    alias_matches = [m for m in matches if m['impact_method'] == 'ALIAS']
    coordinate_matches = [m for m in matches if m['impact_method'] == 'COORDINATE']
    
    # Coverage calculations
    total_assets = len(assets_by_id)
    total_impacted = len(matches)

    # Print comprehensive analysis
    print("\n" + "="*60)
    print("HIERARCHICAL COVERAGE ANALYSIS")
    print("="*60)
    
    # Method matching results
    print("\n[INTEL] Method Matching Results:")
    print(f"  Polygon method matched: {len(polygon_matches)} assets")
    print(f"  Alias method matched: {len(alias_matches)} assets")
    print(f"  Coordinate method matched: {len(coordinate_matches)} assets")
    print(f"  Total assets impacted: {total_impacted}/{total_assets} ({total_impacted/total_assets*100:.1f}%)")
    
    # Coverage analysis
    print("\n[INTEL] Method Coverage Analysis:")
    print(f"  Polygon coverage: {len(polygon_matches)}/{total_assets} assets ({len(polygon_matches)/total_assets*100:.1f}%)")
    print(f"  Alias coverage: {len(alias_matches)}/{total_assets} assets ({len(alias_matches)/total_assets*100:.1f}%)")
    print(f"  Coordinate coverage: {len(coordinate_matches)}/{total_assets} assets ({len(coordinate_matches)/total_assets*100:.1f}%)")

    # Method effectiveness
    print(f"\n[INTEL] Method Effectiveness:")
    print(f"  1st: Polygon method ({len(polygon_matches)} matches)")
    print(f"  2nd: Alias method ({len(alias_matches)} matches)")
    print(f"  3rd: Coordinate method ({len(coordinate_matches)} matches)")



# ------------------------------------------------------------------------------------
# POLYGON helpers
# ------------------------------------------------------------------------------------

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


# def _calculate_polygon_impact_score(asset: dict, polygons: List[List[Tuple[float, float]]]) -> float:
#     """Calculate impact score based on polygon analysis."""
#     # For polygon analysis, assets inside polygon get high score
#     # Could be enhanced based on distance to polygon center
#     return base_score


def _extract_polygons_from_impact(impact_json: dict) -> List[List[Tuple[float, float]]]:
    """Extract polygons from impact JSON for analysis."""
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


def _asset_in_polygons(asset_coords: Tuple[float, float], polygons: List[List[Tuple[float, float]]]) -> bool:
    """Check if asset coordinates are within any disaster polygons."""
    if not asset_coords or not polygons:
        return False
    
    for polygon in polygons:
        if _point_in_polygon(asset_coords[0], asset_coords[1], polygon):
            return True
    
    return False


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
    Step-4 impact JSON -> disasters list.
    """
    # Priority aliases
    priority = ["city", "urbanareas", "ports", "airport", "aru"]
    
    datums = impact_json.get("datums")
    if not isinstance(datums, list):
        return []
    
    # Find first priority alias in one pass
    chosen_alias = None
    chosen_block = None
    
    for block in datums:
        if isinstance(block, dict):
            alias = block.get("alias")
            if isinstance(alias, str):
                alias_clean = alias.strip().casefold()
                if alias_clean in priority:
                    chosen_alias = alias_clean
                    chosen_block = block
                    break
    
    if not chosen_block:
        return []
    
    disasters: list[dict[str, str]] = []
    
    # Process the chosen block directly (no loop needed)
    records = chosen_block.get("datum")
    if not isinstance(records, list) or not records:
        return disasters
        
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
        # Extract city name for priority aliases
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
        })

    return out



# ------------------------------------------------------------------------------------
# COORDINATE helpers
# ------------------------------------------------------------------------------------

def _extract_disaster_coordinates(impact_json: dict) -> List[Dict]:
        """Extract all disaster coordinates from impact data."""
        coords = []
        
        datums = impact_json.get("datums", [])
        for block in datums:
            if isinstance(block, dict):
                alias = block.get("alias", "").strip().casefold()
                records = block.get("datum", [])
                
                if isinstance(records, list):
                    for record in records:
                        if isinstance(record, dict):
                            coord = _extract_single_coordinate(record)
                            if coord:
                                coords.append(coord)
        
        return coords


def _extract_single_coordinate(record: dict) -> Optional[Dict]:
        """Extract single coordinate from record."""
        scalars_dict = _scalars_to_dict(record)
        
        lat = lon = None

        # Search through all scalar fields for lat/long
        for name, value in scalars_dict.items():
            if not value or not value.replace('.', '').replace('-', '').isdigit():
                continue

            name_lower = name.lower()
            if 'lat' in name_lower:
                lat = float(value)
            elif 'long' in name_lower or 'lon' in name_lower:
                lon = float(value)
        
        if lat is not None and lon is not None:
            return {'latitude': lat, 'longitude': lon}
        return None


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in kilometers."""
    R = 6371  # Earth's radius in kilometers
    
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 + 
            math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    c = 2 * math.asin(math.sqrt(a))
    
    return R * c


def _coordinate_analysis(impact_json: dict, eventtype: str, eventid: str) -> Dict:
        """Method 2: Coordinate-based proximity analysis."""
        try:
            # Extract disaster coordinates
            disaster_coords = _extract_disaster_coordinates(impact_json)
            if not disaster_coords:
                return {'success': False, 'reason': 'No coordinates found'}
            
            # Analyze asset impact using proximity
            impacted_assets = []
            for asset in assets:
                min_distance = float('inf')
                
                for coord in disaster_coords:
                    distance = _haversine_distance(
                        asset['latitude'], asset['longitude'],
                        coord['latitude'], coord['longitude']
                    )
                    min_distance = min(min_distance, distance)
                
                # Determine impact based on distance thresholds
                if min_distance <= 100:  # 100km radius
                    impact_level = 'HIGH' if min_distance <= 50 else 'MEDIUM'
                    impact_score = max(0, 100 - min_distance)
                    
                    impacted_assets.append({
                        'asset_name': asset['name'],
                        'impact_level': impact_level,
                        'impact_score': impact_score,
                        'distance_km': min_distance,
                        'method': 'COORDINATE_PROXIMITY'
                    })
            
            return {
                'success': True,
                'coordinates_found': len(disaster_coords),
                'impacted_assets': impacted_assets
            }
            
        except Exception as e:
            return {'success': False, 'reason': str(e)}



            
# ------------------------------------------------------------------------------------
# RAID pipeline
# ------------------------------------------------------------------------------------

def recon(debug: bool = False) -> tuple[list[dict[str, str]], int, dict[str, dict]]:
    """
    R — RECON (DATA RETRIEVAL)

    GDACS JSON pipeline with hierarchical data collection:
      RSS -> (eventtype,eventid,alertlevel) -> construct eventdata URL
      eventdata JSON -> impact export URL
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

    # Build events directly from eventtype/eventid; count total_red from alertlevel.
    events: list[dict[str, str]] = []
    total_red = 0
    
    # Store impact data for hierarchical analysis
    impact_data: dict[str, dict] = {}
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

        # Parse disasters from impact JSON (alias data)
        disasters.extend(_parse_impact_json_to_disasters(impact_json, eventtype, eventid, ev.get("latitude"), ev.get("longitude")))
        
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

    disasters = _dedupe_disasters(disasters)

    if debug:
        print("[RECON] Hierarchical Collection Summary:")
        print(f"  Impact events collected: {len(impact_data)}")
        print(f"  Alias disasters extracted: {len(disasters)}")
        print(f"  Red alert events: {total_red}")
        
        # Data quality validation
        valid_impact_data = sum(1 for data in impact_data.values() if data.get('impact_json'))
        valid_coordinates = sum(1 for data in impact_data.values() if data.get('coordinates'))
        print(f"  Valid impact JSON: {valid_impact_data}/{len(impact_data)}")
        print(f"  Event coordinates: {valid_coordinates}/{len(impact_data)}")
        
        # Show disaster details for debugging
        print("\n[RECON] Disaster Events Processed:")
        for eventid, data in impact_data.items():
            coords = data.get('coordinates')
            event_type = data.get('eventtype', 'unknown')
            if coords and isinstance(coords, tuple) and len(coords) == 2:
                print(f"  {eventid}: {event_type} at ({coords[0]:.3f}, {coords[1]:.3f})")
            else:
                print(f"  {eventid}: {event_type} (invalid coordinates: {coords})")
        
        print("\n[RECON] Alias Disasters:")
        for disaster in disasters[:5]:  # Show first 5
            city = disaster.get('city', 'N/A')
            country = disaster.get('country', 'N/A')
            event_type = disaster.get('type', 'N/A')
            print(f"  {city}, {country} - {event_type}")
        if len(disasters) > 5:
            print(f"  ... and {len(disasters) - 5} more")

    return disasters, total_red, impact_data


def assets() -> tuple[dict[str, str], dict[str, str], dict[str, Tuple[float, float]], dict[str, dict[str, str]]]:
    """
    A — ASSETS (DATA INPUT)
    Load company / contractor asset data (cities, countries, assets, etc.) from assets.csv
    and read pre-geocoded coordinates.
    The CSV is expected to have at least the columns:
      - unique_id  (anonymized unique ID, no PII)
      - city
      - country
      - type       (e.g. 'personnel', 'building', 'vehicle', ...)
      - latitude   (pre-geocoded coordinates)
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
    coordinates: dict[str, Tuple[float, float]] = {}
    assets_by_id: dict[str, dict[str, str]] = {}
    csv_path = Path(__file__).resolve().parents[2] / "tests" / "data" / "assets.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"assets.csv not found at {csv_path}")
    print("[ASSETS] Loading assets with pre-geocoded coordinates...")
    
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        loaded_count = 0
        coord_count = 0
        
        for row in reader:
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
                    print(f"[ASSETS] ⚠ Invalid coordinates for {asset_id}: {lat_str}, {lon_str}")
                    coordinates[asset_id] = None
            else:
                coordinates[asset_id] = None
            assets_by_id[asset_id] = row
            cities[asset_id] = (row.get("city") or "").strip()
            countries[asset_id] = (row.get("country") or "").strip()
    print(f"[ASSETS] Loaded {loaded_count} assets with {coord_count} having valid coordinates")
    
    return cities, countries, coordinates, assets_by_id


def intel(
    disasters: list[dict[str, str]], 
    cities: dict[str, str], 
    countries: dict[str, str], 
    coordinates: dict[str, Tuple[float, float]], 
    assets_by_id: dict[str, dict[str, str]],
    impact_data: dict = None
) -> tuple[list[dict[str, str]], list[list[str]]]:
    """
    I — INTEL (DATA PROCESSING)
    
    ASSET-Centric Analysis.
    Hierarchical cross-reference: Polygon → Alias → Coordinate.
    Priority: Polygon (95% accuracy) → Alias (70% accuracy) → Coordinate (25% accuracy)
    
    Args:
        impact_data: dict mapping eventid → {impact_json, eventtype, coordinates}
    """
    matches: list[dict[str, str]] = []
    outreach_list: list[dict[str, str]] = []
    
    for asset_id, asset in assets_by_id.items():
        asset_coords = coordinates.get(asset_id)
        asset_city = (cities.get(asset_id) or "").strip().casefold()
        asset_country = (countries.get(asset_id) or "").strip().casefold()
        
        # Skip assets without coordinates for polygon/coordinate analysis
        if not asset_coords:
            continue
            
        asset_impacted = False
        impact_method = None
        impact_confidence = None
        impacting_event = None
        
        # METHOD 1: Polygon Analysis (Highest Priority) - Check ALL events
        if impact_data and not asset_impacted:
            for eventid, data in impact_data.items():
                polygons = _extract_polygons_from_impact(data['impact_json'])
                if polygons:
                    if _asset_in_polygons(asset_coords, polygons):
                        impact_method = "POLYGON"
                        impact_confidence = "HIGH"
                        asset_impacted = True
                        impacting_event = eventid
                        break
        
        # METHOD 2: Alias Analysis (Medium Priority)
        if not asset_impacted:
            for d in disasters:
                d_city = (d.get("city") or "").strip().casefold()
                d_country = (d.get("country") or "").strip().casefold()
                d_type = (d.get("type") or "").strip()
                
                if not d_country or asset_country != d_country:
                    continue
                
                # If disaster has a city/locality, require match; otherwise country-only match.
                if d_city and asset_city != d_city:
                    continue
                
                impact_method = "ALIAS"
                impact_confidence = "MEDIUM"
                asset_impacted = True
                impacting_event = d.get("eventid", "unknown")
                break
        
        # METHOD 3: Coordinate Analysis (Fallback) - Check ALL events
        if not asset_impacted and impact_data:
            for eventid, data in impact_data.items():
                disaster_coords = _extract_disaster_coordinates(data['impact_json'])
                if disaster_coords:
                    min_distance = float('inf')
                    for coord in disaster_coords:
                        distance = _haversine_distance(
                            asset_coords[0], asset_coords[1],
                            coord['latitude'], coord['longitude']
                        )
                        min_distance = min(min_distance, distance)
                    
                    if min_distance <= 500:  # 500km radius for broader coverage
                        impact_method = "COORDINATE"
                        impact_confidence = "LOW"
                        asset_impacted = True
                        impacting_event = eventid
                        break
        
        # Add impacted asset to results
        if asset_impacted:
            # Get event type from the impacting event
            event_type = "unknown"
            if impact_method == "ALIAS" and disasters:
                event_type = disasters[0].get("type", "unknown")
            elif impact_method != "ALIAS" and impacting_event in impact_data:
                event_type = impact_data[impacting_event]["eventtype"]
            
            match_record = {
                "unique_id": asset_id,
                "city": cities.get(asset_id, ""),
                "country": countries.get(asset_id, ""),
                "event_type": event_type,
                "event_id": impacting_event,
                "impact_method": impact_method,
                "confidence": impact_confidence,
                "coordinates": f"{asset_coords[0]:.4f}, {asset_coords[1]:.4f}"
            }
            matches.append(match_record)
            outreach_list.append(asset)

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

    if debug:
        _print_coverage_analysis(matches, assets_by_id, impact_data)
   
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
    """
    print("=" * 80)
    print("DISASTER FACTOR - HIERARCHICAL IMPACT ANALYSIS")
    print("=" * 80)

    # Load enhanced assets with coordinates
    cities, countries, coordinates, assets_by_id = assets()
    
    # Collect disaster intel with impact data for hierarchical analysis
    disasters, total_red, impact_data = recon(debug)
    
    # Hierarchical impact assessment: Polygon → Alias → Coordinate
    matches, outreach_list = intel(disasters, cities, countries, coordinates, assets_by_id, impact_data)
    
    # Output results
    disseminate(matches, outreach_list, total_red, assets_by_id, impact_data, debug)
