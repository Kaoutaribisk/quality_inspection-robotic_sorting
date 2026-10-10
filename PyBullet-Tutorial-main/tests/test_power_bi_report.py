import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_power_bi_report import MEASURES, build
from inspection_records import FIELDS


class ReportTests(unittest.TestCase):
    def test_report_model_queries_and_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "GeminiKitting"
            output = root / "report"
            pbip = build(project, output)
            pointer = json.loads(pbip.read_text(encoding="utf-8"))
            report = output / pointer["artifacts"][0]["report"]["path"]
            reference = json.loads((report / "definition.pbir").read_text(encoding="utf-8"))
            model = (report / reference["datasetReference"]["byPath"]["path"]).resolve()
            database = json.loads((model / "model.bim").read_text(encoding="utf-8"))
            table = database["model"]["tables"][0]
            columns = {column["name"] for column in table["columns"]}
            measures = {measure["name"] for measure in table["measures"]}
            self.assertTrue(set(FIELDS).issubset(columns))
            self.assertEqual(measures, set(MEASURES))
            query = "\n".join(table["partitions"][0]["source"]["expression"])
            self.assertIn(str(project / "neu_defect_data" / "camera_inspection_log.csv"), query)
            self.assertIn('"en-US"', query)
            self.assertIn("type nullable number", query)
            self.assertNotIn("Columns=", query)
            self.assertNotIn("GEMINI_API_KEY", query)
            pages_root = report / "definition" / "pages"
            pages = json.loads((pages_root / "pages.json").read_text(encoding="utf-8"))
            self.assertEqual(len(pages["pageOrder"]), 3)
            visual_count = 0
            for name in pages["pageOrder"]:
                page_path = pages_root / name
                page = json.loads((page_path / "page.json").read_text(encoding="utf-8"))
                rectangles = []
                for path in (page_path / "visuals").glob("*/visual.json"):
                    visual_count += 1
                    spec = json.loads(path.read_text(encoding="utf-8"))
                    position = spec["position"]
                    self.assertGreater(position["width"], 0)
                    self.assertGreater(position["height"], 0)
                    self.assertLessEqual(position["x"] + position["width"], page["width"])
                    self.assertLessEqual(position["y"] + position["height"], page["height"])
                    for previous in rectangles:
                        intersects = (position["x"] < previous["x"] + previous["width"] and previous["x"] < position["x"] + position["width"] and position["y"] < previous["y"] + previous["height"] and previous["y"] < position["y"] + position["height"])
                        self.assertFalse(intersects, spec["name"])
                    rectangles.append(position)
                    for role in spec["visual"]["query"]["queryState"].values():
                        for projection in role["projections"]:
                            expression = projection["field"]
                            kind = next(iter(expression))
                            prop = expression[kind]["Property"]
                            self.assertIn(prop, measures if kind == "Measure" else columns)
            self.assertEqual(visual_count, 24)


if __name__ == "__main__":
    unittest.main(verbosity=2)
