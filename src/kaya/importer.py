"""Import timestamped bouldering logs from a Kaya CSV export."""

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import Config
from .database import EXPORT_FIELDS, KayaDatabase

EXPORT_PATTERN = "KAYA-Export-*.csv"
EXPORT_COLUMNS = frozenset(("date", *EXPORT_FIELDS))


class KayaImporter:
    def __init__(self, db=None):
        self.db = db or KayaDatabase()

    @staticmethod
    def find_export():
        """Select the latest timestamped export in the files directory."""
        return max(
            (path for path in Config.FILES_DIR.glob(EXPORT_PATTERN) if path.is_file()),
            key=lambda path: path.name,
            default=None,
        )

    def sync(self, csv_path: str | Path) -> int:
        timezone = ZoneInfo(Config.KAYA_TIMEZONE)
        rows = []
        with Path(csv_path).open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file, strict=True)
            headers = reader.fieldnames or []
            if not EXPORT_COLUMNS.issubset(headers) or len(headers) != len(set(headers)):
                raise ValueError("Kaya CSV is missing required columns or has duplicate headers.")

            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"Kaya CSV has the wrong number of fields on line {reader.line_num}.")
                try:
                    timestamp = datetime.strptime(
                        row["date"].split(" (", 1)[0], "%a %b %d %Y %H:%M:%S GMT%z"
                    )
                except ValueError as error:
                    raise ValueError(f"Kaya CSV has an invalid date on line {reader.line_num}.") from error
                if not row["ascent_type"].strip():
                    raise ValueError(f"Kaya CSV is missing an ascent type on line {reader.line_num}.")
                row["logged_at"] = timestamp.isoformat()
                row["local_date"] = timestamp.astimezone(timezone).date().isoformat()
                rows.append(row)

        if not rows:
            raise ValueError("Kaya CSV contains no climbs.")

        return self.db.add_climbs(rows)
