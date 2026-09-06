"""Unit tests for private helper functions in disaster_factor.core.

Covers ``_find_text_suffix``, ``_extract_rss_geo_point``,
``_build_rss_event_summary``, ``_normalize_alertlevel``,
``_distance_threshold_miles``, ``_euclidean_distance``, and
``_is_asset_affected``. All tests are offline and require no network access.
"""

from __future__ import annotations

import math
import pytest
from bs4 import BeautifulSoup

from disaster_factor.core import (
    _find_text_suffix,
    _extract_rss_geo_point,
    _build_rss_event_summary,
    _normalize_alertlevel,
    _distance_threshold_miles,
    _euclidean_distance,
    _is_asset_affected,
    _THRESHOLD_MILES_BY_TYPE,
    _THRESHOLD_MILES_DEFAULT,
)


# ---------------------------------------------------------------------------
# Helpers to build minimal BeautifulSoup items for testing
# ---------------------------------------------------------------------------

def _make_item(xml_fragment: str) -> BeautifulSoup:
    """Wrap an XML fragment in an ``<item>`` tag and parse it.

    Injects the GDACS and geo namespace declarations so that namespaced
    tags resolve correctly under the ``lxml-xml`` parser.

    Args:
        xml_fragment: Raw XML string to embed inside the ``<item>`` element.

    Returns:
        A BeautifulSoup tag representing the parsed ``<item>`` element.
    """
    return BeautifulSoup(
        f'<rss xmlns:gdacs="http://www.gdacs.org" '
        f'xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#">'
        f'<item>{xml_fragment}</item></rss>',
        features="xml",
    ).find("item")


# ---------------------------------------------------------------------------
# _find_text_suffix
# ---------------------------------------------------------------------------

class TestFindTextSuffix:
    """Tests for ``_find_text_suffix``."""

    def test_finds_matching_tag(self):
        """Returns text content of the first tag whose name ends with the suffix."""
        item = _make_item("<gdacs:eventtype>EQ</gdacs:eventtype>")
        result = _find_text_suffix(item, "eventtype")
        assert result == "EQ"

    def test_strips_whitespace(self):
        """Strips leading and trailing whitespace from the matched tag text."""
        item = _make_item("<gdacs:eventtype>  TC  </gdacs:eventtype>")
        result = _find_text_suffix(item, "eventtype")
        assert result == "TC"

    def test_returns_empty_string_when_no_match(self):
        """Returns an empty string when no child tag matches the suffix."""
        item = _make_item("<gdacs:eventtype>EQ</gdacs:eventtype>")
        result = _find_text_suffix(item, "nonexistent")
        assert result == ""

    def test_case_insensitive_suffix(self):
        """Suffix matching is case-insensitive."""
        item = _make_item("<gdacs:EventType>FL</gdacs:EventType>")
        result = _find_text_suffix(item, "eventtype")
        assert result == "FL"

    def test_returns_empty_string_for_empty_tag(self):
        """Returns an empty string when the matching tag has no text content."""
        item = _make_item("<gdacs:eventtype></gdacs:eventtype>")
        result = _find_text_suffix(item, "eventtype")
        assert result == ""


# ---------------------------------------------------------------------------
# _extract_rss_geo_point
# ---------------------------------------------------------------------------

