"""Unit tests for private helper functions in disaster_factor.core."""
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
    """Wrap an XML fragment in an <item> tag and parse it."""
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
    def test_finds_matching_tag(self):
        item = _make_item("<gdacs:eventtype>EQ</gdacs:eventtype>")
        result = _find_text_suffix(item, "eventtype")
        assert result == "EQ"

    def test_strips_whitespace(self):
        item = _make_item("<gdacs:eventtype>  TC  </gdacs:eventtype>")
        result = _find_text_suffix(item, "eventtype")
        assert result == "TC"

    def test_returns_empty_string_when_no_match(self):
        item = _make_item("<gdacs:eventtype>EQ</gdacs:eventtype>")
        result = _find_text_suffix(item, "nonexistent")
        assert result == ""

    def test_case_insensitive_suffix(self):
        item = _make_item("<gdacs:EventType>FL</gdacs:EventType>")
        result = _find_text_suffix(item, "eventtype")
        assert result == "FL"

    def test_returns_empty_string_for_empty_tag(self):
        item = _make_item("<gdacs:eventtype></gdacs:eventtype>")
        result = _find_text_suffix(item, "eventtype")
        assert result == ""


# ---------------------------------------------------------------------------
# _extract_rss_geo_point
# ---------------------------------------------------------------------------

class TestExtractRssGeoPoint:
    def test_valid_coordinates(self):
        item = _make_item(
            "<geo:Point><geo:lat>36.5894</geo:lat><geo:long>67.4843</geo:long></geo:Point>"
        )
        lat, lon, reason = _extract_rss_geo_point(item)
        assert reason == "ok"
        assert lat == pytest.approx(36.5894)
        assert lon == pytest.approx(67.4843)

    def test_negative_coordinates(self):
        item = _make_item(
            "<geo:Point><geo:lat>-27.4457</geo:lat><geo:long>-71.4784</geo:long></geo:Point>"
        )
        lat, lon, reason = _extract_rss_geo_point(item)
        assert reason == "ok"
        assert lat == pytest.approx(-27.4457)
        assert lon == pytest.approx(-71.4784)

    def test_missing_geo_point_tag(self):
        item = _make_item("<gdacs:eventtype>EQ</gdacs:eventtype>")
        lat, lon, reason = _extract_rss_geo_point(item)
        assert reason == "missing_tag"
        assert lat is None
        assert lon is None

    def test_missing_lat_lon_text(self):
        item = _make_item(
            "<geo:Point><geo:lat></geo:lat><geo:long></geo:long></geo:Point>"
        )
        lat, lon, reason = _extract_rss_geo_point(item)
        assert reason == "missing_latlon"
        assert lat is None
        assert lon is None

    def test_non_numeric_coordinates(self):
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
    def _make_full_item(self, eventtype="EQ", eventid="1234", alertlevel="Green",
                        lat="36.0", lon="67.0"):
        return _make_item(
            f"<gdacs:eventtype>{eventtype}</gdacs:eventtype>"
            f"<gdacs:eventid>{eventid}</gdacs:eventid>"
            f"<gdacs:alertlevel>{alertlevel}</gdacs:alertlevel>"
            f"<geo:Point><geo:lat>{lat}</geo:lat><geo:long>{lon}</geo:long></geo:Point>"
        )

    def test_returns_dict_with_all_keys(self):
        item = self._make_full_item()
        result = _build_rss_event_summary(item)
        assert result is not None
        for key in ("eventid", "eventtype", "alertlevel", "lat", "lon",
                    "eventdata_url", "latitude", "longitude"):
            assert key in result

    def test_correct_eventdata_url(self):
        item = self._make_full_item(eventtype="TC", eventid="9999")
        result = _build_rss_event_summary(item)
        assert result["eventdata_url"] == (
            "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
            "?eventtype=TC&eventid=9999"
        )

    def test_returns_none_when_eventtype_missing(self):
        item = _make_item("<gdacs:eventid>1234</gdacs:eventid>")
        assert _build_rss_event_summary(item) is None

    def test_returns_none_when_eventid_missing(self):
        item = _make_item("<gdacs:eventtype>EQ</gdacs:eventtype>")
        assert _build_rss_event_summary(item) is None

    def test_lat_lon_none_when_no_geo_point(self):
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
        assert _normalize_alertlevel(value) == expected

    @pytest.mark.parametrize("value", [
        "Yellow", "Blue", "", "  ", None, 0, 123, "unknown",
    ])
    def test_invalid_levels_return_none(self, value):
        assert _normalize_alertlevel(value) is None


# ---------------------------------------------------------------------------
# _distance_threshold_miles
# ---------------------------------------------------------------------------

