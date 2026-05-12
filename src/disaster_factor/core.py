# src/disaster_factor/core.py

# IMPORTS
from __future__ import annotations
import csv
import logging
import math
import os
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any, Optional, Tuple
import requests
from bs4 import BeautifulSoup
from .helpers import serve_static_and_open
from .geocode_assets import geocode_assets

LOG_FILE = Path(__file__).resolve().parents[2] / "disaster_factor.log"

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


# ------------------------------------------------------------------------------------
# GDACS helpers
# ------------------------------------------------------------------------------------

def _find_text_suffix(tag, suffix: str) -> str:
    """Find first sub-tag whose name ends with suffix (case-insensitive) and return stripped text."""

    t = tag.find(lambda x: getattr(x, "name", None) and x.name.lower().endswith(suffix))
    return (t.text or "").strip() if t and t.text else ""

def _extract_rss_geo_point(item) -> tuple[Optional[float], Optional[float], str]:
    """
    Extract numeric coordinates from RSS geo:Point.
 
    Returns:
      (lat, lon, reason)
      reason: "ok" | "missing_tag" | "missing_latlon" | "non_numeric"
    """
    geo_point = item.find("geo:Point")
    if not geo_point:
        return None, None, "missing_tag"
 
    lat_elem = geo_point.find("geo:lat")
    lon_elem = geo_point.find("geo:long")
 
    lat_text = (lat_elem.text or "").strip() if lat_elem else ""
    lon_text = (lon_elem.text or "").strip() if lon_elem else ""
 
    if not lat_text or not lon_text:
        return None, None, "missing_latlon"
 
    try:
        return float(lat_text), float(lon_text), "ok"
    except ValueError:
        return None, None, "non_numeric"
 
 
def _build_rss_event_summary(item) -> Optional[dict[str, Any]]:
    """
    Build normalized RSS event summary.
 
    Returns None when eventtype or eventid are missing.
    Fields: eventid, eventtype, alertlevel, lat, lon, eventdata_url,
            latitude, longitude (legacy string keys).
    """
    eventtype = _find_text_suffix(item, "eventtype")
    eventid = _find_text_suffix(item, "eventid")
    if not eventtype or not eventid:
        return None
 
    alertlevel = _find_text_suffix(item, "alertlevel")
    lat, lon, _ = _extract_rss_geo_point(item)
 
    return {
        "eventid": eventid,
        "eventtype": eventtype,
        "alertlevel": alertlevel,
        "lat": lat,
        "lon": lon,
        "eventdata_url": (
            "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
            f"?eventtype={eventtype}&eventid={eventid}"
        ),
        "latitude": str(lat) if lat is not None else None,
        "longitude": str(lon) if lon is not None else None,
    }


_ALERT_PRIORITY: tuple[str, ...] = ("red", "orange", "green")


def _normalize_alertlevel(value: Any) -> Optional[str]:
    """Normalize GDACS alert level to one of {red, orange, green}."""
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _ALERT_PRIORITY else None


# ------------------------------------------------------------------------------------
# Euclidean impact decision helpers
# ------------------------------------------------------------------------------------
 
# Distance thresholds by disaster type (miles). Placeholder values — tune after refactor.
_THRESHOLD_MILES_BY_TYPE: dict[str, float] = {
    "EQ": 150.0,    # Earthquake
    "TC": 200.0,    # Tropical Cyclone
    "FL":  75.0,    # Flood
    "VO": 100.0,    # Volcano
#   "DR": 150.0,    # Drought
    "WF":  75.0,    # Wildfire
    "TS": 250.0,    # Tsunami
}
_THRESHOLD_MILES_DEFAULT = min(_THRESHOLD_MILES_BY_TYPE.values())
 
 
def _distance_threshold_miles(eventtype: str) -> float:
    """Return distance threshold (miles) for a disaster type. Placeholder values."""
    return _THRESHOLD_MILES_BY_TYPE.get(eventtype.strip().upper(), _THRESHOLD_MILES_DEFAULT)
 
 
_MILES_PER_DEGREE = 69.0  # approximate miles per degree of lat/lon
 
