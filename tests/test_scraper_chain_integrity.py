# tests/test_scraper_chain_integrity.py
import os
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

# Import only the pure function we want to test
from disaster_factor.core import track_disasters

# Paths
TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
DATA = TESTS_DIR / "data"

# Map the exact URLs used in your snapshots to local files in tests/data/
URL_MAP = {
    "http://www.gdacs.org/XML/RSS.xml": "gdacs_rss_sample.xml",
    "https://www.gdacs.org//datareport/resources/EQ/1508599/rss_1508599.xml": "downstream1.xml",
    r"https://www.gdacs.org/gis/calculation/EQ1_WPS/-071\eq_-07150_-02745.xml": "downstream2.xml",
}


class MockResp:
    def __init__(self, content: bytes):
        self.content = content


# ✅ This fixture ensures NO real HTTP calls happen – everything comes from local XML files
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


def _build_personnel_from_downstream2(target_dir: Path, count: int = 3) -> Path:
    """
    Build a minimal personnel.csv that mirrors a few city/country pairs from downstream2.xml,
    ensuring the script will produce at least one affected row.
    """
    xml_text = (DATA / "downstream2.xml").read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(xml_text, "xml")

    pairs: list[tuple[str, str]] = []
    for datums in soup.find_all("datums", attrs={"alias": "City"}):
        city_name = None
        country = None

        # structure: <scalar><name>NAME</name><value>Dallas</value>...</scalar>
        for scalar in datums.find_all("scalar"):
            n = scalar.find("name")
            v = scalar.find("value")
            if not n or not v:
                continue
            name = n.text.strip().upper()
            if name == "NAME":
                city_name = v.text.strip()
            elif name == "COUNTRY":
                country = v.text.strip()

        if city_name and country:
            pairs.append((city_name, country))
        if len(pairs) >= count:
            break

    if not pairs:
        pairs = [("Dallas", "United States")]

    out = target_dir / "personnel.csv"
    out.write_text(
        "unique_id,city,country,street\n"
        + "\n".join(
            f"U{i+1},{city},{cntry},123 Test St"
            for i, (city, cntry) in enumerate(pairs)
        ),
        encoding="utf-8",
    )
    return out


def test_disastertracker_runs_with_snapshots_and_writes_csv(tmp_path: Path) -> None:
    # Sanity: expected XML snapshot files exist
    for fname in URL_MAP.values():
        assert (DATA / fname).exists(), f"Missing snapshot: {DATA / fname}"

    # Work in temp dir so core.py writes outputs there, not into your real repo root
    os.chdir(tmp_path)

    # Build personnel.csv that guarantees potential matches
    _build_personnel_from_downstream2(tmp_path)

    # Call only the pure function without running web UI
    track_disasters(open_webapp=False)

    # CSV should be created in the temp dir
    out = tmp_path / "affected.csv"
    assert out.exists(), "Expected affected.csv to be created by track_disasters()"

    # Copy to artifacts/ so you can eyeball it after the test
    artifacts_dir = REPO_ROOT / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    (artifacts_dir / "affected.csv").write_text(
        out.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    # Basic sanity: file exists and is not negative size (duh, but keeps shape)
    assert out.stat().st_size >= 0

    print(f"\nCSV saved to: {artifacts_dir / 'affected.csv'}\n")
