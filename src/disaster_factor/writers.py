# src/disaster_factor/writers.py

"""
Output writers for the RAID pipeline.

Each writer implements two methods:
  - write_affected(rows, output_dir)
  - write_prelim(rows, output_dir)

Add a new format by writing a class with those two methods
and registering it in the WRITERS dict at the bottom of this file.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field definitions (shared across writers)
# ---------------------------------------------------------------------------

AFFECTED_FIELDS: list[str] = [
    "unique_id",
    "city",
    "country",
    "event_type",
    "event_id",
    "impact_method",
    "coordinates",
]

PRELIM_FIELDS: list[str] = [*AFFECTED_FIELDS, "severity"]


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

class CsvWriter:
    """Writes affected and prelim data as CSV/JSON files."""

    def write_affected(self, rows: list[dict[str, str]], output_dir: Path) -> None:
        path = output_dir / "affected.csv"
        self._write_csv(path, rows, AFFECTED_FIELDS)
        logger.info("[CSV] wrote %s (%d rows)", path, len(rows))

    def write_prelim(self, rows: list[dict[str, str]], output_dir: Path) -> None:
        path = output_dir / "prelim.csv"
        self._write_csv(path, rows, PRELIM_FIELDS)
        logger.info("[CSV] wrote %s (%d rows)", path, len(rows))

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, str]], fallback_fields: list[str]) -> None:
        fieldnames = list(rows[0].keys()) if rows else fallback_fields
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)


# ---------------------------------------------------------------------------
# JSON writer
# ---------------------------------------------------------------------------

class JsonWriter:
    """Writes all output as JSON files."""

    def write_affected(self, rows: list[dict[str, str]], output_dir: Path) -> None:
        path = output_dir / "affected.json"
        self._write_json(path, rows)
        logger.info("[JSON] wrote %s (%d rows)", path, len(rows))

    def write_prelim(self, rows: list[dict[str, str]], output_dir: Path) -> None:
        path = output_dir / "prelim.json"
        self._write_json(path, rows)
        logger.info("[JSON] wrote %s (%d rows)", path, len(rows))

    """Writes point data as JSON file, until it becomes irrelevant."""
    def write_points(self, points: list[dict[str, Any]], output_dir: Path) -> None:
        path = output_dir / "points.json"
        self._write_json(path, {"points": points})
        logger.info("[JSON] wrote %s (%d points)", path, len(points))

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, indent=2)
            f.write("\n")


# ---------------------------------------------------------------------------
# XLSX writer (placeholder)
# ---------------------------------------------------------------------------

class XlsxWriter:
    """Writes output as an Excel workbook. Not yet implemented."""

    def write_affected(self, rows: list[dict[str, str]], output_dir: Path) -> None:
        raise NotImplementedError("XlsxWriter.write_affected not yet implemented")

    def write_prelim(self, rows: list[dict[str, str]], output_dir: Path) -> None:
        raise NotImplementedError("XlsxWriter.write_prelim not yet implemented")


# ---------------------------------------------------------------------------
# PDF writer (placeholder)
# ---------------------------------------------------------------------------

class PdfWriter:
    """Writes output as a formatted PDF report. Not yet implemented."""

    def write_affected(self, rows: list[dict[str, str]], output_dir: Path) -> None:
        raise NotImplementedError("PdfWriter.write_affected not yet implemented")

    def write_prelim(self, rows: list[dict[str, str]], output_dir: Path) -> None:
        raise NotImplementedError("PdfWriter.write_prelim not yet implemented")


# ---------------------------------------------------------------------------
# Registry — map format strings to writer classes
# ---------------------------------------------------------------------------

WRITERS: dict[str, type] = {
    "csv": CsvWriter,
    "json": JsonWriter,
    "xlsx": XlsxWriter,
    "pdf": PdfWriter,
}
