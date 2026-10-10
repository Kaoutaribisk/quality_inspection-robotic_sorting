"""Offline camera, motion and request-boundary tests; no real API calls."""

import base64
import csv
from io import BytesIO
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROJECT = Path(os.environ.get("GEMINI_PROJECT_DIR", ROOT)).resolve()
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(ROOT))

import numpy as np
import pybullet as p
import pybullet_data
from PIL import Image

import conveyor_kitting as conveyor
import defect_inspection_kitting as production
from inspection_camera import INSPECTION_Y, InspectionCamera
from production_motion import RealtimeStepper, create_conveyor, move_cube_to_station
from production_motion import move_cube_to_pickup_station, pick_cube_and_place_in_box

OUTPUT = ROOT / "camera_test_output"


class CameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_cwd = Path.cwd()
        os.chdir(PROJECT)
        p.connect(p.DIRECT)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setTimeStep(conveyor.TIME_STEP)
        p.setGravity(0, 0, -9.81)
        p.loadURDF("plane.urdf")
        create_conveyor()
        conveyor.create_painting_station()
        production.create_destination_boxes()
        cls.robot = conveyor.load_panda()
        cls.camera = InspectionCamera(OUTPUT / "captures")
        cls.camera.create_housing()
        cls.old_step = conveyor.step_simulation
        conveyor.step_simulation = RealtimeStepper(lambda: None, realtime=False)
        cls.source = next((PROJECT / "neu_defect_data" / "dataset" / "NEU-DET"
                           / "train" / "images" / "scratches").glob("*.jpg"))
        cls.bodies = []

    @classmethod
    def tearDownClass(cls):
        conveyor.step_simulation = cls.old_step
        p.disconnect()
        os.chdir(cls.old_cwd)

    def spawn(self, x=0.55, yaw=0.0, texture=None):
        cube = p.loadURDF(
            str(production.PRODUCT_URDF),
            [x, conveyor.CUBE_SPAWN_Y, conveyor.BELT_TOP_Z + conveyor.CUBE_HALF_SIZE + 0.005],
            p.getQuaternionFromEuler([0, 0, yaw]),
        )
        p.changeVisualShape(cube, -1, rgbaColor=[1, 1, 1, 1],
                            textureUniqueId=p.loadTexture(str(texture or self.source)))
        p.changeDynamics(cube, -1, lateralFriction=0.25, restitution=0)
        self.addCleanup(p.removeBody, cube)
        return cube

    def test_rotated_products_across_belt(self):
        for cycle, (x, yaw) in enumerate([
            (0.43, 0), (0.43, math.pi/4), (0.67, -math.pi/4),
            (0.67, math.pi), (0.55, 1.1), (0.55, -2.4),
        ], 1):
            with self.subTest(x=x, yaw=yaw):
                cube = self.spawn(x, yaw)
                move_cube_to_station(cube, INSPECTION_Y, "Camera")
                capture = self.camera.capture(cube, cycle)
                self.assertTrue(capture.frame_path.exists())
                self.assertEqual(capture.surface_path.read_bytes(), capture.png_bytes)
                with Image.open(BytesIO(capture.png_bytes)) as image:
                    self.assertEqual(image.size, (256, 256))
                    self.assertGreater(np.asarray(image).std(), 3)
                print(f"Capture at x={x:.2f}, yaw={yaw:.2f}: {capture.seconds:.3f}s")
                p.resetBasePositionAndOrientation(cube, [x, -2, 0.4], [0, 0, 0, 1])

    def test_invisible_or_moving_product_is_rejected(self):
        cube = self.spawn()
        with self.assertRaisesRegex(RuntimeError, "stopping line"):
            self.camera.capture(cube, 50)
        move_cube_to_station(cube, INSPECTION_Y, "Camera")
        p.resetBaseVelocity(cube, [0, 0.2, 0])
        with self.assertRaisesRegex(RuntimeError, "stationary"):
            self.camera.capture(cube, 50)
        p.resetBaseVelocity(cube, [0, 0, 0])
        p.resetBasePositionAndOrientation(cube, [1.0, INSPECTION_Y, 0.145], [0, 0, 0, 1])
        with self.assertRaisesRegex(RuntimeError, "outside"):
            self.camera.capture(cube, 50)

    def test_occlusion_is_rejected(self):
        cube = self.spawn()
        move_cube_to_station(cube, INSPECTION_Y, "Camera")
        obstruction = conveyor.create_static_box([0.10, 0.10, 0.01],
                                                 [0.55, INSPECTION_Y, 0.35], [0, 0, 0, 1])
        self.addCleanup(p.removeBody, obstruction)
        with self.assertRaisesRegex(RuntimeError, "obstructed"):
            self.camera.capture(cube, 51)

    def test_conveyor_capture_then_pick_and_place(self):
        cube = self.spawn(0.67, math.pi/4)
        move_cube_to_station(cube, INSPECTION_Y, "Camera")
        self.camera.capture(cube, 99)
        position = move_cube_to_pickup_station(cube)
        slot = production.DESTINATION_SLOTS["SCRAP"][0]
        pick_cube_and_place_in_box(self.robot, cube, position, slot, "SCRAP")
        placed, _ = p.getBasePositionAndOrientation(cube)
        self.assertLess(math.dist(placed[:2], slot), 0.02)
        self.assertTrue(0.04 <= placed[2] <= 0.09)

    def test_request_contains_camera_bytes_only_and_reuses_cache(self):
        cube = self.spawn()
        move_cube_to_station(cube, INSPECTION_Y, "Camera")
        capture = self.camera.capture(cube, 100)
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            self.assertEqual(base64.b64decode(kwargs["input"][0]["data"]), capture.png_bytes)
            self.assertNotIn(str(self.source), json.dumps(kwargs))
            return SimpleNamespace(output_text=json.dumps({
                "condition": "DEFECTIVE", "defect_type": "scratches",
                "confidence": 0.8, "description": "Visible linear marks",
            }))

        client = SimpleNamespace(interactions=SimpleNamespace(create=create))
        cache = production.InspectionCache(OUTPUT / "cache.json")
        cache.results = {}
        with patch.object(p, "getCameraImage", side_effect=AssertionError("Worker touched physics")):
            result = production.start_inspection(client, capture.png_bytes, cache).result(timeout=5)
            cached = production.start_inspection(client, capture.png_bytes, cache).result(timeout=5)
        self.assertEqual(result["defect_type"], "scratches")
        self.assertFalse(result["_cache_hit"])
        self.assertTrue(cached["_cache_hit"])
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ValueError):
            production.inspect_surface_with_gemini(client, self.source)

    def test_top_face_contains_the_full_source_pattern(self):
        # The primitive cube used to hide a scratch by mapping only part of the image.
        cube = self.spawn(0.55, math.pi/4)
        move_cube_to_station(cube, INSPECTION_Y, "Camera")
        capture = self.camera.capture(cube, 101)
        with Image.open(self.source) as source, Image.open(BytesIO(capture.png_bytes)) as camera:
            expected = np.asarray(source.convert("L").resize((256, 256)), dtype=float)
            actual = np.asarray(camera.convert("L"), dtype=float)
        # Ignore rasterization at the projected face boundary, not the defect pattern.
        correlations = [np.corrcoef(actual[4:-4, 4:-4].ravel(), np.rot90(expected, k)[4:-4, 4:-4].ravel())[0, 1]
                        for k in range(4)]
        self.assertGreater(max(correlations), 0.90)