class TestExtractRssGeoPoint:
    """Tests for ``_extract_rss_geo_point``."""

    def test_valid_coordinates(self):
        """Parses positive lat/lon values and returns reason ``"ok"``."""
        item = _make_item(
            "<geo:Point><geo:lat>36.5894</geo:lat><geo:long>67.4843</geo:long></geo:Point>"
        )
        lat, lon, reason = _extract_rss_geo_point(item)
        assert reason == "ok"
        assert lat == pytest.approx(36.5894)
        assert lon == pytest.approx(67.4843)

    def test_negative_coordinates(self):
        """Parses negative lat/lon values and returns reason ``"ok"``."""
        item = _make_item(
            "<geo:Point><geo:lat>-27.4457</geo:lat><geo:long>-71.4784</geo:long></geo:Point>"
        )
        lat, lon, reason = _extract_rss_geo_point(item)
        assert reason == "ok"
        assert lat == pytest.approx(-27.4457)
        assert lon == pytest.approx(-71.4784)

    def test_missing_geo_point_tag(self):
        """Returns ``(None, None, "missing_tag")`` when no ``geo:Point`` element exists."""
        item = _make_item("<gdacs:eventtype>EQ</gdacs:eventtype>")
        lat, lon, reason = _extract_rss_geo_point(item)
        assert reason == "missing_tag"
        assert lat is None
        assert lon is None

    def test_missing_lat_lon_text(self):
        """Returns ``(None, None, "missing_latlon")`` when lat/lon elements are empty."""
        item = _make_item(
            "<geo:Point><geo:lat></geo:lat><geo:long></geo:long></geo:Point>"
        )
        lat, lon, reason = _extract_rss_geo_point(item)
        assert reason == "missing_latlon"
        assert lat is None
        assert lon is None

    def test_non_numeric_coordinates(self):
        """Returns ``(None, None, "non_numeric")`` when lat/lon text cannot be cast to float."""
        item = _make_item(
            "<geo:Point><geo:lat>abc</geo:lat><geo:long>xyz</geo:long></geo:Point>"
        )
        lat, lon, reason = _extract_rss_geo_point(item)
        assert reason == "non_numeric"
        assert lat is None
        assert lon is None

    def test_uses_real_sample_item(self, gdacs_items):
        """The first item in the sample XML (Chile EQ) should parse cleanly."""
        lat, lon, reason = _extract_rss_geo_point(gdacs_items[0])
        assert reason == "ok"
        assert lat == pytest.approx(-27.4457)
        assert lon == pytest.approx(-71.4784)


# ---------------------------------------------------------------------------
# _build_rss_event_summary
# ---------------------------------------------------------------------------

class TestBuildRssEventSummary:
    """Tests for ``_build_rss_event_summary``."""

    def _make_full_item(self, eventtype="EQ", eventid="1234", alertlevel="Green",
                        lat="36.0", lon="67.0"):
        """Build a minimal but complete RSS item with all required fields.

        Args:
            eventtype: GDACS event type code. Defaults to ``"EQ"``.
            eventid: GDACS event identifier. Defaults to ``"1234"``.
            alertlevel: Alert severity string. Defaults to ``"Green"``.
            lat: Latitude string. Defaults to ``"36.0"``.
            lon: Longitude string. Defaults to ``"67.0"``.

        Returns:
            A BeautifulSoup tag representing the parsed ``<item>`` element.
        """
        return _make_item(
            f"<gdacs:eventtype>{eventtype}</gdacs:eventtype>"
            f"<gdacs:eventid>{eventid}</gdacs:eventid>"
            f"<gdacs:alertlevel>{alertlevel}</gdacs:alertlevel>"
            f"<geo:Point><geo:lat>{lat}</geo:lat><geo:long>{lon}</geo:long></geo:Point>"
        )

    def test_returns_dict_with_all_keys(self):
        """Result dict contains all required keys."""
        item = self._make_full_item()
        result = _build_rss_event_summary(item)
        assert result is not None
        for key in ("eventid", "eventtype", "alertlevel", "lat", "lon",
                    "eventdata_url", "latitude", "longitude"):
            assert key in result

    def test_correct_eventdata_url(self):
        """Constructs the GDACS eventdata URL from eventtype and eventid."""
        item = self._make_full_item(eventtype="TC", eventid="9999")
        result = _build_rss_event_summary(item)
        assert result["eventdata_url"] == (
            "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
            "?eventtype=TC&eventid=9999"
        )

    def test_returns_none_when_eventtype_missing(self):
        """Returns None when the item has no eventtype tag."""
        item = _make_item("<gdacs:eventid>1234</gdacs:eventid>")
        assert _build_rss_event_summary(item) is None

    def test_returns_none_when_eventid_missing(self):
        """Returns None when the item has no eventid tag."""
        item = _make_item("<gdacs:eventtype>EQ</gdacs:eventtype>")
        assert _build_rss_event_summary(item) is None

    def test_lat_lon_none_when_no_geo_point(self):
        """Sets lat, lon, latitude, and longitude to None when geo:Point is absent."""
        item = _make_item(
            "<gdacs:eventtype>EQ</gdacs:eventtype>"
            "<gdacs:eventid>1234</gdacs:eventid>"
        )
        result = _build_rss_event_summary(item)
        assert result is not None
        assert result["lat"] is None
        assert result["lon"] is None
        assert result["latitude"] is None
        assert result["longitude"] is None

    def test_latitude_longitude_are_strings(self):
        """The latitude and longitude fields in the result dict are strings."""
        item = self._make_full_item(lat="36.5894", lon="67.4843")
        result = _build_rss_event_summary(item)
        assert isinstance(result["latitude"], str)
        assert isinstance(result["longitude"], str)

    def test_real_red_item(self, gdacs_items):
        """The Afghanistan red EQ item (index 3) should parse correctly."""
        result = _build_rss_event_summary(gdacs_items[3])
        assert result is not None
        assert result["eventtype"] == "EQ"
        assert result["eventid"] == "1508467"
        assert result["alertlevel"] == "Red"
        assert result["lat"] == pytest.approx(36.5894)


