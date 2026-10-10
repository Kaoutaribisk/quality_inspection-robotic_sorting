import base64
import hashlib
import json
import math
import os
import random
import re
import threading
import time
from concurrent.futures import Future
from io import BytesIO
from pathlib import Path

import numpy as np
import pybullet as p
import pybullet_data
from google import genai
from google.genai import types
from PIL import Image, ImageTk

from production_motion import (
    RealtimeStepper,
    create_conveyor,
    move_cube_to_station,
    move_cube_to_pickup_station,
    pick_cube_and_place_in_box,
)

from inspection_camera import INSPECTION_Y, InspectionCamera
from inspection_records import append_record, merge_logs

import conveyor_kitting as conveyor

from conveyor_kitting import (
    BELT_TOP_Z,
    BOX_SLOT_OFFSETS,
    CUBE_HALF_SIZE,
    CUBE_SPAWN_Y,
    TIME_STEP,
    create_painting_station,
    create_sorting_box,
    load_panda,
    wait_steps,
)


PROJECT_DIR = Path(__file__).resolve().parent
PRODUCT_URDF = PROJECT_DIR / "assets" / "cubes" / "inspection_cube.urdf"
DATASET_ROOT = (
    PROJECT_DIR
    / "neu_defect_data"
    / "dataset"
    / "NEU-DET"
    / "train"
    / "images"
)
GOOD_REFERENCE_PATH = PROJECT_DIR / "neu_defect_data" / "good_reference.png"
INSPECTION_LOG_PATH = PROJECT_DIR / "neu_defect_data" / "camera_inspection_log.csv"
INSPECTION_TIMEOUT_SECONDS = 25.0
INSPECTION_MODEL = "gemini-robotics-er-2-preview"
INSPECTION_CONFIG = {"thinking_level": "low", "max_output_tokens": 768}

DEFECT_CLASSES = (
    "crazing",
    "inclusion",
    "patches",
    "pitted_surface",
    "rolled-in_scale",
    "scratches",
)
GOOD_PROBABILITY = 0.35
BOX_CAPACITY = len(BOX_SLOT_OFFSETS)
DESTINATION_CENTERS = {
    "GOOD": [0.31, 0.36],
    "SCRAP": [0.64, 0.30],
}
DESTINATION_COLORS = {
    "GOOD": [0.08, 0.70, 0.16, 1.0],
    "SCRAP": [0.88, 0.08, 0.05, 1.0],
}
DESTINATION_SLOTS = {
    destination: [
        [center[0] + offset[0], center[1] + offset[1]]
        for offset in BOX_SLOT_OFFSETS
    ]
    for destination, center in DESTINATION_CENTERS.items()
}

INSPECTION_PROMPT = """
You are the visual quality-control inspector for a hot-rolled steel production cell.

The supplied image is the photographed top surface of a simulated steel product,
cropped and perspective-corrected from a fixed overhead camera. Inspect only the
visible surface; ordinary illumination variation and the rectangular crop boundary
are not by themselves defects.
Classify the supplied close-up surface image as GOOD or DEFECTIVE. If defective,
select exactly one defect type from the NEU surface-defect taxonomy:

- crazing: a network of fine cracks
- inclusion: embedded impurities, particles, or dark inclusions
- patches: irregular blotchy or patch-like regions
- pitted_surface: many small pits, holes, or depressions
- rolled-in_scale: irregular scale pressed into the surface, often streaky or flaky
- scratches: long narrow linear grooves or scratch marks

A GOOD surface is clean and uniform. Be conservative: if a defect is visible,
classify the product as DEFECTIVE.

Return only one JSON object, without Markdown, in this exact schema:
{
  "condition": "GOOD or DEFECTIVE",
  "defect_type": "GOOD or one taxonomy label",
  "confidence": 0.0,
  "description": "visual explanation in at most 12 words"
}
"""


