from pathlib import Path
import pytest

import main
from src.apple_health.database import AppleHealthDatabase
from src.apple_health.importer import AppleHealthImporter
from src.config import Config


APPLE_HEALTH_EXPORT = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
  <ExportDate value="2026-04-05 10:00:00 -0700"/>
  <Me
    HKCharacteristicTypeIdentifierDateOfBirth="1990-01-01"
    HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale"
    HKCharacteristicTypeIdentifierBloodType="HKBloodTypeNotSet"
    HKCharacteristicTypeIdentifierFitzpatrickSkinType="HKFitzpatrickSkinTypeNotSet"
    HKCharacteristicTypeIdentifierCardioFitnessMedicationsUse="HKCardioFitnessMedicationsUseNone"
  />
  <Workout
    workoutActivityType="HKWorkoutActivityTypeRunning"
    duration="30"
    durationUnit="min"
    totalEnergyBurned="320"
    totalEnergyBurnedUnit="kcal"
    sourceName="Apple Watch"
    sourceVersion="10.0"
    device="Watch"
    creationDate="2026-04-01 07:31:00 -0700"
    startDate="2026-04-01 07:00:00 -0700"
    endDate="2026-04-01 07:30:00 -0700"
  >
    <WorkoutStatistics
      type="HKQuantityTypeIdentifierHeartRate"
      startDate="2026-04-01 07:00:00 -0700"
      endDate="2026-04-01 07:30:00 -0700"
      average="152"
      maximum="178"
      unit="count/min"
    />
    <WorkoutStatistics
      type="HKQuantityTypeIdentifierActiveEnergyBurned"
      startDate="2026-04-01 07:00:00 -0700"
      endDate="2026-04-01 07:30:00 -0700"
      sum="300"
      unit="kcal"
    />
  </Workout>
  <Workout
    workoutActivityType="HKWorkoutActivityTypeWalking"
    duration="20"
    durationUnit="min"
    sourceName="Apple Watch"
    creationDate="2026-04-02 18:21:00 -0700"
    startDate="2026-04-02 18:00:00 -0700"
    endDate="2026-04-02 18:20:00 -0700"
  />
  <Record
    type="HKQuantityTypeIdentifierHeartRate"
    unit="count/min"
    value="100"
    sourceName="Apple Watch"
    startDate="2026-04-02 18:05:00 -0700"
    endDate="2026-04-02 18:05:00 -0700"
  />
  <Record
    type="HKQuantityTypeIdentifierHeartRate"
    unit="count/min"
    value="110"
    sourceName="Apple Watch"
    startDate="2026-04-02 18:10:00 -0700"
    endDate="2026-04-02 18:10:00 -0700"
  />
  <Record
    type="HKQuantityTypeIdentifierActiveEnergyBurned"
    unit="kcal"
    value="50"
    sourceName="Apple Watch"
    startDate="2026-04-02 18:00:00 -0700"
    endDate="2026-04-02 18:20:00 -0700"
  />
  <Record
    type="HKQuantityTypeIdentifierBasalEnergyBurned"
    unit="kcal"
    value="12"
    sourceName="Apple Watch"
    startDate="2026-04-02 18:00:00 -0700"
    endDate="2026-04-02 18:20:00 -0700"
  />
</HealthData>
"""


def test_find_latest_export_prefers_newest_nested_file(tmp_path, monkeypatch):
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    root_export = files_dir / "export.xml"
    nested_dir = files_dir / "apple_health_export"
    nested_dir.mkdir()
    nested_export = nested_dir / "export.xml"

    root_export.write_text("<HealthData locale='en_US'></HealthData>", encoding="utf-8")
    nested_export.write_text("<HealthData locale='en_US'></HealthData>", encoding="utf-8")
    nested_export.touch()

    monkeypatch.setattr(Config, "FILES_DIR", files_dir)

    assert AppleHealthImporter.find_latest_export() == nested_export.resolve()


def test_importer_parses_workout_stats_and_record_fallbacks(tmp_path):
    xml_path = tmp_path / "export.xml"
    db_path = tmp_path / "apple_health.db"
    xml_path.write_text(APPLE_HEALTH_EXPORT, encoding="utf-8")

    db = AppleHealthDatabase(str(db_path))
    importer = AppleHealthImporter(db=db)

    stats = importer.import_from_file(xml_path)
    assert stats == {"workouts": 2}

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT activity_type, duration_seconds, active_calories, total_calories, avg_heart_rate, max_heart_rate
            FROM workouts
            ORDER BY started_at ASC
            """
        )
        rows = [dict(row) for row in cursor.fetchall()]

    assert rows[0]["activity_type"] == "run"
    assert rows[0]["duration_seconds"] == 1800
    assert rows[0]["active_calories"] == 300
    assert rows[0]["total_calories"] == 320
    assert rows[0]["avg_heart_rate"] == 152
    assert rows[0]["max_heart_rate"] == 178

    assert rows[1]["activity_type"] == "walk"
    assert rows[1]["duration_seconds"] == 1200
    assert rows[1]["active_calories"] == 50
    assert rows[1]["total_calories"] == 62
    assert rows[1]["avg_heart_rate"] == 105
    assert rows[1]["max_heart_rate"] == 110