# ---------------------------------------------------------------------------
# _normalize_alertlevel
# ---------------------------------------------------------------------------

class TestNormalizeAlertlevel:
    """Tests for ``_normalize_alertlevel``."""

    @pytest.mark.parametrize("value,expected", [
        ("Red", "red"),
        ("RED", "red"),
        ("red", "red"),
        ("  Red  ", "red"),
        ("Orange", "orange"),
        ("ORANGE", "orange"),
        ("Green", "green"),
        ("GREEN", "green"),
    ])
    def test_valid_levels(self, value, expected):
        """Normalises valid alert level strings to lowercase canonical form."""
        assert _normalize_alertlevel(value) == expected

    @pytest.mark.parametrize("value", [
        "Yellow", "Blue", "", "  ", None, 0, 123, "unknown",
    ])
    def test_invalid_levels_return_none(self, value):
        """Returns None for any value that is not red, orange, or green."""
        assert _normalize_alertlevel(value) is None


# ---------------------------------------------------------------------------
# _distance_threshold_miles
# ---------------------------------------------------------------------------

class TestDistanceThresholdMiles:
    """Tests for ``_distance_threshold_miles``."""

    @pytest.mark.parametrize("eventtype,expected", [
        ("EQ", 150.0),
        ("TC", 200.0),
        ("FL", 75.0),
        ("VO", 100.0),
        ("WF", 75.0),
        ("TS", 250.0),
    ])
    def test_known_types(self, eventtype, expected):
        """Returns the correct threshold for each known GDACS event type."""
        assert _distance_threshold_miles(eventtype) == expected

    @pytest.mark.parametrize("eventtype", ["eq", "tc", "fl"])
    def test_case_insensitive(self, eventtype):
        """Threshold lookup is case-insensitive."""
        upper = _distance_threshold_miles(eventtype.upper())
        lower = _distance_threshold_miles(eventtype)
        assert lower == upper

    def test_unknown_type_returns_default(self):
        """Returns the default threshold for an unrecognised event type code."""
        result = _distance_threshold_miles("XX")
        assert result == _THRESHOLD_MILES_DEFAULT

    def test_empty_string_returns_default(self):
        """Returns the default threshold when given an empty string."""
        result = _distance_threshold_miles("")
        assert result == _THRESHOLD_MILES_DEFAULT

    def test_default_is_minimum_of_known_thresholds(self):
        """The default threshold equals the minimum across all known type thresholds."""
        assert _THRESHOLD_MILES_DEFAULT == min(_THRESHOLD_MILES_BY_TYPE.values())


# ---------------------------------------------------------------------------
# _euclidean_distance
# ---------------------------------------------------------------------------

