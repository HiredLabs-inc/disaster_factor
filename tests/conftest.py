from __future__ import annotations

import json
import importlib
import importlib.util
from pathlib import Path
from typing import Any, Dict

import pytest

# Ensure repo root is on sys.path (needed when tests/ is executed directly).
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DATA_DIR = Path(__file__).parent / "data"


def _load_core_module():
    """Import disaster_factor.core if available; else load /mnt/data/core.py for sandbox runs."""
    try:
        return importlib.import_module("disaster_factor.core")
    except Exception:
        # Fallback for this sandbox where core.py is mounted directly.
        core_path = Path("/mnt/data/core.py")
        spec = importlib.util.spec_from_file_location("core", core_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load core module from {core_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        return mod


@pytest.fixture(scope="session")
def core_mod():
    return _load_core_module()


@pytest.fixture(scope="session")
def load_impact_json() -> Any:
    def _loader(filename: str) -> Dict[str, Any]:
        path = DATA_DIR / filename
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return _loader


@pytest.fixture(scope="session")
def impact_data_real(load_impact_json):
    """Four real GDACS per-event impact_json files, shaped as recon() would store them."""
    files = [
        ("E1", "getimpact-1.json"),
        ("E2", "getimpact-2.json"),
        ("E3", "getimpact-3.json"),
        ("E4", "getimpact-4.json"),
    ]
    out = {}
    for event_id, fname in files:
        out[event_id] = {
            "impact_json": load_impact_json(fname),
            "eventtype": "unknown",
            "coordinates": None,
        }
    return out
