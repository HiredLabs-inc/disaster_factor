# add an intel() spy to your existing integration test
#
#   - A spy wrapper around core.intel(...) that prints:
#       * number of disasters
#       * a small sample of disaster (city, country, type)
#       * number of assets
#       * a small sample of asset (city, country, type, unique_id)

import csv
from pathlib import Path

from disaster_factor import core


def _sample_items(seq, n=5):
    """Return up to n items from a list/iterable as a list."""
    return list(seq)[:n]


def test_json_integration_with_assets_csv(monkeypatch):
    """
    Integration test that reflects the filesystem layout you want:

      - assets.csv lives in: tests/data/assets.csv
      - affected.csv should be written to: tests/data/affected.csv

    Runs the full pipeline via core.track_disasters(debug=True) and verifies:
      - affected.csv exists
      - header structure is correct

    Also spies on:
      - core.intel      (to print disasters/assets samples + match counts)
      - core.disseminate (to print final report counts + ensure file writes)
    """

    # --- SETUP: run from tests/data so open("assets.csv") + open("affected.csv") resolve there ---
    tests_data_dir = Path(__file__).parent / "data"
    monkeypatch.chdir(tests_data_dir)

    assets_csv_path = tests_data_dir / "assets.csv"
    affected_csv_path = tests_data_dir / "affected.csv"

    print("\n--- SETUP: Running from tests/data ---")
    print(f"Working directory: {tests_data_dir}")
    print(f"assets.csv location: {assets_csv_path}")

    assert assets_csv_path.exists(), f"assets.csv not found at {assets_csv_path}"

    # Ensure fresh output
    if affected_csv_path.exists():
        print("\n--- CLEANUP: removing existing affected.csv ---")
        affected_csv_path.unlink()

    # --- Spy on intel (this is where matching happens) ---
    original_intel = core.intel
    intel_calls = []

    def spy_intel(disasters, cities, countries, assets_by_id):
        print("\n--- SPY: intel called ---")
        print("disasters count:", len(disasters))
        print("assets count:", len(assets_by_id))

        # Show a small sample of disasters (city/country/type)
        disaster_samples = []
        for d in _sample_items(disasters.values(), n=10):
            disaster_samples.append((d.get("city"), d.get("country"), d.get("type")))
        print("disaster samples (city, country, type):", disaster_samples)

        # Show a small sample of assets (unique_id/city/country/type)
        asset_samples = []
        for a in _sample_items(assets_by_id.values(), n=10):
            asset_samples.append((a.get("unique_id"), a.get("city"), a.get("country"), a.get("type")))
        print("asset samples (unique_id, city, country, type):", asset_samples)

        matches, outreach_list = original_intel(disasters, cities, countries, assets_by_id)

        print("intel matches count:", len(matches))
        print("intel outreach rows:", len(outreach_list))

        intel_calls.append(
            {
                "disasters_count": len(disasters),
                "assets_count": len(assets_by_id),
                "matches_count": len(matches),
                "outreach_count": len(outreach_list),
            }
        )

        return matches, outreach_list

    monkeypatch.setattr(core, "intel", spy_intel)

    # --- Spy on disseminate (this function writes affected.csv in your current core.py) ---
    original_disseminate = core.disseminate
    disseminate_calls = []

    def spy_disseminate(matches, outreach_list, total_red, debug=False):
        print("\n--- SPY: disseminate called ---")
        print("matches count:", len(matches))
        print("outreach rows:", len(outreach_list))
        print("total_red:", total_red)
        print("debug:", debug)

        disseminate_calls.append(
            {
                "matches_count": len(matches),
                "outreach_count": len(outreach_list),
                "total_red": total_red,
                "debug": debug,
            }
        )

        # Call the real function so it still writes affected.csv
        return original_disseminate(matches, outreach_list, total_red, debug=debug)

    monkeypatch.setattr(core, "disseminate", spy_disseminate)

    # --- ACT: run the full pipeline ---
    print("\n--- CALLING track_disasters(debug=True) ---")
    print("\n--- DIRECT CALL: recon() DIAGNOSTIC ---")
    disasters, total_red = core.recon()
    print("recon disasters count:", len(disasters))
    print("recon total_red:", total_red)
    print("recon sample disasters:", list(disasters.values())[:5])

    core.track_disasters(debug=True)

    # --- ASSERT: spies ran ---
    assert len(intel_calls) == 1, f"Expected intel to be called once, got {len(intel_calls)}"
    assert len(disseminate_calls) == 1, f"Expected disseminate to be called once, got {len(disseminate_calls)}"

    # --- ASSERT: affected.csv should now exist in tests/data ---
    assert affected_csv_path.exists(), f"affected.csv not found at {affected_csv_path}"

    print("\n--- affected.csv contents ---")
    print(affected_csv_path.read_text(encoding="utf-8"))

    with affected_csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    assert rows, "affected.csv exists but is empty"
    assert rows[0] == ["unique_id", "disaster_type"], f"Unexpected header: {rows[0]}"

    # Rows may legitimately be empty (live feed + strict matching), but if present:
    for i, row in enumerate(rows[1:], start=1):
        assert len(row) == 2, f"Row {i} should have 2 columns [unique_id, disaster_type], got: {row}"