def test_importer_is_idempotent_on_reimport(tmp_path):
    xml_path = tmp_path / "export.xml"
    db_path = tmp_path / "apple_health.db"
    xml_path.write_text(APPLE_HEALTH_EXPORT, encoding="utf-8")

    db = AppleHealthDatabase(str(db_path))
    importer = AppleHealthImporter(db=db)

    importer.import_from_file(xml_path)
    importer.import_from_file(xml_path)

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM workouts")
        assert cursor.fetchone()[0] == 2


def test_importer_prefers_external_uuid_for_workout_id(tmp_path):
    xml_path = tmp_path / "export.xml"
    db_path = tmp_path / "apple_health.db"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
  <Workout workoutActivityType="HKWorkoutActivityTypeWalking" duration="22" durationUnit="min"
    sourceName="Oura" creationDate="2023-11-13 23:22:19 -0700"
    startDate="2022-08-21 08:57:00 -0700" endDate="2022-08-21 09:19:00 -0700">
    <MetadataEntry key="HKExternalUUID" value="oura-workout-272c6e69-1bd4-458a-a13b-ef8a3485e6a8"/>
  </Workout>
</HealthData>
""",
        encoding="utf-8",
    )

    db = AppleHealthDatabase(str(db_path))
    importer = AppleHealthImporter(db=db)
    importer.import_from_file(xml_path)

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM workouts")
        assert cursor.fetchone()[0] == "oura-workout-272c6e69-1bd4-458a-a13b-ef8a3485e6a8"


def test_importer_rejects_git_lfs_pointer_file(tmp_path):
    xml_path = tmp_path / "export.xml"
    db_path = tmp_path / "apple_health.db"
    xml_path.write_text(
        "\n".join([
            "version https://git-lfs.github.com/spec/v1",
            "oid sha256:1234567890abcdef",
            "size 99587116",
        ]),
        encoding="utf-8",
    )

    importer = AppleHealthImporter(db=AppleHealthDatabase(str(db_path)))

    with pytest.raises(ValueError, match="Git LFS pointer"):
        importer.import_from_file(xml_path)


def test_heart_breathing_command_imports_samples_only_and_can_be_retried(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "apple_health.db"
    xml_path = tmp_path / "export.xml"
    xml_path.write_text(APPLE_HEALTH_EXPORT.replace("</HealthData>", """
  <Record type="HKQuantityTypeIdentifierOxygenSaturation" value="0.98" unit="%"
    sourceName="Watch" startDate="2026-04-02 19:00:00 -0700" endDate="2026-04-02 19:00:00 -0700">
    <MetadataEntry key="HKExternalUUID" value="sample-id"/>
  </Record>
</HealthData>"""), encoding="utf-8")
    monkeypatch.setattr(Config, "APPLE_HEALTH_DATABASE_PATH", db_path)
    monkeypatch.setattr(Config, "FILES_DIR", tmp_path)
    db = AppleHealthDatabase(str(db_path))
    assert AppleHealthImporter(db).import_from_file(xml_path) == {"workouts": 2}

    assert main.main(["apple-health-import-heart-breathing"]) == 0
    assert "3 new heart and breathing samples" in capsys.readouterr().out
    assert main.main(["apple-health-import-heart-breathing", str(xml_path)]) == 0
    assert "0 new heart and breathing samples" in capsys.readouterr().out

    with db.read_connection(required_tables=("heart_breathing_samples",)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0] == 2
        rows = conn.execute("""
            SELECT sample_type, value, unit, started_at, source_name, metadata_json
            FROM heart_breathing_samples ORDER BY started_at
        """).fetchall()
    assert [tuple(row) for row in rows] == [
        ("HeartRate", 100.0, "count/min", "2026-04-03T01:05:00+00:00", "Apple Watch", "{}"),
        ("HeartRate", 110.0, "count/min", "2026-04-03T01:10:00+00:00", "Apple Watch", "{}"),
        ("OxygenSaturation", 0.98, "%", "2026-04-03T02:00:00+00:00", "Watch", '{"HKExternalUUID": "sample-id"}'),
    ]


def test_heart_breathing_import_rolls_back_after_invalid_sample(tmp_path):
    db = AppleHealthDatabase(str(tmp_path / "apple_health.db"))
    importer = AppleHealthImporter(db)
    xml_path = tmp_path / "export.xml"
    xml_path.write_text(APPLE_HEALTH_EXPORT, encoding="utf-8")
    assert importer.import_heart_breathing_from_file(xml_path) == 2

    xml_path.write_text(
        APPLE_HEALTH_EXPORT.replace('value="100"', 'value="101"').replace('value="110"', 'value="NaN"'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid HeartRate sample"):
        importer.import_heart_breathing_from_file(xml_path)

    rows = db.fetch_rows("SELECT value FROM heart_breathing_samples ORDER BY value",
                         required_tables=("heart_breathing_samples",))
    assert rows == [{"value": 100.0}, {"value": 110.0}]
