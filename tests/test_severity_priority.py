from disaster_factor import core


def test_intel_prefers_red_over_orange_and_green() -> None:
    events = [
        {"eventid": "E-ORANGE", "eventtype": "FL", "alertlevel": "orange", "lat": 1.0, "lon": 1.0},
        {"eventid": "E-RED", "eventtype": "FL", "alertlevel": "red", "lat": 1.0, "lon": 1.0},
        {"eventid": "E-GREEN", "eventtype": "FL", "alertlevel": "green", "lat": 1.0, "lon": 1.0},
    ]
    coordinates = {"AST001": (1.0, 1.0)}
    cities = {"AST001": "Sendai"}
    countries = {"AST001": "Japan"}
    assets_by_id = {"AST001": {"unique_id": "AST001", "city": "Sendai", "country": "Japan"}}

    red_matches, prelim_matches, red_points = core.intel(
        events,
        coordinates,
        cities,
        countries,
        assets_by_id,
    )

    assert len(red_matches) == 1
    assert red_matches[0]["event_id"] == "E-RED"

    assert len(prelim_matches) == 1
    assert prelim_matches[0]["severity"] == "red"
    assert prelim_matches[0]["event_id"] == "E-RED"

    assert len(red_points) == 1
    assert red_points[0]["severity"] == "red"
    assert red_points[0]["label"] == "Sendai, Japan"


def test_intel_falls_back_to_orange_then_green() -> None:
    events = [
        {"eventid": "E-GREEN-A1", "eventtype": "FL", "alertlevel": "green", "lat": 2.0, "lon": 2.0},
        {"eventid": "E-ORANGE-A1", "eventtype": "FL", "alertlevel": "orange", "lat": 2.0, "lon": 2.0},
        {"eventid": "E-GREEN-A2", "eventtype": "FL", "alertlevel": "green", "lat": 3.0, "lon": 3.0},
    ]
    coordinates = {
        "AST001": (2.0, 2.0),
        "AST002": (3.0, 3.0),
    }
    cities = {"AST001": "A", "AST002": "B"}
    countries = {"AST001": "AA", "AST002": "BB"}
    assets_by_id = {
        "AST001": {"unique_id": "AST001"},
        "AST002": {"unique_id": "AST002"},
        "AST003": {"unique_id": "AST003"},
    }

    # AST001 matches both orange and green -> orange should win.
    # AST002 matches green only -> green should be selected.
    red_matches, prelim_matches, red_points = core.intel(
        events,
        coordinates,
        cities,
        countries,
        assets_by_id,
    )

    assert red_matches == []
    assert red_points == []
    assert len(prelim_matches) == 2

    prelim_by_asset = {row["unique_id"]: row for row in prelim_matches}
    assert prelim_by_asset["AST001"]["severity"] == "orange"
    assert prelim_by_asset["AST001"]["event_id"] == "E-ORANGE-A1"
    assert prelim_by_asset["AST002"]["severity"] == "green"
    assert prelim_by_asset["AST002"]["event_id"] == "E-GREEN-A2"
