"""Shared pytest fixtures for disaster_factor tests.

Provides reusable fixtures for RSS feed parsing, sample event dicts covering
all GDACS alert levels, and sample asset collections used across the test suite.
No network access is required; all data is sourced from files under tests/data/.
"""
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
    """Read the sample GDACS RSS feed from disk.

    Returns:
        Raw bytes of the sample RSS XML file.
    """
    return (DATA_DIR / "gdacs_rss_sample.xml").read_bytes()


@pytest.fixture(scope="session")
def gdacs_soup(gdacs_rss_xml: bytes) -> BeautifulSoup:
    """Parse the sample GDACS RSS feed into a BeautifulSoup object.

    Args:
        gdacs_rss_xml: Raw bytes of the sample RSS XML file.

    Returns:
        Parsed BeautifulSoup tree of the sample feed.
    """
    return BeautifulSoup(gdacs_rss_xml, features="xml")


@pytest.fixture(scope="session")
def gdacs_items(gdacs_soup: BeautifulSoup):
    """Extract all RSS item elements from the sample feed.

    Args:
        gdacs_soup: Parsed BeautifulSoup tree of the sample feed.

    Returns:
        A list of all ``<item>`` BeautifulSoup tags found in the feed.
    """
    return gdacs_soup.find_all("item")


# ---------------------------------------------------------------------------
# Sample event dicts (no network required)
# ---------------------------------------------------------------------------

@pytest.fixture
def red_eq_event() -> dict[str, Any]:
    """Return a red-alert earthquake event near Afghanistan.

    Coordinates are taken from the sample XML and place the event near
    Kunduz, Afghanistan. Used to test red-severity matching logic.

    Returns:
        A normalised event dict as produced by ``_build_rss_event_summary()``.
    """
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
    """Return an orange-alert flood event near Cuba.

    Coordinates are taken from the sample XML and place the event near
    eastern Cuba. Used to test orange-severity matching logic.

    Returns:
        A normalised event dict as produced by ``_build_rss_event_summary()``.
    """
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
    """Return a green-alert earthquake event near Chile.

    Coordinates are taken from the sample XML and place the event off the
    coast of northern Chile. Used to test green-severity matching logic.

    Returns:
        A normalised event dict as produced by ``_build_rss_event_summary()``.
    """
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
    """Return an event with no valid coordinates.

    Used to verify that assets are never matched against events whose
    ``lat`` and ``lon`` values are None.

    Returns:
        A normalised event dict with ``lat``, ``lon``, ``latitude``, and
        ``longitude`` all set to None.
    """
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
    """Return a mixed list of events covering all severity levels.

    Includes one red, one orange, one green, and one no-coordinates event
    to exercise the full range of matching behaviour in a single test.

    Args:
        red_eq_event: Red-alert earthquake fixture.
        orange_fl_event: Orange-alert flood fixture.
        green_eq_event: Green-alert earthquake fixture.
        no_coords_event: Event with no valid coordinates fixture.

    Returns:
        A list of four normalised event dicts.
    """
    return [red_eq_event, orange_fl_event, green_eq_event, no_coords_event]


# ---------------------------------------------------------------------------
# Sample asset dicts
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_assets() -> dict:
    """Return a small set of test assets covering all matching scenarios.

    Assets included:
        - AST_NEAR_AFG: ~50 miles from the red EQ event (Afghanistan area).
        - AST_NEAR_CUBA: ~30 miles from the orange FL event (Cuba area).
        - AST_FAR: Wellington, New Zealand — far from all events.
        - AST_NO_COORD: Asset with no coordinates, should always be skipped.

    Returns:
        A four-tuple ``(cities, countries, coordinates, assets_by_id)``
        matching the structure returned by ``core.assets()``.
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