def create_clean_reference():
    """Create a clean steel sample because NEU-DET contains defects only."""
    if GOOD_REFERENCE_PATH.exists():
        return

    GOOD_REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    base = np.full((256, 256), 166.0, dtype=np.float32)
    brush = np.sin(np.linspace(0, 12 * math.pi, 256)) * 2.0
    base += brush[:, None]
    base += rng.normal(0.0, 1.4, base.shape)
    clean = np.clip(base, 0, 255).astype(np.uint8)
    Image.fromarray(clean).convert("RGB").save(GOOD_REFERENCE_PATH)


def validate_dataset():
    missing = [name for name in DEFECT_CLASSES if not (DATASET_ROOT / name).is_dir()]
    if missing:
        raise FileNotFoundError(
            "NEU dataset is incomplete. Missing folders: " + ", ".join(missing)
        )


class ProductionControl:
    """Production stops between products; a held product can be retried."""

    def __init__(self):
        self.running = False
        self.active = False
        self.single_cycle = False
        self.started = False
        self.fault = False
        self.retry_requested = False
        self.retry_available = False
        self.motion_fault = False
        self.camera_fault = False

    def start(self, single_cycle=False):
        if self.active or self.fault:
            return
        self.running = True
        self.started = True
        self.single_cycle = single_cycle

    def stop(self):
        self.running = False

    def finish_cycle(self):
        self.active = False
        if self.single_cycle:
            self.running = False
        self.single_cycle = False

    def retry(self):
        if self.fault and self.retry_available:
            self.retry_requested = True


class InspectionDashboard:
    """Keep the close-up and diagnosis outside the robot's workspace."""

    def __init__(self):
        import tkinter as tk

        self.root = tk.Tk()
        self.root.title("Gemini | Surface inspection")
        self.root.geometry("440x820")
        self.root.configure(bg="#141b24")
        self.closed = False
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.last_refresh = 0.0
        self.inspection_started = None
        self.photo = None
        self.control = ProductionControl()

        def label(text, size=12, color="#c3cfdd"):
            widget = tk.Label(
                self.root, text=text, bg="#141b24", fg=color,
                font=("Segoe UI", size), wraplength=370, justify="left",
            )
            widget.pack(padx=18, pady=7, anchor="w")
            return widget

        label("SURFACE INSPECTION", 19, "#ffffff")
        self.production_status = label("Production stopped | Press Start production", 12, "#ffce75")
        controls = tk.Frame(self.root, bg="#141b24")
        controls.pack(padx=18, pady=6, fill="x")

        def button(text, command, row, column):
            widget = tk.Button(
                controls, text=text, command=command, bg="#27384c", fg="white",
                disabledforeground="#718094", relief="flat", padx=8, pady=9,
            )
            widget.grid(row=row, column=column, padx=3, pady=3, sticky="ew")
            return widget

        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)
        self.start_button = button("Start production", self.control.start, 0, 0)
        self.stop_button = button("Stop production", self.control.stop, 0, 1)
        self.single_button = button("Run one cycle", lambda: self.control.start(True), 1, 0)
        self.retry_button = button("Retry inspection", self.control.retry, 1, 1)
        self.phase = label("Ready", 12, "#81b8ff")
        self.image_label = tk.Label(self.root, bg="#141b24")
        self.image_label.pack(pady=8)
        self.camera_status = label("Camera ready | Waiting for a product", 10, "#8e9bab")
        self.diagnosis = label("Waiting for product", 17, "#ffffff")
        self.evidence = label("")
        self.counts = label("Accepted: 0   |   Scrap: 0", 12)
        tk.Button(
            self.root, text="Exit simulation", command=self.close,
            bg="#27384c", fg="white", relief="flat", padx=15, pady=8,
        ).pack(padx=18, pady=12, anchor="w")

    def close(self):
        self.closed = True

    def show_product(self, cycle):
        self.photo = None
        self.image_label.configure(image="", text="Waiting for camera snapshot", fg="#c3cfdd")
        self.diagnosis.configure(text=f"Product {cycle} | Arriving at camera...", fg="#ffffff")
        self.evidence.configure(text="Conveyor transporting product from painting station.")
        self.phase.configure(text="Moving to inspection camera")
        self.camera_status.configure(text="Camera ready | Waiting for the stopping sensor")

    def show_capture(self, capture, cycle):
        with Image.open(BytesIO(capture.png_bytes)) as source:
            image = source.convert("RGB").resize((260, 260))
        self.photo = ImageTk.PhotoImage(image, master=self.root)
        self.image_label.configure(image=self.photo, text="")
        self.diagnosis.configure(text=f"Product {cycle} | Inspecting...", fg="#ffffff")
        self.camera_status.configure(text=f"Camera snapshot | Top surface | Capture: {capture.seconds:.2f} s")
        self.evidence.configure(text="Gemini Robotics ER is checking the captured camera image.")
        self.inspection_started = time.monotonic()

    def show_result(self, result, seconds):
        self.inspection_started = None
        good = result["condition"] == "GOOD"
        defect = result["defect_type"].replace("_", " ").upper()
        self.diagnosis.configure(
            text=f"{defect}\n{'GOOD BOX' if good else 'SCRAP BOX'}",
            fg="#6de6a0" if good else "#ff8d86",
        )
        self.evidence.configure(
            text=f"Model confidence: {result['confidence']:.0%}\n"
            f"{result['description']}\nInspection: {seconds:.1f} s"
            + (" | Cached Gemini result" if result.get("_cache_hit") else " | Gemini ER")
        )
        self.phase.configure(text="Robot sorting product")

    def update_counts(self, counts):
        self.counts.configure(text=f"Accepted: {counts['GOOD']}   |   Scrap: {counts['SCRAP']}")

    def refresh(self):
        if self.closed:
            raise KeyboardInterrupt
        now = time.monotonic()
        if now - self.last_refresh < 0.05:
            return
        self.last_refresh = now
        control = self.control
        can_start = not control.active and not control.running and not control.fault
        self.start_button.configure(
            text="Resume production" if control.started else "Start production",
            state="normal" if can_start else "disabled",
        )
        self.single_button.configure(state="normal" if can_start else "disabled")
        self.stop_button.configure(state="normal" if control.running else "disabled")
        self.retry_button.configure(
            state="normal" if control.fault and control.retry_available else "disabled"
        )
        if control.camera_fault:
            production_text = "Camera error | Product stopped | Retry or Exit"
        elif control.motion_fault:
            production_text = "Motion paused | Inspect the scene, then Exit"
        elif control.fault:
            production_text = "Inspection error | Product held | Retry or Exit"
        elif control.active and not control.running:
            production_text = "Stopping after the current product..."
        elif control.running:
            production_text = "Running one cycle" if control.single_cycle else "Production running"
        else:
            production_text = "Production stopped | Ready to start or resume"
        self.production_status.configure(text=production_text)
        if self.inspection_started is not None:
            self.phase.configure(text=f"Processing camera image | {now-self.inspection_started:.1f} s")
        self.root.update_idletasks()
        self.root.update()

    def destroy(self):
        self.root.destroy()


