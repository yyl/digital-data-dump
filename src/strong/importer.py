"""Strong CSV importer with auto-discovery."""

import csv
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from collections import defaultdict

from ..config import Config
from ..time_utils import utc_now_iso
from .database import StrongDatabase


def parse_duration(duration_str: str) -> int:
    """Parse a duration string like '1h 5m', '55m', '2m' into minutes.
    
    Args:
        duration_str: Human-readable duration string.
        
    Returns:
        Duration in minutes (integer).
    """
    if not duration_str:
        return 0
    
    total = 0
    hours = re.search(r'(\d+)\s*h', duration_str)
    minutes = re.search(r'(\d+)\s*m', duration_str)
    
    if hours:
        total += int(hours.group(1)) * 60
    if minutes:
        total += int(minutes.group(1))
    
    return total


class StrongImporter:
    """Imports Strong workout data from CSV export files."""
    
    def __init__(self, db: Optional[StrongDatabase] = None):
        """Initialize importer."""
        self.db = db or StrongDatabase()
    
    @staticmethod
    def find_latest_export() -> Optional[Path]:
        """Find the latest Strong CSV export in files/.
        
        Scans for files matching 'strong_workouts*.csv' and returns
        the one with the latest modification time.
        """
        files_dir = Config.FILES_DIR
        if not files_dir.exists():
            return None
        
        csv_files = sorted(
            files_dir.glob("strong_workouts*.csv"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        return csv_files[0] if csv_files else None
    
    def import_from_file(self, csv_path: Path, *, replace: bool = False) -> Dict[str, int]:
        """Import all workout data from a Strong CSV export.
        
        Args:
            csv_path: Path to strong_workouts.csv
            
        Returns:
            Dictionary with import counts
        """
        stats = {"workouts": 0, "exercises": 0}
        
        # Initialize database
        self.db.init_tables()
        
        # Read CSV and group rows by workout (same Date = same workout)
        workouts: Dict[str, Dict[str, Any]] = {}
        exercises: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip Rest Timer rows
                if row.get("Set Order", "").strip() == "Rest Timer":
                    continue
                
                workout_id = row["Date"]
                
                # Build workout entry (first time we see this Date)
                if workout_id not in workouts:
                    workouts[workout_id] = {
                        "id": workout_id,
                        "workout_name": row.get("Workout Name", ""),
                        "started_at": workout_id,
                        "duration_minutes": parse_duration(row.get("Duration", "")),
                        "notes": row.get("Workout Notes") or None,
                    }
                
                # Build exercise entry
                set_order = row.get("Set Order", "0")
                try:
                    set_order_int = int(set_order)
                except ValueError:
                    continue  # Skip any non-numeric, non-Rest Timer rows
                
                exercise = {
                    "exercise_name": row.get("Exercise Name", ""),
                    "set_order": set_order_int,
                    "weight": float(row["Weight"]) if row.get("Weight") else 0,
                    "reps": float(row["Reps"]) if row.get("Reps") else 0,
                    "distance": float(row["Distance"]) if row.get("Distance") else 0,
                    "seconds": float(row["Seconds"]) if row.get("Seconds") else 0,
                    "notes": row.get("Notes") or None,
                    "rpe": float(row["RPE"]) if row.get("RPE") else None,
                }
                exercises[workout_id].append(exercise)
        
        # Upsert workouts and their exercises
        saved_stats = self.db.save_workouts(workouts, exercises, snapshot={
            "source": "csv", "last_successful_sync_at": utc_now_iso(),
        } if replace else None)
        stats["workouts"] = saved_stats["workouts"]
        stats["exercises"] = saved_stats["exercises"]
        
        return stats
    
    def sync(self) -> Dict[str, int]:
        """Auto-discover latest export and import it.
        
        Returns:
            Dictionary with import counts
        """
        csv_file = self.find_latest_export()
        if not csv_file:
            print("Error: No Strong CSV file found in files/")
            print("  Expected: files/strong_workouts*.csv")
            return {"workouts": 0, "exercises": 0}
        
        print(f"Found export: {csv_file.name}")
        stats = self.import_from_file(csv_file)
        print(f"Imported {stats['workouts']} workouts, {stats['exercises']} exercise sets")
        return stats
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        try:
            self.db.init_tables()
            return {
                "database_stats": self.db.get_stats(),
                "latest_export": self.find_latest_export()
            }
        except Exception as e:
            return {"error": str(e)}
