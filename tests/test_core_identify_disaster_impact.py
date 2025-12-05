# tests/test_core_identify_disaster_impact.py

from disaster_factor import core


def test_identify_disaster_impact_basic_city_country_match():
    print("\n--- SETUP ---")

    disasters = {
        1: {"city": "Dallas", "country": "United States", "type": "EQ"}
    }
    print("Disasters input:", disasters)

    assets_by_id = {
        "A1": {
            "unique_id": "U1",
            "city": "Dallas",
            "country": "United States",
            "type": "personnel",
        },
        "A2": {
            "unique_id": "U2",
            "city": "Houston",
            "country": "United States",
            "type": "building",
        },
    }
    print("Assets input:", assets_by_id)

    cities = {}
    countries = {}

    print("\n--- CALLING identify_disaster_impact ---")
    matches, outreach_list = core.identify_disaster_impact(
        disasters, cities, countries, assets_by_id
    )

    print("\n--- OUTPUT ---")
    print("Matches:", matches)
    print("Outreach list:", outreach_list)

    print("\n--- ASSERTIONS ---")
    assert len(matches) == 1
    match = matches[0]
    assert match["unique_id"] == "U1"
    assert match["city"] == "Dallas"
    assert match["country"] == "United States"
    assert match["type"] == "EQ"
    assert match["asset_type"] == "personnel"

    assert outreach_list == [["U1", "EQ"]]
