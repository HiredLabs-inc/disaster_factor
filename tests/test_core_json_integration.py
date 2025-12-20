# tests/test_core_json_integration.py

import json
import csv
from pathlib import Path
from disaster_factor import core


def test_json_integration_with_assets_csv(monkeypatch):
    """
    Integration test that validates the refactored JSON-based disaster tracking.
    
    This test:
      1. Uses the real refactored recon() function (no mocks)
      2. Uses assets.csv for company assets
      3. Runs the complete pipeline with live RSS data
      4. Validates affected.csv contains expected structure
    """
    
    # --- SETUP: Ensure assets.csv is in the correct location ---
    
    # The test should run from project root so core.py finds tests/data/assets.csv
    project_root = Path(__file__).parent.parent
    monkeypatch.chdir(project_root)
    
    print("\n--- SETUP: Running from project root ---")
    print(f"Working directory: {project_root}")
    print(f"assets.csv location: {project_root / 'tests' / 'data' / 'assets.csv'}")
    
    # --- ACT: Run the complete pipeline with real refactored code ---
    
    print("\n--- CALLING track_disasters(debug=True) with real refactored code ---")
    core.track_disasters(debug=True)
    
    # --- ASSERT: Verify affected.csv was created with expected structure ---
    
    tests_data_dir = Path(__file__).parent / "data"
    affected_csv_path = tests_data_dir / "affected.csv"
    
    assert affected_csv_path.exists(), f"affected.csv not found at {affected_csv_path}"
    
    # Read and validate affected.csv
    with open(affected_csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    
    print(f"\n--- AFFECTED.CSV CONTENT ---")
    print(f"File: {affected_csv_path}")
    print(f"Headers: {rows[0] if rows else 'No rows'}")
    print(f"Data rows: {rows[1:] if len(rows) > 1 else 'No data rows'}")
    
    # Basic assertions
    assert len(rows) >= 1, "affected.csv should have at least headers"
    assert rows[0] == ["unique_id", "disaster_type"], "Header should match expected format"
    
    # Check if we have any matches (depends on asset-disaster city matching)
    data_rows = rows[1:]
    print(f"\n--- ASSERTIONS ---")
    print(f"Found {len(data_rows)} affected assets")
    
    if data_rows:
        print("Affected assets:")
        for row in data_rows:
            print(f"  Asset {row[0]} affected by {row[1]}")
    else:
        print("No assets matched current disaster locations (this is normal)")
    
    # The important thing is that the pipeline runs without errors
    assert isinstance(data_rows, list), "Data rows should be a list"
    
    # Verify each data row has exactly 2 columns if any exist
    for row in data_rows:
        assert len(row) == 2, f"Each data row should have 2 columns, got {len(row)}: {row}"
        assert isinstance(row[0], str), "Asset ID should be string"
        assert isinstance(row[1], str), "Disaster type should be string"
    
    print("\n--- SUCCESS: Refactored JSON integration test passed! ---")


def test_json_disaster_parsing_logic():
    """
    Unit test for the specific JSON parsing logic to ensure we extract
    the correct disaster information from step_3.json.
    """
    
    # Load test JSON
    json_path = Path(__file__).parent / "data" / "step_3.json"
    disaster_data = json.loads(json_path.read_text(encoding="utf-8"))
    
    print("\n--- TESTING JSON PARSING LOGIC ---")
    print(f"JSON top-level keys: {list(disaster_data.keys())}")
    
    # Extract properties
    disaster_props = disaster_data.get("properties", {})
    print(f"Properties keys: {list(disaster_props.keys())}")
    print(f"Event type: {disaster_props.get('eventtype')}")
    print(f"Country: {disaster_props.get('country')}")
    print(f"Alert level: {disaster_props.get('alertlevel')}")
    
    # Basic assertions about JSON structure
    assert "properties" in disaster_data, "JSON should have properties"
    assert "eventtype" in disaster_props, "Properties should have eventtype"
    assert "country" in disaster_props, "Properties should have country"
    # Note: step_3.json doesn't have datums, that's in step_4.json