def create_destination_boxes():
    for destination, center in DESTINATION_CENTERS.items():
        create_sorting_box(destination, center, DESTINATION_COLORS[destination])


def choose_surface_sample():
    if random.random() < GOOD_PROBABILITY:
        return GOOD_REFERENCE_PATH, "GOOD"

    defect_type = random.choice(DEFECT_CLASSES)
    candidates = list((DATASET_ROOT / defect_type).glob("*.jpg"))
    if not candidates:
        raise FileNotFoundError(f"No images found for defect class: {defect_type}")
    return random.choice(candidates), defect_type


def spawn_inspection_cube(cycle_number, image_path):
    random_x = random.uniform(0.43, 0.67)
    random_yaw = random.uniform(-math.pi, math.pi)
    cube_z = BELT_TOP_Z + CUBE_HALF_SIZE + 0.005
    cube = p.loadURDF(
        str(PRODUCT_URDF),
        [random_x, CUBE_SPAWN_Y, cube_z],
        p.getQuaternionFromEuler([0, 0, random_yaw]),
        useFixedBase=False,
    )
    texture = p.loadTexture(str(image_path))
    p.changeVisualShape(
        cube,
        -1,
        rgbaColor=[1.0, 1.0, 1.0, 1.0],
        textureUniqueId=texture,
    )
    p.changeDynamics(cube, -1, lateralFriction=0.25, restitution=0.0)
    print(
        f"\n=== QUALITY-CONTROL CYCLE {cycle_number} ===\n"
        f"Painting station released an unclassified product at x={random_x:.3f} m."
    )
    return cube