def _euclidean_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight Euclidean distance in miles between two lat/lon points. No curvature correction."""
    dlat = (lat2 - lat1) * _MILES_PER_DEGREE
    dlon = (lon2 - lon1) * _MILES_PER_DEGREE
    return math.sqrt(dlat * dlat + dlon * dlon)
 
 
def _is_asset_affected(
    asset_coord: tuple[float, float],
    event: dict[str, Any],
) -> bool:
    """
    Decide whether an asset is affected by an event.
 
    Returns False for events without valid coordinates.
    Uses straight Euclidean distance vs. disaster-type threshold.
    """
    lat = event.get("lat")
    lon = event.get("lon")
    if lat is None or lon is None:
        return False

    try:
        event_lat = float(lat)
        event_lon = float(lon)
    except (TypeError, ValueError):
        logger.debug(
            "[INTEL] Skipping event with non-numeric coordinates: event_id=%s lat=%r lon=%r",
            event.get("eventid", "unknown"),
            lat,
            lon,
        )
        return False
 
    distance = _euclidean_distance(
        asset_coord[0], asset_coord[1],
        event_lat, event_lon,
    )
    return distance <= _distance_threshold_miles(event.get("eventtype", ""))



# ------------------------------------------------------------------------------------
# RAID pipeline
# ------------------------------------------------------------------------------------

def recon(debug: bool = False) -> tuple[int, list[dict[str, Any]]]:
    """
    R — RECON (DATA RETRIEVAL)
 
    Fetch GDACS RSS feed and extract normalized event summaries with geo:Point coordinates.
 
    Returns:
      (total_red, events)
 
    total_red: count of RSS items with alertlevel == "Red"
    events: list[dict] with keys {eventid, eventtype, alertlevel, lat, lon}
    """
 
    rss_url = "https://www.gdacs.org/XML/RSS.xml"
 
    resp = requests.get(rss_url, timeout=20)
    resp.raise_for_status()
 
    soup = BeautifulSoup(resp.content, features="xml")
    items = soup.find_all("item")
 
    t_recon_start = perf_counter()
 
    # geo:Point audit
    geo_point_total = 0
    geo_point_missing_tag = 0
    geo_point_missing_latlon = 0
    geo_point_non_numeric = 0
    geo_point_valid = 0
 
    events: list[dict[str, Any]] = []
    total_red = 0
    total_orange = 0
    total_green = 0
 
    for item in items:
        geo_point_total += 1
 
        lat, lon, geo_reason = _extract_rss_geo_point(item)
        if geo_reason == "missing_tag":
            geo_point_missing_tag += 1
        elif geo_reason == "missing_latlon":
            geo_point_missing_latlon += 1
        elif geo_reason == "non_numeric":
            geo_point_non_numeric += 1
        elif geo_reason == "ok":
            geo_point_valid += 1
 
        alert = _normalize_alertlevel(_find_text_suffix(item, "alertlevel"))
        if alert == "red":
            total_red += 1
        elif alert == "orange":
            total_orange += 1
        elif alert == "green":
            total_green += 1
 
        event = _build_rss_event_summary(item)
        if not event:
            continue
 
        events.append(event)

    for event in events:
        if _normalize_alertlevel(event.get("alertlevel")) == "red":
            logger.info(
                "[RECON] RED ALERT: %s %s lat=%s lon=%s",
                event["eventtype"], event["eventid"],
                event["lat"], event["lon"],
            )
 
    # Dev cap (optional)
    cap_raw = os.getenv("GDACS_DEV_CAP", "").strip()
    if cap_raw.isdigit() and int(cap_raw) > 0:
        events = events[:int(cap_raw)]
 
    if debug:
        logger.debug("[RECON] RSS Collection Summary:")
        logger.debug(f"  RSS items: {geo_point_total}")
        logger.debug(f"  Events extracted: {len(events)}")
        logger.debug(f"  Red alert events: {total_red}")
        logger.debug(f"  Orange alert events: {total_orange}")
        logger.debug(f"  Green alert events: {total_green}")
        logger.debug(f"  Valid geo:Point coordinates: {geo_point_valid}")
        logger.debug(f"  Missing geo:Point tag: {geo_point_missing_tag}")
        logger.debug(f"  Missing geo:lat/geo:long: {geo_point_missing_latlon}")
        logger.debug(f"  Non-numeric geo:lat/geo:long: {geo_point_non_numeric}")
 
    total = perf_counter() - t_recon_start
    logger.info(f"[RECON][TIMER] recon total: {total:.2f}s")
 
    return total_red, events


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
    
    
    # TODO: Review for refactoring to using Python objects instead of files (see geocode_assets.py/geocode_assets_csv)
    logger.info("[ASSETS] Loading assets with pre-geocoded coordinates...")
    asset_rows = geocode_assets()
    loaded_count = 0
    coord_count = 0

    for asset_row in asset_rows:
        asset_id = (asset_row.get("unique_id") or "").strip()
        if not asset_id:
            continue
        loaded_count += 1
    
        lat = asset_row.get("latitude")
        lon = asset_row.get("longitude")

        if lat and lon:
            try:
                coordinates[asset_id] = (float(lat), float(lon))
                coord_count += 1
            except (ValueError, TypeError):
                logger.warning(f"[ASSETS] Invalid coordinates for {asset_id}: {lat}, {lon}")
                coordinates[asset_id] = None
        else:
            coordinates[asset_id] = None
        assets_by_id[asset_id] = asset_row
        cities[asset_id] = (asset_row.get("city") or "").strip()
        countries[asset_id] = (asset_row.get("country") or "").strip()
    logger.info(f"[ASSETS] Loaded {loaded_count} assets with {coord_count} having valid coordinates")

    return cities, countries, coordinates, assets_by_id

def intel(
    events: list[dict[str, Any]],
    coordinates: dict[str, Optional[Tuple[float, float]]],
    cities: dict[str, str],
    countries: dict[str, str],
    assets_by_id: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, Any]]]:
    """
    I — INTEL (Euclidean path)
 
    One-pass: for each asset with valid coordinates, check events in priority
    order red -> orange -> green, and stop on the first matched tier using
    straight Euclidean distance and disaster-type thresholds.
 
    Returns:
      (red_matches, prelim_matches, red_points)
    """
    red_matches: list[dict[str, str]] = []
    prelim_matches: list[dict[str, str]] = []
    red_points: list[dict[str, Any]] = []

    events_by_severity: dict[str, list[dict[str, Any]]] = {sev: [] for sev in _ALERT_PRIORITY}
    for event in events:
        severity = _normalize_alertlevel(event.get("alertlevel"))
        if severity is None:
            continue
        events_by_severity[severity].append(event)

    for asset_id in assets_by_id:
        asset_coords = coordinates.get(asset_id)
        if not (
            isinstance(asset_coords, (tuple, list))
            and len(asset_coords) == 2
            and isinstance(asset_coords[0], (int, float))
            and isinstance(asset_coords[1], (int, float))
        ):
            continue
 
        matched_event: Optional[dict[str, Any]] = None
        matched_severity: Optional[str] = None
        for severity in _ALERT_PRIORITY:
            for event in events_by_severity[severity]:
                if _is_asset_affected(asset_coords, event):
                    matched_event = event
                    matched_severity = severity
                    break
            if matched_event is not None:
                break

        if matched_event is None or matched_severity is None:
            continue

        base_match = {
            "unique_id": asset_id,
            "city": cities.get(asset_id, ""),
            "country": countries.get(asset_id, ""),
            "event_type": matched_event.get("eventtype", "unknown"),
            "event_id": matched_event.get("eventid", "unknown"),
            "impact_method": "EUCLIDEAN",
            "coordinates": f"{asset_coords[0]:.4f}, {asset_coords[1]:.4f}",
        }
        prelim_matches.append({
            **base_match,
            "severity": matched_severity,
        })
        if matched_severity == "red":
            red_matches.append(base_match)
            label = ", ".join(
                p for p in (cities.get(asset_id, "").strip(), countries.get(asset_id, "").strip()) if p
            ) or asset_id
            red_points.append({
                "lat": float(asset_coords[0]),
                "lon": float(asset_coords[1]),
                "label": label,
                "severity": "red",
            })
 
    return red_matches, prelim_matches, red_points


def disseminate(
    red_matches: list[dict[str, str]],
    prelim_matches: list[dict[str, str]],
    red_points: list[dict[str, Any]],
    total_red: int,
    debug: bool = False,
    **kwargs,
) -> None:
    """
    D — DISSEMINATE (OUTPUT)
 
    - Capture output in Python object .
    - Launch the static dashboard UI (disabled in debug mode).
    """
    from .writers import CsvWriter

    output_dir = kwargs.get("output_dir", Path(__file__).resolve().parents[2] / "tests" / "data")
    writer = kwargs.get("writer", CsvWriter())

    writer.write_affected(red_matches, output_dir)
    writer.write_prelim(prelim_matches, output_dir)
    writer.write_points(red_points, output_dir)

    logger.info(
        "[DISSEMINATE] affected=%d rows, prelim=%d rows, points=%d (total_red=%d)",
        len(red_matches),
        len(prelim_matches),
        len(red_points),
        total_red,
    )

    # Serve dashboard static
    if not debug:
        serve_static_and_open()


def track_disasters(debug: bool = False, **kwargs) -> None:
    """
    Orchestrator for the full disaster tracking pipeline.

    RAID-style flow:
      R — recon()             : collect RSS events with geo coordinates
      A — assets()            : load company assets with coordinates
      I — intel()             : priority classification (red/orange/green)
      D — disseminate()       : write output via writer + launch dashboard

      Timed operations:
        assets() load
        recon() collect
        intel() analyze
        disseminate() output
    """

    setup_logging(debug=debug)
    logger.info("=" * 80)
    logger.info("DISASTER FACTOR - EUCLIDEAN IMPACT ANALYSIS")
    logger.info("=" * 80)

    # Load enhanced assets with coordinates
    with _timer("assets() load", enabled=True):
        cities, countries, coordinates, assets_by_id = assets()

    # Collect disaster intel from RSS
    with _timer("recon() collect", enabled=True):
        total_red, events = recon(debug)
    
    # Euclidean impact assessment with severity priority
    with _timer("intel() analyze", enabled=True):
        red_matches, prelim_matches, red_points = intel(
            events, coordinates, cities, countries, assets_by_id
        )
 
    # Output results
    with _timer("disseminate() output", enabled=True):
        disseminate(red_matches, prelim_matches, red_points, total_red, debug, **kwargs)