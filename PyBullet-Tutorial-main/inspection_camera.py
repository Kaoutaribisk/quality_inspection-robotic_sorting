"""Fixed overhead inspection camera; every inspection uses rendered scene pixels."""

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import json
import math
from pathlib import Path
import time

import numpy as np
import pybullet as p
from PIL import Image

import conveyor_kitting as conveyor


INSPECTION_Y = -0.83
CAMERA_HEIGHT = 0.70
FRAME_SIZE = 384
SURFACE_FRAME_SIZE = 384
SURFACE_SIZE = 256
FIELD_OF_VIEW = 36.0


@dataclass(frozen=True)
class CameraCapture:
    png_bytes: bytes
    frame_path: Path
    surface_path: Path
    seconds: float


def perspective_coefficients(corners, size):
    """Map output surface coordinates to the four projected camera corners."""
    output = [(0, 0), (size - 1, 0), (size - 1, size - 1), (0, size - 1)]
    matrix, values = [], []
    for (x, y), (u, v) in zip(output, corners):
        matrix.extend([
            [x, y, 1, 0, 0, 0, -u*x, -u*y],
            [0, 0, 0, x, y, 1, -v*x, -v*y],
        ])
        values.extend([u, v])
    return tuple(np.linalg.solve(np.asarray(matrix), np.asarray(values)))


