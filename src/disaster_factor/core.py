# src/disaster_factor/core.py
"""Disaster Factor core pipeline.

Implements the RAID pipeline for disaster tracking:
    R — recon()       : fetch and parse GDACS RSS events with geo coordinates.
    A — assets()      : load company asset data with geocoded coordinates.
    I — intel()       : classify assets by proximity and alert severity.
    D — disseminate() : capture output and launch the dashboard.

Entry point is ``track_disasters()``.
"""

# IMPORTS
from __future__ import annotations
import csv
import logging
import math
import os
from pathlib import Path
from typing import Any, Optional, Tuple
import requests
from bs4 import BeautifulSoup
from .helpers import serve_static_and_open
from .geocode_assets import geocode_assets

LOG_FILE = Path(__file__).resolve().parents[2] / "disaster_factor.log"

logger = logging.getLogger(__name__)

def setup_logging(*, debug: bool = False) -> None:
    """Configure root logger with terminal and file handlers.

    Clears existing handlers before applying new ones to prevent duplicate
    log entries if called more than once.

    Args:
        debug: If True, sets log level to DEBUG. Defaults to INFO.
    """
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
# GDACS helpers
# ------------------------------------------------------------------------------------

def _find_text_suffix(tag, suffix: str) -> str:
    """Find the first child tag whose name ends with a given suffix.

    The suffix comparison is case-insensitive.

    Args:
        tag: A BeautifulSoup tag to search within.
        suffix: The suffix to match against child tag names.

    Returns:
        Stripped text content of the matching tag, or an empty string if
        no matching tag is found.
    """
    t = tag.find(lambda x: getattr(x, "name", None) and x.name.lower().endswith(suffix))
    return (t.text or "").strip() if t and t.text else ""

def _extract_rss_geo_point(item) -> tuple[Optional[float], Optional[float], str]:
    """Extract numeric coordinates from an RSS ``geo:Point`` element.

    Args:
        item: A BeautifulSoup tag representing an RSS ``<item>`` element.

    Returns:
        A three-tuple ``(lat, lon, reason)`` where:
            - ``lat`` and ``lon`` are floats if extraction succeeded, else None.
            - ``reason`` is one of ``"ok"``, ``"missing_tag"``,
              ``"missing_latlon"``, or ``"non_numeric"``.
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
    """Build a normalised event summary dict from an RSS item.

    Returns None when ``eventtype`` or ``eventid`` are missing, as these
    are required for downstream processing.

    Args:
        item: A BeautifulSoup tag representing an RSS ``<item>`` element.

    Returns:
        A dict with keys ``eventid``, ``eventtype``, ``alertlevel``, ``lat``,
        ``lon``, ``eventdata_url``, ``latitude``, and ``longitude``, or None
        if required fields are absent.
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
    """Normalize a GDACS alert level value to a canonical lowercase string.

    Args:
        value: Raw alert level value from the RSS feed.

    Returns:
        One of ``"red"``, ``"orange"``, or ``"green"`` if the value matches,
        otherwise None.
    """
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
    """Return the distance threshold in miles for a given disaster type.

    Falls back to the minimum threshold across all known types if the
    event type is unrecognised.

    Args:
        eventtype: GDACS event type code (e.g. ``"EQ"``, ``"TC"``).

    Returns:
        Distance threshold in miles as a float.
    """
    return _THRESHOLD_MILES_BY_TYPE.get(eventtype.strip().upper(), _THRESHOLD_MILES_DEFAULT)
 
 
_MILES_PER_DEGREE = 69.0  # approximate miles per degree of lat/lon
 
def _euclidean_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate straight-line Euclidean distance in miles between two points.

    Uses a flat-earth approximation with a fixed miles-per-degree constant.
    No curvature correction is applied.

    Args:
        lat1: Latitude of the first point in degrees.
        lon1: Longitude of the first point in degrees.
        lat2: Latitude of the second point in degrees.
        lon2: Longitude of the second point in degrees.

    Returns:
        Approximate distance in miles as a float.
    """
    dlat = (lat2 - lat1) * _MILES_PER_DEGREE
    dlon = (lon2 - lon1) * _MILES_PER_DEGREE
    return math.sqrt(dlat * dlat + dlon * dlon)
 
 
def _is_asset_affected(
    asset_coord: tuple[float, float],
    event: dict[str, Any],
) -> bool:
    """Determine whether an asset falls within the impact radius of an event.

    Uses straight Euclidean distance compared against a disaster-type-specific
    threshold. Returns False immediately if the event has no valid coordinates.

    Args:
        asset_coord: A ``(latitude, longitude)`` tuple for the asset.
        event: A normalised event dict as returned by ``_build_rss_event_summary()``.

    Returns:
        True if the asset is within the threshold distance of the event,
        False otherwise.
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
    """Fetch and parse the GDACS RSS feed into normalised event summaries.

    Retrieves the live RSS feed, extracts geo coordinates and alert levels,
    and logs a breakdown of geo:Point availability. Applies an optional
    development cap via the ``GDACS_DEV_CAP`` environment variable.

    Args:
        debug: If True, logs a detailed summary of RSS collection statistics.

    Returns:
        A two-tuple ``(total_red, events)`` where:
            - ``total_red`` is the count of RSS items with alertlevel ``"red"``.
            - ``events`` is a list of normalised event dicts with keys
              ``eventid``, ``eventtype``, ``alertlevel``, ``lat``, and ``lon``.
    """
    rss_url = "https://www.gdacs.org/XML/RSS.xml"
 
    resp = requests.get(rss_url, timeout=20)
    resp.raise_for_status()
 
    soup = BeautifulSoup(resp.content, features="xml")
    items = soup.find_all("item")
 
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
 
    return total_red, events


