from __future__ import annotations

import math


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Independent haversine implementation (miles)."""
    r_km = 6371.0088
    km_to_miles = 0.621371

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r_km * c * km_to_miles


def test_coordinate_analysis_real_returns_top5_and_required_keys(core_mod, impact_data_real):
    # Near one of the Ports points in getimpact-4.json (Aleutians / Wake Island entry)
    asset_coords = (52.0, 177.0)

    result = core_mod._coordinate_analysis(asset_coords, impact_data_real, top_n=5)
    nearest = result.get("nearest")

    print("\n[TEST] Nearest disaster candidates:")
    for i, c in enumerate(nearest, start=1):
        print(
            f"{i}. event_id={c['event_id']} "
            f"alias={c['alias']} "
            f"lat={c['latitude']:.6f} "
            f"lon={c['longitude']:.6f} "
            f"dist_mi={c['distance_miles']:.3f}"
        )

    assert isinstance(nearest, list)
    assert len(nearest) == 5

    required = {"event_id", "alias", "latitude", "longitude", "distance_miles"}
    for item in nearest:
        assert required.issubset(item.keys())
        assert isinstance(item["event_id"], str)
        assert isinstance(item["alias"], str)
        assert isinstance(item["latitude"], float)
        assert isinstance(item["longitude"], float)
        assert isinstance(item["distance_miles"], float)
        assert item["distance_miles"] >= 0

    # Ordering: nearest -> farthest, with deterministic secondary keys.
    distances = [x["distance_miles"] for x in nearest]
    assert distances == sorted(distances)

    # Spot-check distance math for the first returned coordinate using independent haversine.
    first = nearest[0]
    expected = _haversine_miles(asset_coords[0], asset_coords[1], first["latitude"], first["longitude"])
    # Absolute tolerance: core.py may use a slightly different earth-radius constant.
    assert abs(first["distance_miles"] - expected) <= 1e-2