class InspectionCamera:
    """Photograph a stopped product after it clears the painting-station roof."""

    def __init__(self, captures_root, renderer=p.ER_TINY_RENDERER):
        self.eye = [conveyor.BELT_CENTER[0], INSPECTION_Y, CAMERA_HEIGHT]
        self.view = p.computeViewMatrix(
            self.eye, [self.eye[0], self.eye[1], conveyor.BELT_TOP_Z], [0, 1, 0]
        )
        self.projection = p.computeProjectionMatrixFOV(
            FIELD_OF_VIEW, 1.0, 0.02, 2.0
        )
        self.renderer = renderer
        self.captures_root = Path(captures_root)
        self.session = datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    def create_housing(self):
        """Visual-only gantry, positioned away from the robot's pickup workspace."""
        def box(half_extents, position, color):
            visual = p.createVisualShape(
                p.GEOM_BOX, halfExtents=half_extents, rgbaColor=color
            )
            return p.createMultiBody(
                baseMass=0, baseVisualShapeIndex=visual, basePosition=position
            )

        x, y, z = self.eye
        box([0.018, 0.035, 0.385], [x + 0.28, y, 0.385], [0.28, 0.32, 0.36, 1])
        box([0.16, 0.028, 0.018], [x + 0.14, y, z + 0.09], [0.28, 0.32, 0.36, 1])
        box([0.055, 0.045, 0.035], [x, y, z + 0.055], [0.08, 0.12, 0.18, 1])
        lens = p.createVisualShape(
            p.GEOM_CYLINDER, radius=0.025, length=0.012,
            rgbaColor=[0.10, 0.50, 0.70, 1],
        )
        p.createMultiBody(
            baseMass=0, baseVisualShapeIndex=lens,
            basePosition=[x, y, z + 0.012],
        )
        p.addUserDebugText(
            "INSPECTION CAMERA", [x - 0.12, y, z + 0.13],
            textColorRGB=[0.18, 0.70, 0.95], textSize=1.0,
        )

    def _top_corners(self, position, orientation, projection_matrix=None, size=FRAME_SIZE):
        rotation = np.asarray(p.getMatrixFromQuaternion(orientation)).reshape(3, 3)
        if rotation[2, 2] < math.cos(math.radians(5)):
            raise RuntimeError("Camera capture refused: the product is tilted.")
        view = np.asarray(self.view).reshape(4, 4, order="F")
        projection = np.asarray(self.projection if projection_matrix is None else projection_matrix).reshape(4, 4, order="F")
        half = conveyor.CUBE_HALF_SIZE
        corners = []
        # Known simulation pose is used only to isolate the photographed top face.
        for local in [(-half, half, half), (half, half, half),
                      (half, -half, half), (-half, -half, half)]:
            world, _ = p.multiplyTransforms(position, orientation, local, [0, 0, 0, 1])
            clip = projection @ view @ np.asarray([*world, 1.0])
            if clip[3] <= 0:
                raise RuntimeError("Product is behind the inspection camera.")
            ndc = clip[:3] / clip[3]
            if abs(ndc[0]) >= 0.99 or abs(ndc[1]) >= 0.99 or not -1 < ndc[2] < 1:
                raise RuntimeError("Product top surface is outside the camera frame.")
            corners.append(((ndc[0] + 1)*size/2, (1 - ndc[1])*size/2))
        return corners

    def _render(self, projection, size):
        return p.getCameraImage(
            width=size, height=size,
            viewMatrix=self.view, projectionMatrix=projection,
            renderer=self.renderer, shadow=1,
            lightDirection=[0.1, -0.2, 1.0],
            lightAmbientCoeff=0.65, lightDiffuseCoeff=0.35,
            lightSpecularCoeff=0.0,
            flags=p.ER_SEGMENTATION_MASK_OBJECT_AND_LINKINDEX,
        )

    def _roi_projection(self, corners):
        # Render a high-density sensor region with exactly the same optical center.
        # This changes the sampled pixel window, not the physical camera pose.
        ndc = np.array([(2*x/FRAME_SIZE - 1, 1 - 2*y/FRAME_SIZE) for x, y in corners])
        lower, upper = ndc.min(axis=0), ndc.max(axis=0)
        margin = (upper - lower)*0.04
        lower, upper = np.maximum(-1, lower-margin), np.minimum(1, upper+margin)
        crop = np.eye(4)
        crop[0, 0], crop[1, 1] = 2/(upper-lower)
        crop[0, 3], crop[1, 3] = -(upper+lower)/(upper-lower)
        projection = np.asarray(self.projection).reshape(4, 4, order="F")
        return (crop @ projection).flatten(order="F").tolist()

    def capture(self, cube, cycle):
        started = time.monotonic()
        position, orientation = p.getBasePositionAndOrientation(cube)
        if abs(position[1] - INSPECTION_Y) > 0.006:
            raise RuntimeError("Product has not reached the camera stopping line.")
        linear, angular = p.getBaseVelocity(cube)
        if np.linalg.norm(linear) > 0.02 or np.linalg.norm(angular) > 0.10:
            raise RuntimeError("Product must be stationary for a sharp camera capture.")
        corners = self._top_corners(position, orientation)
        _, _, rgba, _, _ = self._render(self.projection, FRAME_SIZE)
        rgb = np.asarray(rgba, dtype=np.uint8).reshape(FRAME_SIZE, FRAME_SIZE, 4)[:, :, :3]
        frame = Image.fromarray(rgb)
        roi_projection = self._roi_projection(corners)
        _, _, roi_rgba, _, segmentation = self._render(roi_projection, SURFACE_FRAME_SIZE)
        roi = Image.fromarray(np.asarray(roi_rgba, dtype=np.uint8).reshape(
            SURFACE_FRAME_SIZE, SURFACE_FRAME_SIZE, 4
        )[:, :, :3])
        roi_corners = self._top_corners(position, orientation, roi_projection, SURFACE_FRAME_SIZE)
        coefficients = perspective_coefficients(roi_corners, SURFACE_SIZE)
        surface = roi.transform(
            (SURFACE_SIZE, SURFACE_SIZE), Image.Transform.PERSPECTIVE,
            coefficients, resample=Image.Resampling.BICUBIC,
        )
        ids = np.asarray(segmentation, dtype=np.int64).reshape(SURFACE_FRAME_SIZE, SURFACE_FRAME_SIZE)
        cube_mask = ((ids >= 0) & ((ids & 0xFFFFFF) == cube)).astype(np.uint8)*255
        visible = Image.fromarray(cube_mask).transform(
            (SURFACE_SIZE, SURFACE_SIZE), Image.Transform.PERSPECTIVE,
            coefficients, resample=Image.Resampling.NEAREST,
        )
        # Ignore a two-pixel raster boundary, not missing interior surface areas.
        coverage = float(np.mean(np.asarray(visible)[2:-2, 2:-2] > 0))
        if coverage < 0.99:
            raise RuntimeError(
                f"Camera view obstructed ({coverage:.0%} visible); no inspection sent."
            )
        buffer = BytesIO()
        surface.save(buffer, format="PNG")
        pixels = buffer.getvalue()
        directory = self.captures_root / self.session
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"product-{cycle:06d}-{time.time_ns()}"
        frame_path = directory / f"{stem}-frame.png"
        surface_path = directory / f"{stem}-top.png"
        frame.save(frame_path)
        surface_path.write_bytes(pixels)
        (directory / f"{stem}.json").write_text(json.dumps({
            "cycle": cycle,
            "camera_position": self.eye,
            "product_position": position,
            "product_orientation": orientation,
            "top_corners_pixels": corners,
            "surface_roi_projection": roi_projection,
            "visible_fraction": coverage,
            "frame": frame_path.name,
            "inspection_image": surface_path.name,
        }, indent=2), encoding="utf-8")
        return CameraCapture(pixels, frame_path, surface_path, time.monotonic() - started)