def assets() -> tuple[dict[str, str], dict[str, str], dict[str, Optional[Tuple[float, float]]], dict[str, dict[str, str]]]:
    """Load and return company asset data with geocoded coordinates.

    Delegates to ``geocode_assets()`` and organises the results into four
    lookup dicts keyed by ``unique_id``. Assets without valid coordinates
    are included with a None coordinate value.

    Returns:
        A four-tuple ``(cities, countries, coordinates, assets_by_id)`` where:
            - ``cities``: mapping of asset_id to city name.
            - ``countries``: mapping of asset_id to country name.
            - ``coordinates``: mapping of asset_id to ``(latitude, longitude)``
              tuple, or None if coordinates are unavailable.
            - ``assets_by_id``: mapping of asset_id to the full asset row dict.
    """
    cities: dict[str, str] = {}
    countries: dict[str, str] = {}
    coordinates: dict[str, Optional[Tuple[float, float]]] = {}
    assets_by_id: dict[str, dict[str, str]] = {}
    
    logger.info("[ASSETS] Loading assets with pre-geocoded coordinates...")
    assets = geocode_assets()
    loaded_count = 0
    coord_count = 0

    for asset_row in assets:
        asset_id = (asset_row.get("unique_id") or "").strip()
        if not asset_id:
            continue
        loaded_count += 1
    
        lat = asset_row.get("latitude")
        lon = asset_row.get("longitude")

        if lat not in (None, "") and lon not in (None, ""):
            coordinates[asset_id] = (lat, lon)
            coord_count += 1
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
    """Classify assets by proximity to disaster events using Euclidean distance.

    Performs a single pass over all assets with valid coordinates. For each
    asset, events are checked in priority order (red, orange, green) and
    matching stops at the first hit. Assets with no coordinate data are
    skipped silently.

    Args:
        events: List of normalised event dicts from ``recon()``.
        coordinates: Mapping of asset_id to ``(latitude, longitude)`` or None.
        cities: Mapping of asset_id to city name.
        countries: Mapping of asset_id to country name.
        assets_by_id: Mapping of asset_id to full asset row dict.

    Returns:
        A three-tuple ``(red_matches, prelim_matches, red_points)`` where:
            - ``red_matches``: list of asset dicts matched at red alert level.
            - ``prelim_matches``: list of all matched asset dicts across all
              severity levels, each including a ``severity`` key.
            - ``red_points``: list of coordinate dicts for red-matched assets,
              suitable for rendering on the dashboard map.
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
) -> tuple[list[dict], int]:
    """Log pipeline output summary and return results.

    Logs a summary line with match counts and returns the pipeline results
    as a tuple for the caller to use or store.

    Args:
        red_matches: List of asset dicts matched at red alert level.
        prelim_matches: List of all matched asset dicts across all severities.
        red_points: List of coordinate dicts for red-matched assets.
        total_red: Total count of red alert events from the RSS feed.
        debug: Reserved for future use. Defaults to False.

    Returns:
        A four-tuple ``(red_matches, prelim_matches, red_points, total_red)``.
    """
    logger.info(
        "[DISSEMINATE] affected=%d rows, prelim=%d rows, points=%d (total_red=%d)",
        len(red_matches),
        len(prelim_matches),
        len(red_points),
        total_red,
    )

    return red_matches, prelim_matches, red_points, total_red

def track_disasters(debug: bool = False) -> None:
    """Run the full RAID disaster tracking pipeline.

    Orchestrates the four pipeline stages in order, sets up logging, and
    launches the static dashboard unless running in debug mode.

    Args:
        debug: If True, enables debug logging and skips launching the
            dashboard. Defaults to False.
    """
    setup_logging(debug=debug)
    logger.info("=" * 80)
    logger.info("DISASTER FACTOR - EUCLIDEAN IMPACT ANALYSIS")
    logger.info("=" * 80)

    # Load enhanced assets with coordinates
    cities, countries, coordinates, assets_by_id = assets()

    # Collect disaster intel from RSS
    total_red, events = recon(debug)
    
    # Euclidean impact assessment with severity priority
    red_matches, prelim_matches, red_points = intel(events, coordinates, cities, countries, assets_by_id)
 
    # Output results
    final_output = disseminate(red_matches, prelim_matches, red_points, total_red, debug)
    
    # Serve dashboard static
    if not debug:
        serve_static_and_open()
