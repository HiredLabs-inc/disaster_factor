import json
from pathlib import Path

from disaster_factor import core


def test_static_map_config_and_points_are_split_contract() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    points_path = repo_root / "src" / "disaster_factor" / "static" / "points.json"
    config_path = repo_root / "src" / "disaster_factor" / "static" / "map_config.json"

    points_data = json.loads(points_path.read_text(encoding="utf-8"))
    config_data = json.loads(config_path.read_text(encoding="utf-8"))

    assert "config" not in points_data
    assert isinstance(points_data.get("points"), list)
    assert all(point.get("severity") == "red" for point in points_data["points"])

    assert set(("lat_t", "lat_b", "lon_c")).issubset(config_data.keys())


def test_write_points_json_writes_points_key_only(tmp_path: Path) -> None:
    points = [{"lat": 10.0, "lon": 20.0, "label": "X", "severity": "red"}]
    out = tmp_path / "points.json"

    core._write_points_json(out, points)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert list(data.keys()) == ["points"]
    assert data["points"] == points
