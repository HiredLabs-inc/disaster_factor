# tests/test_core_track_disasters.py

from disaster_factor import core


def test_track_disasters_wires_helpers_and_passes_debug(monkeypatch, tmp_path):
    """
    Orchestrator test for track_disasters.

    We fake out all the helpers so we can assert that:
      - recon is called once and its outputs are passed onward
      - assets is called once and its outputs are passed onward
      - intel receives disasters + assets and returns matches/outreach
      - disseminate receives the matches, outreach, total_red, and debug flag

    This test uses debug=True so no real web UI is started.
    """

    # Work in a temp directory to keep any accidental file writes sandboxed
    monkeypatch.chdir(tmp_path)
    print("\n--- SETUP: cwd set to tmp_path for track_disasters ---")
    print("cwd:", tmp_path)

    # --- Fake data that flows through the pipeline ---

    fake_disasters = {
        1: {"city": "Dallas", "country": "United States", "type": "EQ"}
    }
    fake_total_red = 1

    fake_cities = {}
    fake_countries = {}
    fake_assets_by_id = {
        "A1": {
            "unique_id": "U1",
            "city": "Dallas",
            "country": "United States",
            "type": "personnel",
        }
    }

    fake_matches = [
        {
            "unique_id": "U1",
            "city": "Dallas",
            "country": "United States",
            "type": "EQ",
            "asset_type": "personnel",
        }
    ]
    fake_outreach = [["U1", "EQ"]]

    # --- Monkeypatch helpers in core.py ---

    def fake_recon():
        print("\n[fake_recon CALLED]")
        return fake_disasters, fake_total_red

    def fake_assets():
        print("\n[fake_assets CALLED]")
        return fake_cities, fake_countries, fake_assets_by_id

    identify_calls: list[tuple[dict, dict, dict, dict]] = []

    def fake_intel(disasters, cities, countries, assets_by_id):
        print("\n[fake_intel CALLED]")
        print("  disasters:", disasters)
        print("  cities:", cities)
        print("  countries:", countries)
        print("  assets_by_id:", assets_by_id)
        identify_calls.append((disasters, cities, countries, assets_by_id))
        return fake_matches, fake_outreach

    report_calls: list[dict] = []

    def fake_disseminate(matches, outreach_list, total_red, debug=False):
        print("\n[fake_disseminate CALLED]")
        print("  matches:", matches)
        print("  outreach_list:", outreach_list)
        print("  total_red:", total_red)
        print("  debug:", debug)
        report_calls.append(
            {
                "matches": matches,
                "outreach_list": outreach_list,
                "total_red": total_red,
                "debug": debug,
            }
        )

    monkeypatch.setattr(core, "recon", fake_recon)
    monkeypatch.setattr(core, "assets", fake_assets)
    monkeypatch.setattr(core, "intel", fake_intel)
    monkeypatch.setattr(core, "disseminate", fake_disseminate)

    # --- ACT: call the orchestrator with debug=True ---

    print("\n--- CALL: track_disasters(debug=True) ---")
    core.track_disasters(debug=True)

    # --- ASSERT: verify wiring ---

    # intel should have been called exactly once
    assert len(identify_calls) == 1
    (d_arg, c_arg, cn_arg, a_arg) = identify_calls[0]
    assert d_arg is fake_disasters
    assert c_arg is fake_cities
    assert cn_arg is fake_countries
    assert a_arg is fake_assets_by_id

    # disseminate should have been called exactly once
    assert len(report_calls) == 1
    call = report_calls[0]
    assert call["matches"] is fake_matches
    assert call["outreach_list"] is fake_outreach
    assert call["total_red"] == fake_total_red
    # Most important: debug flag is passed through unchanged
    assert call["debug"] is True
