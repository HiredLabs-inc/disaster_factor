# tests/test_core_load_company_assets.py

from disaster_factor import core


def test_load_company_assets_reads_assets_csv(monkeypatch, tmp_path):
    """
    Given a small fake assets.csv file in the working directory,
    load_company_assets should:
      - read all rows
      - build assets_by_id with the expected structure
      - leave cities / countries as empty dicts (for now)
    """

    # --- SETUP: write a fake assets.csv into a temporary directory ---
    csv_text = (
        "asset_id,city,country,type,owner\n"
        "A1,Dallas,United States,personnel,Acme Corp\n"
        "A2,Houston,United States,building,Acme Corp\n"
    )

    assets_file = tmp_path / "assets.csv"
    assets_file.write_text(csv_text, encoding="utf-8")

    # Make the temp directory the current working dir so core.load_company_assets()
    # will find our fake assets.csv when it does open("assets.csv", ...).
    monkeypatch.chdir(tmp_path)

    print("\n--- SETUP: wrote assets.csv at", assets_file, "---")
    print(assets_file.read_text())

    # --- ACT: call the helper under test ---
    cities, countries, assets_by_id = core.load_company_assets()

    print("\n--- OUTPUT FROM load_company_assets ---")
    print("cities:", cities)
    print("countries:", countries)
    print("assets_by_id:", assets_by_id)

    # --- ASSERT: basic structure is correct ---

    # For now, the helper does not populate these lookups.
    assert cities == {}
    assert countries == {}

    # We should have two assets keyed by their asset_id
    assert set(assets_by_id.keys()) == {"A1", "A2"}

    a1 = assets_by_id["A1"]
    assert a1["unique_id"] == "A1"
    assert a1["city"] == "Dallas"
    assert a1["country"] == "United States"
    assert a1["type"] == "personnel"
    # Extra columns (like 'owner') should be preserved too
    assert a1["owner"] == "Acme Corp"

    a2 = assets_by_id["A2"]
    assert a2["unique_id"] == "A2"
    assert a2["city"] == "Houston"
    assert a2["country"] == "United States"
    assert a2["type"] == "building"
    assert a2["owner"] == "Acme Corp"
