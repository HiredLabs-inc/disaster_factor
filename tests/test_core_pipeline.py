"""Integration tests for the RAID pipeline functions in disaster_factor.core."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from disaster_factor.core import (
    recon,
    assets,
    intel,
    disseminate,
    track_disasters,
)

DATA_DIR = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_response(content: bytes, status_code: int = 200) -> MagicMock:
    """Build a mock requests.Response."""
    mock_resp = MagicMock()
    mock_resp.content = content
    mock_resp.status_code = status_code
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = Exception(
            f"HTTP Error {status_code}"
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


# ---------------------------------------------------------------------------
# recon()
# ---------------------------------------------------------------------------

class TestRecon:
    """Tests for the R (Recon) stage — mocks requests.get."""

    @pytest.fixture
    def rss_bytes(self) -> bytes:
        return (DATA_DIR / "gdacs_rss_sample.xml").read_bytes()

    def test_returns_correct_total_red(self, rss_bytes):
        """Sample XML has 3 red alerts: Afghanistan EQ + TC KALMAEGI (1001233) + TC 1001230."""
        with patch("disaster_factor.core.requests.get") as mock_get:
            mock_get.return_value = _make_mock_response(rss_bytes)
            total_red, events = recon()
        assert total_red == 3

    def test_returns_list_of_event_dicts(self, rss_bytes):
        with patch("disaster_factor.core.requests.get") as mock_get:
            mock_get.return_value = _make_mock_response(rss_bytes)
            _, events = recon()
        assert isinstance(events, list)
        assert len(events) > 0
        for event in events:
            assert isinstance(event, dict)

    def test_event_dicts_have_required_keys(self, rss_bytes):
        with patch("disaster_factor.core.requests.get") as mock_get:
            mock_get.return_value = _make_mock_response(rss_bytes)
            _, events = recon()
        required_keys = {"eventid", "eventtype", "alertlevel", "lat", "lon", "eventdata_url"}
        for event in events:
            assert required_keys.issubset(event.keys()), (
                f"Event missing keys: {required_keys - event.keys()}"
            )

    def test_red_events_have_correct_alertlevel(self, rss_bytes):
        with patch("disaster_factor.core.requests.get") as mock_get:
            mock_get.return_value = _make_mock_response(rss_bytes)
            _, events = recon()
        red_events = [e for e in events if e.get("alertlevel", "").lower() == "red"]
        assert len(red_events) == 3
        event_ids = {e["eventid"] for e in red_events}
        assert "1508467" in event_ids   # Afghanistan EQ
        assert "1001233" in event_ids   # TC KALMAEGI-25
        assert "1001230" in event_ids   # TC (second red TC)

    def test_raises_on_http_error(self):
        with patch("disaster_factor.core.requests.get") as mock_get:
            mock_get.return_value = _make_mock_response(b"", status_code=500)
            with pytest.raises(Exception):
                recon()

    def test_debug_mode_does_not_raise(self, rss_bytes):
        with patch("disaster_factor.core.requests.get") as mock_get:
            mock_get.return_value = _make_mock_response(rss_bytes)
            total_red, events = recon(debug=True)
        assert isinstance(total_red, int)
        assert isinstance(events, list)

    def test_requests_get_called_with_gdacs_url(self, rss_bytes):
        with patch("disaster_factor.core.requests.get") as mock_get:
            mock_get.return_value = _make_mock_response(rss_bytes)
            recon()
        call_args = mock_get.call_args
        assert "gdacs.org" in call_args[0][0]


# ---------------------------------------------------------------------------
# assets()
# ---------------------------------------------------------------------------

class TestAssets:
    """Tests for the A (Assets) stage — mocks geocode_assets()."""

    def _make_asset_rows(self):
        return [
            {"unique_id": "AST001", "city": "Tokyo", "country": "Japan",
             "type": "personnel", "latitude": 35.689, "longitude": 139.692},
            {"unique_id": "AST002", "city": "Manila", "country": "Philippines",
             "type": "building", "latitude": 14.6, "longitude": 120.984},
            {"unique_id": "AST003", "city": "Unknown", "country": "Unknown",
             "type": "vehicle", "latitude": "", "longitude": ""},
            # Row with no unique_id should be skipped
            {"unique_id": "", "city": "Ghost", "country": "Nowhere",
             "type": "personnel", "latitude": 0.0, "longitude": 0.0},
        ]

    def test_returns_four_tuple(self):
        with patch("disaster_factor.core.geocode_assets") as mock_ga:
            mock_ga.return_value = self._make_asset_rows()
            result = assets()
        assert isinstance(result, tuple)
        assert len(result) == 4

    def test_cities_and_countries_populated(self):
        with patch("disaster_factor.core.geocode_assets") as mock_ga:
            mock_ga.return_value = self._make_asset_rows()
            cities, countries, coordinates, assets_by_id = assets()
        assert cities["AST001"] == "Tokyo"
        assert countries["AST001"] == "Japan"
        assert cities["AST002"] == "Manila"
        assert countries["AST002"] == "Philippines"

    def test_valid_coordinates_stored_as_tuple(self):
        with patch("disaster_factor.core.geocode_assets") as mock_ga:
            mock_ga.return_value = self._make_asset_rows()
            _, _, coordinates, _ = assets()
        assert isinstance(coordinates["AST001"], tuple)
        assert len(coordinates["AST001"]) == 2
        assert coordinates["AST001"][0] == pytest.approx(35.689)
        assert coordinates["AST001"][1] == pytest.approx(139.692)

    def test_missing_coordinates_stored_as_none(self):
        with patch("disaster_factor.core.geocode_assets") as mock_ga:
            mock_ga.return_value = self._make_asset_rows()
            _, _, coordinates, _ = assets()
        assert coordinates["AST003"] is None

    def test_asset_without_unique_id_is_skipped(self):
        with patch("disaster_factor.core.geocode_assets") as mock_ga:
            mock_ga.return_value = self._make_asset_rows()
            _, _, _, assets_by_id = assets()
        assert "" not in assets_by_id

    def test_assets_by_id_contains_full_row(self):
        with patch("disaster_factor.core.geocode_assets") as mock_ga:
            mock_ga.return_value = self._make_asset_rows()
            _, _, _, assets_by_id = assets()
        assert "AST001" in assets_by_id
        assert assets_by_id["AST001"]["city"] == "Tokyo"


# ---------------------------------------------------------------------------
# intel()
# ---------------------------------------------------------------------------

class TestIntel:
    """Tests for the I (Intel) stage — pure logic, no mocking needed."""

    def test_red_asset_in_red_matches_and_prelim(self, sample_assets, red_eq_event):
        cities, countries, coordinates, assets_by_id = sample_assets
        events = [red_eq_event]
        red_matches, prelim_matches, red_points = intel(
            events, coordinates, cities, countries, assets_by_id
        )
        red_ids = {m["unique_id"] for m in red_matches}
        prelim_ids = {m["unique_id"] for m in prelim_matches}
        assert "AST_NEAR_AFG" in red_ids
        assert "AST_NEAR_AFG" in prelim_ids

    def test_orange_asset_only_in_prelim(self, sample_assets, orange_fl_event):
        cities, countries, coordinates, assets_by_id = sample_assets
        events = [orange_fl_event]
        red_matches, prelim_matches, red_points = intel(
            events, coordinates, cities, countries, assets_by_id
        )
        red_ids = {m["unique_id"] for m in red_matches}
        prelim_ids = {m["unique_id"] for m in prelim_matches}
        assert "AST_NEAR_CUBA" not in red_ids
        assert "AST_NEAR_CUBA" in prelim_ids

    def test_orange_match_has_correct_severity(self, sample_assets, orange_fl_event):
        cities, countries, coordinates, assets_by_id = sample_assets
        events = [orange_fl_event]
        _, prelim_matches, _ = intel(
            events, coordinates, cities, countries, assets_by_id
        )
        cuba_match = next(
            (m for m in prelim_matches if m["unique_id"] == "AST_NEAR_CUBA"), None
        )
        assert cuba_match is not None
        assert cuba_match["severity"] == "orange"

    def test_red_takes_priority_over_orange(self, sample_assets, red_eq_event, orange_fl_event):
        """An asset near both a red and orange event should be matched to red."""
        cities, countries, coordinates, assets_by_id = sample_assets
        # Place a new asset near both events — use Afghanistan coords (near red EQ)
        # and add a fake orange event also near Afghanistan
        orange_near_afg = {
            "eventid": "FAKE_ORANGE",
            "eventtype": "EQ",
            "alertlevel": "Orange",
            "lat": 36.6,
            "lon": 67.5,
        }
        events = [red_eq_event, orange_near_afg]
        red_matches, prelim_matches, _ = intel(
            events, coordinates, cities, countries, assets_by_id
        )
        # AST_NEAR_AFG should be matched to red, not orange
        red_ids = {m["unique_id"] for m in red_matches}
        assert "AST_NEAR_AFG" in red_ids
        # In prelim, severity should be "red"
        afg_prelim = next(
            (m for m in prelim_matches if m["unique_id"] == "AST_NEAR_AFG"), None
        )
        assert afg_prelim is not None
        assert afg_prelim["severity"] == "red"

    def test_far_asset_not_in_any_output(self, sample_assets, red_eq_event):
        cities, countries, coordinates, assets_by_id = sample_assets
        events = [red_eq_event]
        red_matches, prelim_matches, red_points = intel(
            events, coordinates, cities, countries, assets_by_id
        )
        all_ids = (
            {m["unique_id"] for m in red_matches}
            | {m["unique_id"] for m in prelim_matches}
        )
        assert "AST_FAR" not in all_ids

    def test_no_coord_asset_is_skipped(self, sample_assets, red_eq_event):
        cities, countries, coordinates, assets_by_id = sample_assets
        events = [red_eq_event]
        red_matches, prelim_matches, red_points = intel(
            events, coordinates, cities, countries, assets_by_id
        )
        all_ids = (
            {m["unique_id"] for m in red_matches}
            | {m["unique_id"] for m in prelim_matches}
        )
        assert "AST_NO_COORD" not in all_ids

    def test_red_points_structure(self, sample_assets, red_eq_event):
        cities, countries, coordinates, assets_by_id = sample_assets
        events = [red_eq_event]
        _, _, red_points = intel(
            events, coordinates, cities, countries, assets_by_id
        )
        assert len(red_points) >= 1
        for pt in red_points:
            assert "lat" in pt
            assert "lon" in pt
            assert "label" in pt
            assert "severity" in pt
            assert pt["severity"] == "red"
            assert isinstance(pt["lat"], float)
            assert isinstance(pt["lon"], float)

    def test_impact_method_is_euclidean(self, sample_assets, red_eq_event):
        cities, countries, coordinates, assets_by_id = sample_assets
        events = [red_eq_event]
        red_matches, prelim_matches, _ = intel(
            events, coordinates, cities, countries, assets_by_id
        )
        for match in red_matches + prelim_matches:
            assert match["impact_method"] == "EUCLIDEAN"

    def test_empty_events_returns_empty_outputs(self, sample_assets):
        cities, countries, coordinates, assets_by_id = sample_assets
        red_matches, prelim_matches, red_points = intel(
            [], coordinates, cities, countries, assets_by_id
        )
        assert red_matches == []
        assert prelim_matches == []
        assert red_points == []

    def test_empty_assets_returns_empty_outputs(self, red_eq_event):
        red_matches, prelim_matches, red_points = intel(
            [red_eq_event], {}, {}, {}, {}
        )
        assert red_matches == []
        assert prelim_matches == []
        assert red_points == []

    def test_event_without_valid_alertlevel_is_ignored(self, sample_assets):
        cities, countries, coordinates, assets_by_id = sample_assets
        bad_event = {
            "eventid": "BAD",
            "eventtype": "EQ",
            "alertlevel": "Yellow",  # not a valid level
            "lat": 36.9,
            "lon": 67.7,
        }
        red_matches, prelim_matches, _ = intel(
            [bad_event], coordinates, cities, countries, assets_by_id
        )
        assert red_matches == []
        assert prelim_matches == []

    def test_coordinates_field_format_in_match(self, sample_assets, red_eq_event):
        cities, countries, coordinates, assets_by_id = sample_assets
        events = [red_eq_event]
        _, prelim_matches, _ = intel(
            events, coordinates, cities, countries, assets_by_id
        )
        afg_match = next(
            (m for m in prelim_matches if m["unique_id"] == "AST_NEAR_AFG"), None
        )
        assert afg_match is not None
        # coordinates field should be "lat, lon" formatted string
        assert "," in afg_match["coordinates"]


# ---------------------------------------------------------------------------
# disseminate()
# ---------------------------------------------------------------------------

class TestDisseminate:
    """Tests for the D (Disseminate) stage."""

    def test_returns_four_tuple(self):
        red = [{"unique_id": "A"}]
        prelim = [{"unique_id": "A"}, {"unique_id": "B"}]
        points = [{"lat": 1.0, "lon": 2.0, "label": "X", "severity": "red"}]
        result = disseminate(red, prelim, points, total_red=3)
        assert isinstance(result, tuple)
        assert len(result) == 4

    def test_passthrough_values(self):
        red = [{"unique_id": "A"}]
        prelim = [{"unique_id": "A"}, {"unique_id": "B"}]
        points = [{"lat": 1.0, "lon": 2.0, "label": "X", "severity": "red"}]
        total_red = 5
        out_red, out_prelim, out_points, out_total = disseminate(
            red, prelim, points, total_red
        )
        assert out_red is red
        assert out_prelim is prelim
        assert out_points is points
        assert out_total == total_red

    def test_empty_inputs(self):
        out_red, out_prelim, out_points, out_total = disseminate([], [], [], 0)
        assert out_red == []
        assert out_prelim == []
        assert out_points == []
        assert out_total == 0


# ---------------------------------------------------------------------------
# track_disasters() — end-to-end smoke test
# ---------------------------------------------------------------------------

class TestTrackDisasters:
    """Smoke test for the full RAID pipeline with all I/O mocked."""

    def test_full_pipeline_debug_mode(self):
        """Run track_disasters(debug=True) with mocked network and geocoding."""
        rss_bytes = (DATA_DIR / "gdacs_rss_sample.xml").read_bytes()

        mock_assets = [
            {"unique_id": "AST001", "city": "Kabul", "country": "Afghanistan",
             "type": "personnel", "latitude": 36.9, "longitude": 67.7},
            {"unique_id": "AST002", "city": "Wellington", "country": "New Zealand",
             "type": "building", "latitude": -41.3, "longitude": 174.8},
        ]

        with patch("disaster_factor.core.requests.get") as mock_get, \
             patch("disaster_factor.core.geocode_assets") as mock_ga:
            mock_get.return_value = _make_mock_response(rss_bytes)
            mock_ga.return_value = mock_assets
            # Should not raise; debug=True skips the web server
            track_disasters(debug=True)

        mock_get.assert_called_once()
        mock_ga.assert_called_once()

    def test_full_pipeline_returns_none(self):
        """track_disasters() returns None (it's a void orchestrator)."""
        rss_bytes = (DATA_DIR / "gdacs_rss_sample.xml").read_bytes()
        mock_assets = [
            {"unique_id": "AST001", "city": "Kabul", "country": "Afghanistan",
             "type": "personnel", "latitude": 36.9, "longitude": 67.7},
        ]
        with patch("disaster_factor.core.requests.get") as mock_get, \
             patch("disaster_factor.core.geocode_assets") as mock_ga:
            mock_get.return_value = _make_mock_response(rss_bytes)
            mock_ga.return_value = mock_assets
            result = track_disasters(debug=True)
        assert result is None