class TestDistanceThresholdMiles:
    @pytest.mark.parametrize("eventtype,expected", [
        ("EQ", 150.0),
        ("TC", 200.0),
        ("FL", 75.0),
        ("VO", 100.0),
        ("WF", 75.0),
        ("TS", 250.0),
    ])
    def test_known_types(self, eventtype, expected):
        assert _distance_threshold_miles(eventtype) == expected

    @pytest.mark.parametrize("eventtype", ["eq", "tc", "fl"])
    def test_case_insensitive(self, eventtype):
        upper = _distance_threshold_miles(eventtype.upper())
        lower = _distance_threshold_miles(eventtype)
        assert lower == upper

    def test_unknown_type_returns_default(self):
        result = _distance_threshold_miles("XX")
        assert result == _THRESHOLD_MILES_DEFAULT

    def test_empty_string_returns_default(self):
        result = _distance_threshold_miles("")
        assert result == _THRESHOLD_MILES_DEFAULT

    def test_default_is_minimum_of_known_thresholds(self):
        assert _THRESHOLD_MILES_DEFAULT == min(_THRESHOLD_MILES_BY_TYPE.values())


# ---------------------------------------------------------------------------
# _euclidean_distance
# ---------------------------------------------------------------------------

class TestEuclideanDistance:
    def test_same_point_is_zero(self):
        assert _euclidean_distance(10.0, 20.0, 10.0, 20.0) == pytest.approx(0.0)

    def test_one_degree_latitude(self):
        # 1 degree lat difference = 69 miles
        dist = _euclidean_distance(0.0, 0.0, 1.0, 0.0)
        assert dist == pytest.approx(69.0)

    def test_one_degree_longitude(self):
        # 1 degree lon difference = 69 miles (Euclidean, no curvature)
        dist = _euclidean_distance(0.0, 0.0, 0.0, 1.0)
        assert dist == pytest.approx(69.0)

    def test_diagonal(self):
        # 3-4-5 triangle: 3 deg lat, 4 deg lon → 5 * 69 miles
        dist = _euclidean_distance(0.0, 0.0, 3.0, 4.0)
        assert dist == pytest.approx(5.0 * 69.0)

    def test_negative_coordinates(self):
        dist = _euclidean_distance(-10.0, -20.0, -11.0, -20.0)
        assert dist == pytest.approx(69.0)

    def test_symmetry(self):
        d1 = _euclidean_distance(10.0, 20.0, 30.0, 40.0)
        d2 = _euclidean_distance(30.0, 40.0, 10.0, 20.0)
        assert d1 == pytest.approx(d2)

    def test_always_non_negative(self):
        assert _euclidean_distance(0.0, 0.0, -5.0, -5.0) >= 0.0


# ---------------------------------------------------------------------------
# _is_asset_affected
# ---------------------------------------------------------------------------

class TestIsAssetAffected:
    def test_asset_within_threshold_is_affected(self):
        # Asset ~50 miles from EQ event (threshold 150 miles)
        event = {"lat": 36.5894, "lon": 67.4843, "eventtype": "EQ"}
        assert _is_asset_affected((36.9, 67.7), event) is True

    def test_asset_beyond_threshold_is_not_affected(self):
        # Asset in New Zealand, far from Afghanistan EQ
        event = {"lat": 36.5894, "lon": 67.4843, "eventtype": "EQ"}
        assert _is_asset_affected((-41.3, 174.8), event) is False

    def test_event_with_none_lat_returns_false(self):
        event = {"lat": None, "lon": 67.4843, "eventtype": "EQ"}
        assert _is_asset_affected((36.9, 67.7), event) is False

    def test_event_with_none_lon_returns_false(self):
        event = {"lat": 36.5894, "lon": None, "eventtype": "EQ"}
        assert _is_asset_affected((36.9, 67.7), event) is False

    def test_event_with_non_numeric_lat_returns_false(self):
        event = {"lat": "abc", "lon": 67.4843, "eventtype": "EQ"}
        assert _is_asset_affected((36.9, 67.7), event) is False

    def test_event_with_non_numeric_lon_returns_false(self):
        event = {"lat": 36.5894, "lon": "xyz", "eventtype": "EQ"}
        assert _is_asset_affected((36.9, 67.7), event) is False

    def test_uses_correct_threshold_per_type(self):
        # Place asset exactly at the FL threshold boundary (75 miles = ~1.087 degrees)
        # Asset at (0, 0), event at (0, 1.086) → ~74.9 miles → within FL threshold
        event_near = {"lat": 0.0, "lon": 1.086, "eventtype": "FL"}
        assert _is_asset_affected((0.0, 0.0), event_near) is True

        # Asset at (0, 0), event at (0, 1.1) → ~75.9 miles → beyond FL threshold
        event_far = {"lat": 0.0, "lon": 1.1, "eventtype": "FL"}
        assert _is_asset_affected((0.0, 0.0), event_far) is False

    def test_unknown_event_type_uses_default_threshold(self):
        # Default threshold is 75 miles (min of all types)
        # Asset at (0, 0), event at (0, 1.0) → 69 miles → within default threshold
        event = {"lat": 0.0, "lon": 1.0, "eventtype": "UNKNOWN"}
        assert _is_asset_affected((0.0, 0.0), event) is True

    def test_asset_exactly_at_event_location(self):
        event = {"lat": 36.5894, "lon": 67.4843, "eventtype": "EQ"}
        assert _is_asset_affected((36.5894, 67.4843), event) is True
