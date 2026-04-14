import csv
from pathlib import Path

from disaster_factor import core


def _sample_red_match() -> dict[str, str]:
    return {
        "unique_id": "AST001",
        "city": "Sendai",
        "country": "Japan",
        "event_type": "FL",
        "event_id": "E-RED",
        "impact_method": "EUCLIDEAN",
        "coordinates": "1.0000, 1.0000",
    }


def test_write_csv_rows_uses_fallback_header_with_empty_rows(tmp_path: Path) -> None:
    path = tmp_path / "prelim.csv"
    fieldnames = [
        "unique_id",
        "city",
        "country",
        "event_type",
        "event_id",
        "impact_method",
        "coordinates",
        "severity",
    ]

    core._write_csv_rows(path, [], fieldnames)

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
    assert header == fieldnames


def test_disseminate_routes_red_prelim_and_points_outputs(monkeypatch) -> None:
    red_matches = [_sample_red_match()]
    prelim_matches = [{**_sample_red_match(), "severity": "red"}]
    red_points = [{"lat": 1.0, "lon": 1.0, "label": "Sendai, Japan", "severity": "red"}]

    csv_calls: list[tuple[Path, list[dict[str, str]], list[str]]] = []
    points_calls: list[tuple[Path, list[dict[str, object]]]] = []
    served = {"called": False}

    def _fake_write_csv(path: Path, rows: list[dict[str, str]], fallback: list[str]) -> None:
        csv_calls.append((path, rows, fallback))

    def _fake_write_points(path: Path, points: list[dict[str, object]]) -> None:
        points_calls.append((path, points))

    def _fake_serve() -> None:
        served["called"] = True

    monkeypatch.setattr(core, "_write_csv_rows", _fake_write_csv)
    monkeypatch.setattr(core, "_write_points_json", _fake_write_points)
    monkeypatch.setattr(core, "serve_static_and_open", _fake_serve)

    core.disseminate(red_matches, prelim_matches, red_points, total_red=1, debug=True)

    assert served["called"] is False
    assert len(csv_calls) == 2
    assert csv_calls[0][0].name == "affected.csv"
    assert csv_calls[0][1] == red_matches
    assert csv_calls[1][0].name == "prelim.csv"
    assert csv_calls[1][1] == prelim_matches
    assert csv_calls[1][2][-1] == "severity"

    assert len(points_calls) == 1
    assert points_calls[0][0].name == "points.json"
    assert points_calls[0][1] == red_points