def parse_inspection_response(response_text):
    match = re.search(r"\{.*\}", response_text, flags=re.DOTALL)
    if not match:
        raise ValueError("Gemini did not return a JSON object.")

    result = json.loads(match.group(0))
    condition = str(result.get("condition", "")).strip().upper()
    defect_type = str(result.get("defect_type", "")).strip().lower().replace(" ", "_")
    if defect_type == "rolled_in_scale":
        defect_type = "rolled-in_scale"

    confidence = max(0.0, min(1.0, float(result.get("confidence", 0.0))))
    description = str(result.get("description", "No description supplied.")).strip()

    if condition == "GOOD" and defect_type == "good":
        normalized_type = "GOOD"
    elif condition == "DEFECTIVE" and defect_type in DEFECT_CLASSES:
        normalized_type = defect_type
    else:
        raise ValueError(
            f"Unexpected classification: condition={condition!r}, "
            f"defect_type={defect_type!r}"
        )

    return {
        "condition": condition,
        "defect_type": normalized_type,
        "confidence": confidence,
        "description": description,
    }


class InspectionCache:
    """Reuse only actual Gemini decisions for identical bytes and request settings."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        try:
            self.results = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.results, dict):
                self.results = {}
        except (OSError, ValueError):
            self.results = {}

    def key(self, pixels):
        settings = json.dumps([INSPECTION_MODEL, INSPECTION_CONFIG, INSPECTION_PROMPT], sort_keys=True).encode()
        return hashlib.sha256(settings + pixels).hexdigest()

    def get(self, key):
        with self.lock:
            value = self.results.get(key)
            if value is None:
                return None
            try:
                return parse_inspection_response(json.dumps(value))
            except (ValueError, TypeError):
                return None

    def put(self, key, result):
        with self.lock:
            self.results[key] = {k: v for k, v in result.items() if not k.startswith("_")}
            temporary = self.path.with_suffix(".tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_text(json.dumps(self.results, indent=2), encoding="utf-8")
                temporary.replace(self.path)
            except OSError as error:
                print(f"Cache could not be saved: {error}")


def inspect_surface_with_gemini(client, pixels, cache=None):
    started = time.monotonic()
    # Immutable rendered PNG bytes, never a source texture path or dataset label.
    if not isinstance(pixels, bytes) or not pixels.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Inspection requires a captured PNG camera image.")
    cache_key = cache.key(pixels) if cache else None
    cached = cache.get(cache_key) if cache else None
    if cached is not None:
        print("Reusing cached Gemini decision for identical surface pixels.")
        return dict(cached, _cache_hit=True, _inspection_seconds=0.0)
    print("Gemini Robotics ER is inspecting the camera snapshot...")
    image_data = base64.b64encode(pixels).decode("ascii")
    response = client.interactions.create(
        model=INSPECTION_MODEL,
        input=[
            {
                "type": "image",
                "data": image_data,
                "mime_type": "image/png",
            },
            {"type": "text", "text": INSPECTION_PROMPT},
        ],
        generation_config=INSPECTION_CONFIG,
        timeout=INSPECTION_TIMEOUT_SECONDS,
    )
    result = parse_inspection_response(response.output_text)
    if cache:
        cache.put(cache_key, result)
    return dict(result, _cache_hit=False, _inspection_seconds=time.monotonic()-started)


def start_inspection(client, pixels, cache=None):
    future = Future()

    def work():
        try:
            result = inspect_surface_with_gemini(client, pixels, cache)
            future.set_result(result)
        except Exception as error:
            future.set_exception(error)

    threading.Thread(target=work, daemon=True, name="GeminiInspector").start()
    return future


def finish_inspection(client, pixels, future, started, dashboard, cache=None):
    """Wait responsively and allow manual retries for the same held product."""
    control = dashboard.control
    while True:
        try:
            while not future.done():
                if time.monotonic() - started > INSPECTION_TIMEOUT_SECONDS:
                    raise TimeoutError("Inspection exceeded 25 seconds.")
                conveyor.step_simulation()
            result = future.result()
            return result, result.get("_inspection_seconds", time.monotonic() - started)
        except Exception as error:
            print(f"Inspection stopped: {error}")
            control.running = False
            control.fault = True
            control.retry_requested = False
            dashboard.inspection_started = None
            dashboard.phase.configure(text="Inspection unavailable | Line paused")
            dashboard.diagnosis.configure(text="Product held at pickup", fg="#ffce75")
            dashboard.evidence.configure(text=str(error)[:250])
            while not control.retry_requested:
                # Wait for a timed-out request to end before starting another.
                control.retry_available = future.done()
                conveyor.step_simulation()
            control.fault = False
            control.retry_available = False
            control.retry_requested = False
            started = time.monotonic()
            dashboard.inspection_started = started
            dashboard.phase.configure(text="Retrying held product")
            future = start_inspection(client, pixels, cache)


def capture_product(camera, cube, cycle, dashboard):
    """An invalid photograph pauses the line; it never creates a quality decision."""
    control = dashboard.control
    while True:
        try:
            capture = camera.capture(cube, cycle)
            control.fault = False
            control.camera_fault = False
            control.retry_available = False
            return capture
        except Exception as error:
            print(f"Camera capture stopped: {error}")
            control.running = False
            control.fault = True
            control.camera_fault = True
            control.retry_requested = False
            control.retry_available = True
            dashboard.phase.configure(text="Camera unavailable | Line paused")
            dashboard.diagnosis.configure(text="Product held under camera", fg="#ffce75")
            dashboard.evidence.configure(text=str(error)[:250])
            while not control.retry_requested:
                conveyor.step_simulation()
            control.retry_requested = False


def append_inspection_log(cycle_number, image_path, expected_type, result, destination, capture):
    expected_condition = "GOOD" if expected_type == "GOOD" else "DEFECTIVE"
    type_match = result["defect_type"] == expected_type
    append_record(INSPECTION_LOG_PATH, {
        "cycle": cycle_number,
        "image": str(image_path),
        "expected_condition": expected_condition,
        "expected_type": expected_type,
        "gemini_condition": result["condition"],
        "gemini_type": result["defect_type"],
        "confidence": f"{result['confidence']:.4f}",
        "type_match": type_match,
        "destination": destination,
        "description": result["description"],
        "camera_frame": str(capture.frame_path),
        "camera_top_surface": str(capture.surface_path),
        "capture_seconds": f"{capture.seconds:.4f}",
        "inspection_source": "Camera",
    })
    return type_match


def main():
    os.chdir(PROJECT_DIR)
    validate_dataset()
    create_clean_reference()
    merge_logs(INSPECTION_LOG_PATH.parent)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing from this terminal.")
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=int(INSPECTION_TIMEOUT_SECONDS * 1000),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    cache = InspectionCache(PROJECT_DIR / "neu_defect_data" / "inspection_cache.json")

    p.connect(p.GUI)
    p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.setTimeStep(TIME_STEP)
    p.setGravity(0, 0, -9.81)
    plane = p.loadURDF("plane.urdf")
    p.changeVisualShape(plane, -1, textureUniqueId=-1, rgbaColor=[0.32, 0.36, 0.40, 1])
    p.resetDebugVisualizerCamera(
        cameraDistance=2.25,
        cameraYaw=75,
        cameraPitch=-57,
        cameraTargetPosition=[0.50, -0.34, 0.12],
    )

    create_conveyor()
    create_painting_station()
    create_destination_boxes()
    # Remove crowded imported labels and retain only short station names.
    p.removeAllUserDebugItems()
    for destination, center in DESTINATION_CENTERS.items():
        p.addUserDebugText(
            destination, [center[0], center[1], 0.23],
            textColorRGB=DESTINATION_COLORS[destination][:3], textSize=1.3,
        )
    camera = InspectionCamera(PROJECT_DIR / "neu_defect_data" / "camera_captures")
    camera.create_housing()
    panda = load_panda()
    dashboard = InspectionDashboard()
    original_step = conveyor.step_simulation
    original_camera = conveyor.render_camera_panels
    conveyor.render_camera_panels = lambda: None

    conveyor.step_simulation = RealtimeStepper(dashboard.refresh)

    cycle_number = 1
    packed_cubes = {"GOOD": [], "SCRAP": []}
    total_counts = {"GOOD": 0, "SCRAP": 0}
    correct_predictions = 0

    try:
        while p.isConnected():
            # No product is spawned or API request made until Start is clicked.
            while not dashboard.control.running:
                conveyor.step_simulation()
            dashboard.control.active = True
            image_path, expected_type = choose_surface_sample()
            cube = spawn_inspection_cube(cycle_number, image_path)
            dashboard.show_product(cycle_number)
            move_cube_to_station(cube, INSPECTION_Y, "Inspection camera")
            dashboard.phase.configure(text="Product stopped | Capturing top surface")
            dashboard.refresh()
            capture = capture_product(camera, cube, cycle_number, dashboard)
            dashboard.show_capture(capture, cycle_number)
            print(f"Camera captured product top in {capture.seconds:.2f}s: {capture.surface_path}")
            inspection_started = time.monotonic()
            inspection_future = start_inspection(client, capture.png_bytes, cache)
            cube_position = move_cube_to_pickup_station(cube)
            print("Pickup sensor triggered. Conveyor stopped.")

            result, inspection_seconds = finish_inspection(
                client, capture.png_bytes, inspection_future, inspection_started, dashboard, cache
            )

            destination = "GOOD" if result["condition"] == "GOOD" else "SCRAP"
            dashboard.show_result(result, inspection_seconds)

            print("\n===== GEMINI QUALITY REPORT =====")
            print(f"Condition: {result['condition']}")
            print(f"Defect type: {result['defect_type']}")
            print(f"Confidence: {result['confidence']:.0%}")
            print(f"Evidence: {result['description']}")
            print(f"Inspection: {inspection_seconds:.2f}s | {'Cached Gemini result' if result.get('_cache_hit') else 'Gemini ER request'}")
            print(f"Decision: route product to {destination} BOX")

            slot_index = len(packed_cubes[destination])
            try:
                pick_cube_and_place_in_box(
                    panda, cube, cube_position,
                    DESTINATION_SLOTS[destination][slot_index], destination,
                )
            except RuntimeError as error:
                print(f"Motion stopped: {error}")
                dashboard.control.running = False
                dashboard.control.fault = True
                dashboard.control.motion_fault = True
                dashboard.control.retry_available = False
                dashboard.phase.configure(text="Motion verification failed")
                dashboard.evidence.configure(text=str(error))
                while p.isConnected():
                    conveyor.step_simulation()
            packed_cubes[destination].append(cube)
            total_counts[destination] += 1
            dashboard.update_counts(total_counts)

            type_match = append_inspection_log(
                cycle_number, image_path, expected_type, result, destination, capture
            )
            correct_predictions += int(type_match)
            print(
                f"Dataset truth: {expected_type} | "
                f"Exact type match: {'YES' if type_match else 'NO'} | "
                f"Running exact-match accuracy: {correct_predictions / cycle_number:.1%}"
            )
            print(
                f"{destination} box count: "
                f"{len(packed_cubes[destination])}/{BOX_CAPACITY}"
            )

            if len(packed_cubes[destination]) == BOX_CAPACITY:
                print(f"{destination} box full. Dispatching it...")
                wait_steps(60)
                for packed_cube in packed_cubes[destination]:
                    p.removeBody(packed_cube)
                packed_cubes[destination].clear()
                print(f"Empty {destination} box ready.")

            cycle_number += 1
            dashboard.control.finish_cycle()
            dashboard.phase.configure(text="Cycle complete | Robot ready")
            wait_steps(12)
    except KeyboardInterrupt:
        print("\nDefect-inspection simulation stopped cleanly.")
    finally:
        conveyor.step_simulation = original_step
        conveyor.render_camera_panels = original_camera
        dashboard.destroy()
        if p.isConnected():
            p.disconnect()


if __name__ == "__main__":
    main()
