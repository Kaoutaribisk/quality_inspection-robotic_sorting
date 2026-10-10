import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("inspection_records", PROJECT / "inspection_records.py")
records = importlib.util.module_from_spec(spec)
spec.loader.exec_module(records)


def row(source="Texture", cycle="1"):
    result = dict(zip(records.BASE_FIELDS, [cycle, "patches/a.jpg", "DEFECTIVE", "patches", "DEFECTIVE", "patches", "0.9", "True", "SCRAP", "Patch, with a quoted \"edge\"."]))
    result.update(camera_frame="", camera_top_surface="", capture_seconds="", inspection_source=source)
    if source == "Camera":
        result.update(camera_frame="frame.png", camera_top_surface="top.png", capture_seconds="0.4690")
    return result


def write(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


class RecordsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.legacy = self.data / "inspection_log.csv"
        self.camera = self.data / "camera_inspection_log.csv"

    def tearDown(self):
        self.temp.cleanup()

    def test_merge_preserves_repeated_cycles_and_identical_rows(self):
        write(self.legacy, records.BASE_FIELDS, [row(), row(), row(cycle="2")])
        write(self.camera, records.BASE_FIELDS + records.CAMERA_FIELDS, [row("Camera"), row("Camera")])
        legacy_bytes = self.legacy.read_bytes()
        summary = records.merge_logs(self.data)
        self.assertEqual(summary["total_rows"], 5)
        merged, header, _ = records._read(self.camera, "Camera")
        self.assertEqual(header, records.FIELDS)
        self.assertEqual(sum(r["inspection_source"] == "Texture" for r in merged), 3)
        self.assertEqual(merged[0]["capture_seconds"], "")
        self.assertEqual(merged[0]["description"], row()["description"])
        self.assertEqual(self.legacy.read_bytes(), legacy_bytes)
        before = self.camera.read_bytes()
        self.assertFalse(records.merge_logs(self.data)["changed"])
        self.assertEqual(self.camera.read_bytes(), before)
        self.assertTrue(Path(summary["backup_directory"]).exists())
        records.append_record(self.camera, row("Camera", "3"))
        self.assertEqual(records.merge_logs(self.data)["total_rows"], 6)
        write(self.legacy, records.BASE_FIELDS, [row(), row(), row(cycle="2"), row()])
        self.assertEqual(records.merge_logs(self.data)["legacy_rows_added"], 1)
        self.assertEqual(len(records._read(self.camera, "Camera")[0]), 7)

    def test_missing_camera_creates_unified_log(self):
        write(self.legacy, records.BASE_FIELDS, [row()])
        self.assertEqual(records.merge_logs(self.data)["total_rows"], 1)

    def test_bad_schema_does_not_overwrite(self):
        self.camera.write_text("unexpected\nvalue\n", encoding="utf-8")
        original = self.camera.read_bytes()
        with self.assertRaises(ValueError):
            records.merge_logs(self.data)
        self.assertEqual(self.camera.read_bytes(), original)

    def test_invalid_numeric_data_does_not_overwrite(self):
        bad = row("Camera")
        bad["confidence"] = "nan"
        write(self.camera, records.FIELDS, [bad])
        original = self.camera.read_bytes()
        with self.assertRaises(ValueError):
            records.merge_logs(self.data)
        self.assertEqual(self.camera.read_bytes(), original)

    def test_fresh_append(self):
        records.append_record(self.camera, row("Camera"))
        self.assertEqual(records._read(self.camera, "Camera")[0], [row("Camera")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