class MainLoopTests(unittest.TestCase):
    def test_two_cycles_use_captures_and_keep_separate_camera_log(self):
        runtime = OUTPUT / "main-loop"
        runtime.mkdir(parents=True, exist_ok=True)
        log_path = runtime / f"log-{__import__('time').time_ns()}.csv"
        captures, decisions, events = [], [], []
        gui_thread = threading.get_ident()

        class Dashboard:
            def __init__(self):
                self.control = production.ProductionControl()
                self.control.start()
                self.inspection_started = None
                self.counts = {"GOOD": 0, "SCRAP": 0}
                self.phase = self.diagnosis = self.evidence = SimpleNamespace(configure=lambda **kw: None)

            def show_product(self, cycle):
                events.append("product")

            def show_capture(self, capture, cycle):
                self_test.assertEqual(threading.get_ident(), gui_thread)
                captures.append(capture)
                events.append("capture")

            def show_result(self, result, seconds):
                decisions.append(result)

            def update_counts(self, counts):
                self.counts = dict(counts)

            def refresh(self):
                if sum(self.counts.values()) == 2:
                    raise KeyboardInterrupt

            def destroy(self):
                events.append("closed")

        self_test = self

        def create(**kwargs):
            self.assertNotEqual(threading.get_ident(), gui_thread)
            self.assertEqual(events[-1], "capture")
            self.assertEqual(base64.b64decode(kwargs["input"][0]["data"]), captures[-1].png_bytes)
            condition, defect = ("GOOD", "GOOD") if len(captures) == 1 else ("DEFECTIVE", "scratches")
            return SimpleNamespace(output_text=json.dumps({
                "condition": condition, "defect_type": defect,
                "confidence": 0.8, "description": "Offline test decision",
            }))

        real_connect = p.connect
        real_load_panda = conveyor.load_panda

        def load_robot():
            previous = Path.cwd()
            try:
                os.chdir(PROJECT)
                return real_load_panda()
            finally:
                os.chdir(previous)

        source = next((PROJECT / "neu_defect_data" / "dataset" / "NEU-DET"
                       / "train" / "images" / "scratches").glob("*.jpg"))
        previous = Path.cwd()
        try:
            with patch.object(production, "PROJECT_DIR", runtime), \
                 patch.object(production, "INSPECTION_LOG_PATH", log_path), \
                 patch.object(production, "validate_dataset"), \
                 patch.object(production, "create_clean_reference"), \
                 patch.object(production, "choose_surface_sample", return_value=(source, "scratches")), \
                 patch.object(production, "InspectionDashboard", Dashboard), \
                 patch.object(production, "load_panda", load_robot), \
                 patch.object(production, "RealtimeStepper", side_effect=lambda refresh: RealtimeStepper(refresh, False)), \
                 patch.object(p, "connect", side_effect=lambda mode: real_connect(p.DIRECT)), \
                 patch.object(production.genai, "Client", return_value=SimpleNamespace(interactions=SimpleNamespace(create=create))), \
                 patch.dict(os.environ, {"GEMINI_API_KEY": "offline-test"}):
                production.main()
        finally:
            os.chdir(previous)
        self.assertFalse(p.isConnected())
        self.assertEqual(len(captures), 2)
        self.assertEqual(len(decisions), 2)
        self.assertEqual(events[-1], "closed")
        with log_path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["destination"] for row in rows], ["GOOD", "SCRAP"])
        self.assertEqual(rows[0]["camera_top_surface"], str(captures[0].surface_path))


