import logging

from disaster_factor import core


def test_normalize_alertlevel_accepts_only_gdacs_levels() -> None:
    assert core._normalize_alertlevel("red") == "red"
    assert core._normalize_alertlevel(" orange ") == "orange"
    assert core._normalize_alertlevel("GREEN") == "green"
    assert core._normalize_alertlevel(None) is None


def test_is_asset_affected_non_numeric_event_coordinates_logs_debug(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger=core.logger.name)
    event = {
        "eventid": "E-BAD",
        "eventtype": "FL",
        "alertlevel": "red",
        "lat": "not-a-number",
        "lon": "120.0",
    }

    result = core._is_asset_affected((14.5, 120.9), event)

    assert result is False
    assert "Skipping event with non-numeric coordinates" in caplog.text


def test_is_asset_affected_missing_coordinates_returns_false() -> None:
    assert core._is_asset_affected((0.0, 0.0), {"eventid": "E1", "eventtype": "FL"}) is False
