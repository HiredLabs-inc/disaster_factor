# tests/test_core_generate_impact_report.py

import csv
from disaster_factor import core


def test_generate_impact_report_writes_csv_and_respects_debug(monkeypatch, tmp_path):
    """
    generate_impact_report should always:
      - write affected.csv with the outreach rows

    And:
      - NOT call serve_static_and_open when debug=True
      - CALL serve_static_and_open once when debug=False
    """

    # --- SETUP: fake filesystem + fake web server helper ---

    # Work in a temporary directory so affected.csv doesn't pollute the project root
    monkeypatch.chdir(tmp_path)
    print("\n--- SETUP: current working directory set to tmp_path ---")
    print("cwd:", tmp_path)

    calls = []

    def fake_serve_static_and_open(*args, **kwargs):
        print("\n[FAKE serve_static_and_open CALLED]")
        print("  args:", args)
        print("  kwargs:", kwargs)
        calls.append((args, kwargs))

    # Patch the helper that generate_impact_report imports/uses
    monkeypatch.setattr(core, "serve_static_and_open", fake_serve_static_and_open)

    # Minimal, but structurally valid, match + outreach data
    matches = [
        {
            "unique_id": "U1",
            "city": "Dallas",
            "country": "United States",
            "type": "EQ",
            "asset_type": "personnel",
        }
    ]
    outreach_list = [["U1", "EQ"]]
    total_red = 1

    # --- CASE 1: debug=True -> no web UI, but CSV written ---

    print("\n--- CALL: generate_impact_report(debug=True) ---")
    core.generate_impact_report(
        matches=matches,
        outreach_list=outreach_list,
        total_red=total_red,
        debug=True,
    )

    print("\n--- AFTER debug=True CALL ---")
    print("serve_static_and_open calls:", calls)

    # No UI launch in debug mode
    assert calls == []

    # affected.csv should exist and contain our outreach row
    csv_path = tmp_path / "affected.csv"
    assert csv_path.exists()

    content = csv_path.read_text(encoding="utf-8")
    print("\naffected.csv contents after debug=True call:\n", content)

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    # Header + 1 outreach row
    assert rows[0] == ["unique_id", "disaster_type"]
    assert rows[1] == ["U1", "EQ"]

    # --- CASE 2: debug=False -> web UI should be launched once, CSV rewritten ---

    calls.clear()
    print("\n--- CALL: generate_impact_report(debug=False) ---")
    core.generate_impact_report(
        matches=matches,
        outreach_list=outreach_list,
        total_red=total_red,
        debug=False,
    )

    print("\n--- AFTER debug=False CALL ---")
    print("serve_static_and_open calls:", calls)

    # Now we expect exactly one UI launch
    assert len(calls) == 1

    # affected.csv should still exist (rewritten with same contents in this test)
    assert csv_path.exists()
    content2 = csv_path.read_text(encoding="utf-8")
    print("\naffected.csv contents after debug=False call:\n", content2)

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows2 = list(reader)

    assert rows2[0] == ["unique_id", "disaster_type"]
    assert rows2[1] == ["U1", "EQ"]
