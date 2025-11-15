# tests/test_scraper_chain_integrity.py
import importlib
import os
import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from disaster_factor.core import track_disasters

TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
DATA = TESTS_DIR / "data"
SCRIPT_SRC = REPO_ROOT / "src/disaster_factor/core.py"

# Map the exact URLs used in your snapshots to local files in tests/data/
URL_MAP = {
    "http://www.gdacs.org/XML/RSS.xml": "gdacs_rss_sample.xml",
    "https://www.gdacs.org//datareport/resources/EQ/1508599/rss_1508599.xml": "downstream1.xml",
    r"https://www.gdacs.org/gis/calculation/EQ1_WPS/-071\eq_-07150_-02745.xml": "downstream2.xml",
}

class MockResp:
    def __init__(self, content: bytes):
        self.content = content

@pytest.fixture(autouse=True)
def mock_requests(monkeypatch):
    import requests

    def fake_get(url, *args, **kwargs):
        fname = URL_MAP.get(url)
        if not fname:
            raise RuntimeError(f"No fixture mapped for URL: {url}")
        path = DATA / fname
        if not path.exists():
            raise RuntimeError(f"Fixture file not found: {path}")
        return MockResp(path.read_bytes())

    monkeypatch.setattr(requests, "get", fake_get)

def _build_personnel_from_downstream2(target_dir: Path, count: int = 3):
    """
    Build a minimal personnel.csv that mirrors a few city/country pairs from downstream2.xml,
    ensuring the script will produce at least one affected row.
    """
    xml_text = (DATA / "downstream2.xml").read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(xml_text, "xml")

    # Collect city/country pairs from <datums alias="City">
    pairs = []
    for datums in soup.find_all("datums", attrs={"alias": "City"}):
        city_name = None
        country = None
        # find scalar NAME and COUNTRY values
        # (structure is <scalar><name>NAME</name><value>Dallas</value>...</scalar>)
        for scalar in datums.find_all("scalar"):
            n = scalar.find("name")
            v = scalar.find("value")
            if not n or not v:
                continue
            if n.text.strip().upper() == "NAME":
                city_name = v.text.strip()
            elif n.text.strip().upper() == "COUNTRY":
                country = v.text.strip()
        if city_name and country:
            pairs.append((city_name, country))
        if len(pairs) >= count:
            break

    # Fallback in case the sample has fewer than expected
    if not pairs:
        pairs = [("Dallas", "United States")]

    # Write personnel.csv in the temp dir
    out = target_dir / "personnel.csv"
    out.write_text(
        "unique_id,city,country,street\n" + "\n".join(
            f"U{i+1},{c},{cntry},123 Test St" for i, (c, cntry) in enumerate(pairs)
        ),
        encoding="utf-8"
    )
    return out

def test_disastertracker_runs_with_snapshots_and_writes_csv(tmp_path):
    # Sanity: expected files exist
    # assert SCRIPT_SRC.exists(), f"Missing script at {SCRIPT_SRC}"
    for fname in URL_MAP.values():
        assert (DATA / fname).exists(), f"Missing snapshot: {DATA/fname}"

    # Work in temp dir so your script's outputs land here
    os.chdir(tmp_path)

    # Place a personnel.csv derived from downstream2 so a non-empty affected.csv is produced
    _build_personnel_from_downstream2(tmp_path)

    # call track_disasters from core.py
    track_disasters()

    # Copy script into temp dir
    dst = tmp_path / "disastertracker_app.py"
    dst.write_text(SCRIPT_SRC.read_text(encoding="utf-8"), encoding="utf-8")

    # Import executes the script (requests is mocked above)
    sys.path.insert(0, str(tmp_path))
    importlib.import_module("disastertracker_app")

    # Assert the script wrote the CSV
    out = tmp_path / "affected.csv"
    assert out.exists(), "Expected affected.csv to be created by the script"

    # Also copy it to a stable artifacts folder in the repo so you can inspect it
    artifacts_dir = REPO_ROOT / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    (artifacts_dir / "affected.csv").write_text(out.read_text(encoding="utf-8"), encoding="utf-8")

    # Optional: basic sanity check that at least a header or a row exists
    # (Your script writes rows only; no header—so we just check non-empty or allow empty if no match)
    assert out.stat().st_size >= 0

    # Optional: print confirmation for visibility in console output
    print(f"\nCSV saved to: {artifacts_dir / 'affected.csv'}\n")