class TestEuclideanDistance:
    """Tests for ``_euclidean_distance``."""

    def test_same_point_is_zero(self):
        """Distance between a point and itself is zero."""
        assert _euclidean_distance(10.0, 20.0, 10.0, 20.0) == pytest.approx(0.0)

    def test_one_degree_latitude(self):
        """One degree of latitude difference equals 69 miles."""
        dist = _euclidean_distance(0.0, 0.0, 1.0, 0.0)
        assert dist == pytest.approx(69.0)

    def test_one_degree_longitude(self):
        """One degree of longitude difference equals 69 miles (flat-earth, no curvature)."""
        dist = _euclidean_distance(0.0, 0.0, 0.0, 1.0)
        assert dist == pytest.approx(69.0)

    def test_diagonal(self):
        """A 3-4-5 degree triangle yields a hypotenuse of 5 * 69 miles."""
        dist = _euclidean_distance(0.0, 0.0, 3.0, 4.0)
        assert dist == pytest.approx(5.0 * 69.0)

    def test_negative_coordinates(self):
        """Works correctly with negative latitude and longitude values."""
        dist = _euclidean_distance(-10.0, -20.0, -11.0, -20.0)
        assert dist == pytest.approx(69.0)

    def test_symmetry(self):
        """Distance from A to B equals distance from B to A."""
        d1 = _euclidean_distance(10.0, 20.0, 30.0, 40.0)
        d2 = _euclidean_distance(30.0, 40.0, 10.0, 20.0)
        assert d1 == pytest.approx(d2)

    def test_always_non_negative(self):
        """Result is always non-negative regardless of coordinate order."""
        assert _euclidean_distance(0.0, 0.0, -5.0, -5.0) >= 0.0


# ---------------------------------------------------------------------------
# _is_asset_affected
# ---------------------------------------------------------------------------

class TestIsAssetAffected:
    """Tests for ``_is_asset_affected``."""

    def test_asset_within_threshold_is_affected(self):
        """Returns True when asset is within the event's type-specific threshold."""
        # Asset ~50 miles from EQ event (threshold 150 miles)
        event = {"lat": 36.5894, "lon": 67.4843, "eventtype": "EQ"}
        assert _is_asset_affected((36.9, 67.7), event) is True

    def test_asset_beyond_threshold_is_not_affected(self):
        """Returns False when asset is beyond the event's type-specific threshold."""
        # Asset in New Zealand, far from Afghanistan EQ
        event = {"lat": 36.5894, "lon": 67.4843, "eventtype": "EQ"}
        assert _is_asset_affected((-41.3, 174.8), event) is False

    def test_event_with_none_lat_returns_false(self):
        """Returns False when event lat is None."""
        event = {"lat": None, "lon": 67.4843, "eventtype": "EQ"}
        assert _is_asset_affected((36.9, 67.7), event) is False

    def test_event_with_none_lon_returns_false(self):
        """Returns False when event lon is None."""
        event = {"lat": 36.5894, "lon": None, "eventtype": "EQ"}
        assert _is_asset_affected((36.9, 67.7), event) is False

    def test_event_with_non_numeric_lat_returns_false(self):
        """Returns False when event lat cannot be cast to float."""
        event = {"lat": "abc", "lon": 67.4843, "eventtype": "EQ"}
        assert _is_asset_affected((36.9, 67.7), event) is False

    def test_event_with_non_numeric_lon_returns_false(self):
        """Returns False when event lon cannot be cast to float."""
        event = {"lat": 36.5894, "lon": "xyz", "eventtype": "EQ"}
        assert _is_asset_affected((36.9, 67.7), event) is False

    def test_uses_correct_threshold_per_type(self):
        """Applies the FL-specific 75-mile threshold rather than a generic value."""
        # Place asset exactly at the FL threshold boundary (75 miles = ~1.087 degrees)
        # Asset at (0, 0), event at (0, 1.086) → ~74.9 miles → within FL threshold
        event_near = {"lat": 0.0, "lon": 1.086, "eventtype": "FL"}
        assert _is_asset_affected((0.0, 0.0), event_near) is True

        # Asset at (0, 0), event at (0, 1.1) → ~75.9 miles → beyond FL threshold
        event_far = {"lat": 0.0, "lon": 1.1, "eventtype": "FL"}
        assert _is_asset_affected((0.0, 0.0), event_far) is False

    def test_unknown_event_type_uses_default_threshold(self):
        """Falls back to the default threshold for unrecognised event type codes."""
        # Default threshold is 75 miles (min of all types)
        # Asset at (0, 0), event at (0, 1.0) → 69 miles → within default threshold
        event = {"lat": 0.0, "lon": 1.0, "eventtype": "UNKNOWN"}
        assert _is_asset_affected((0.0, 0.0), event) is True

    def test_asset_exactly_at_event_location(self):
        """Returns True when the asset coordinate exactly matches the event location."""
        event = {"lat": 36.5894, "lon": 67.4843, "eventtype": "EQ"}
        assert _is_asset_affected((36.5894, 67.4843), event) is True