class ControlTests(unittest.TestCase):
    def test_single_cycle_and_stop_finish_current_product(self):
        control = production.ProductionControl()
        control.start(True)
        control.active = True
        control.stop()
        self.assertFalse(control.running)
        self.assertTrue(control.active)
        control.finish_cycle()
        self.assertFalse(control.running)
        self.assertFalse(control.active)

    def test_hidden_dashboard_displays_the_exact_camera_png(self):
        import tkinter as tk
        real_tk = tk.Tk

        def hidden_root():
            root = real_tk()
            root.withdraw()
            return root

        try:
            with patch.object(tk, "Tk", hidden_root):
                dashboard = production.InspectionDashboard()
        except tk.TclError as error:
            self.skipTest(f"Tk runtime unavailable in this execution environment: {error}")
        try:
            png = BytesIO()
            Image.new("RGB", (256, 256), (60, 80, 100)).save(png, format="PNG")
            capture = SimpleNamespace(png_bytes=png.getvalue(), seconds=0.25)
            dashboard.show_product(1)
            dashboard.show_capture(capture, 1)
            self.assertEqual(dashboard.photo.width(), 260)
            dashboard.show_result({"condition": "GOOD", "defect_type": "GOOD",
                                   "confidence": 0.8, "description": "Clean"}, 1.0)
            dashboard.refresh()
            self.assertIn("Camera snapshot", dashboard.camera_status.cget("text"))
            self.assertEqual(dashboard.start_button.cget("state"), "normal")
        finally:
            dashboard.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
