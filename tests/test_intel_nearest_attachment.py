from __future__ import annotations


def test_intel_attaches_nearest_disaster_coords_when_not_impacted(core_mod, load_impact_json):
    impact_data = {
        "E4": {
            "impact_json": load_impact_json("getimpact-4.json"),
            "eventtype": "EQ",
            "coordinates": None,
        }
    }

    disasters = []

    cities = {"A1": "", "A2": ""}
    countries = {"A1": "", "A2": ""}

    coordinates = {
        "A1": (52.0, 177.0),
        "A2": None,  # missing coords case
    }

    assets_by_id = {
        "A1": {"unique_id": "A1", "city": "", "country": "", "type": "test"},
        "A2": {"unique_id": "A2", "city": "", "country": "", "type": "test"},
    }

    matches, outreach = core_mod.intel(
        disasters,
        cities,
        countries,
        coordinates,
        assets_by_id,
        impact_data=impact_data,
    )

    assert matches == []
    assert outreach == []

    assert "nearest_disaster_coords" in assets_by_id["A1"]
    nearest = assets_by_id["A1"]["nearest_disaster_coords"]
    assert isinstance(nearest, list)
    assert 1 <= len(nearest) <= 5

    # Missing coords case: no attachment
    assert "nearest_disaster_coords" not in assets_by_id["A2"]
