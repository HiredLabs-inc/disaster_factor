"""Shared pytest fixtures for disaster_factor tests."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# RSS / GDACS fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def gdacs_rss_xml() -> bytes:
    """Raw bytes of the sample GDACS RSS feed."""
    return (DATA_DIR / "gdacs_rss_sample.xml").read_bytes()


@pytest.fixture(scope="session")
def gdacs_soup(gdacs_rss_xml: bytes) -> BeautifulSoup:
    """Parsed BeautifulSoup of the sample GDACS RSS feed."""
    return BeautifulSoup(gdacs_rss_xml, features="xml")


@pytest.fixture(scope="session")
def gdacs_items(gdacs_soup: BeautifulSoup):
    """All <item> elements from the sample RSS feed."""
    return gdacs_soup.find_all("item")


# ---------------------------------------------------------------------------
# Sample event dicts (no network required)
# ---------------------------------------------------------------------------

@pytest.fixture
def red_eq_event() -> dict[str, Any]:
    """A red-alert earthquake event near Afghanistan (from sample XML)."""
    return {
        "eventid": "1508467",
        "eventtype": "EQ",
        "alertlevel": "Red",
        "lat": 36.5894,
        "lon": 67.4843,
        "eventdata_url": (
            "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
            "?eventtype=EQ&eventid=1508467"
        ),
        "latitude": "36.5894",
        "longitude": "67.4843",
    }


@pytest.fixture
def orange_fl_event() -> dict[str, Any]:
    """An orange-alert flood event near Cuba (from sample XML)."""
    return {
        "eventid": "1103585",
        "eventtype": "FL",
        "alertlevel": "Orange",
        "lat": 20.3700559,
        "lon": -76.4272225,
        "eventdata_url": (
            "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
            "?eventtype=FL&eventid=1103585"
        ),
        "latitude": "20.3700559",
        "longitude": "-76.4272225",
    }


@pytest.fixture
def green_eq_event() -> dict[str, Any]:
    """A green-alert earthquake event near Chile (from sample XML)."""
    return {
        "eventid": "1508599",
        "eventtype": "EQ",
        "alertlevel": "Green",
        "lat": -27.4457,
        "lon": -71.4784,
        "eventdata_url": (
            "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
            "?eventtype=EQ&eventid=1508599"
        ),
        "latitude": "-27.4457",
        "longitude": "-71.4784",
    }


@pytest.fixture
def no_coords_event() -> dict[str, Any]:
    """An event with no valid coordinates."""
    return {
        "eventid": "9999999",
        "eventtype": "EQ",
        "alertlevel": "Red",
        "lat": None,
        "lon": None,
        "eventdata_url": "",
        "latitude": None,
        "longitude": None,
    }


@pytest.fixture
def sample_events(red_eq_event, orange_fl_event, green_eq_event, no_coords_event):
    """A mixed list of events covering all severity levels and a no-coords case."""
    return [red_eq_event, orange_fl_event, green_eq_event, no_coords_event]


# ---------------------------------------------------------------------------
# Sample asset dicts
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_assets() -> dict:
    """
    Returns (cities, countries, coordinates, assets_by_id) for a small set of
    test assets.

    - AST_NEAR_AFG: close to the red EQ event (Afghanistan area)
    - AST_NEAR_CUBA: close to the orange FL event (Cuba area)
    - AST_FAR: far from all events
    - AST_NO_COORD: asset with no coordinates
    """
    cities = {
        "AST_NEAR_AFG": "Kabul",
        "AST_NEAR_CUBA": "Havana",
        "AST_FAR": "Wellington",
        "AST_NO_COORD": "Unknown City",
    }
    countries = {
        "AST_NEAR_AFG": "Afghanistan",
        "AST_NEAR_CUBA": "Cuba",
        "AST_FAR": "New Zealand",
        "AST_NO_COORD": "Unknown",
    }
    # AST_NEAR_AFG is ~50 miles from the red EQ (36.5894, 67.4843)
    # AST_NEAR_CUBA is ~30 miles from the orange FL (20.37, -76.43)
    # AST_FAR is in New Zealand, far from everything
    coordinates = {
        "AST_NEAR_AFG": (36.9, 67.7),
        "AST_NEAR_CUBA": (20.0, -76.0),
        "AST_FAR": (-41.3, 174.8),
        "AST_NO_COORD": None,
    }
    assets_by_id = {
        "AST_NEAR_AFG": {"unique_id": "AST_NEAR_AFG", "city": "Kabul", "country": "Afghanistan", "type": "personnel"},
        "AST_NEAR_CUBA": {"unique_id": "AST_NEAR_CUBA", "city": "Havana", "country": "Cuba", "type": "building"},
        "AST_FAR": {"unique_id": "AST_FAR", "city": "Wellington", "country": "New Zealand", "type": "vehicle"},
        "AST_NO_COORD": {"unique_id": "AST_NO_COORD", "city": "Unknown City", "country": "Unknown", "type": "personnel"},
    }
    return cities, countries, coordinates, assets_by_id
