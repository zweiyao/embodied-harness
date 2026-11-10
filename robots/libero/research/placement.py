# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Review visible placement geometry before one opt-in XY alignment."""

from __future__ import annotations

import io
import threading
import uuid
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import Field

from robots.libero.eef_control import EefControl
from rpent.tools import ToolResult, tool

Pixel = Annotated[
    list[Annotated[int, Field(ge=0, strict=True)]], Field(min_length=2, max_length=2)
]


def _points(value, count, shape):
    points = np.asarray(value)
    if (
        points.ndim != 2
        or points.shape[1] != 2
        or not count[0] <= len(points) <= count[1]
        or points.dtype.kind not in "iu"
        or (points < 0).any()
        or (points >= np.asarray(shape)).any()
    ):
        raise ValueError(
            "Use integer [row, column] pixels inside the actual high image"
        )
    return points.astype(float)


def _sample(world, pixel):
    row, col = np.rint(pixel).astype(int)
    h, w = world.shape[:2]
    anchor = world[row, col, :3]
    patch = world[
        max(0, row - 1) : min(h, row + 2), max(0, col - 1) : min(w, col + 2), :3
    ].reshape(-1, 3)
    if not np.isfinite(anchor).all() or np.linalg.norm(anchor) <= 1e-6:
        raise ValueError("Selected pixel has invalid depth")
    valid = patch[
        np.isfinite(patch).all(axis=1)
        & (np.linalg.norm(patch - anchor, axis=1) <= 0.025)
    ]
    if len(valid) < 3:
        raise ValueError("Selected pixel lacks locally consistent depth")
    low, median, high = np.quantile(valid, [0.1, 0.5, 0.9], axis=0)
    spread = float(np.linalg.norm(high - low))
    if spread > 0.02:
        raise ValueError("Selected surface patch has mixed depth")
    return median, spread


def placement_geometry(
    high: dict[str, Any],
    eef: np.ndarray,
    held_feature: list[int],
    target_region: list[list[int]],
    plane_samples: list[list[int]],
) -> dict[str, Any]:
    """Compute only a caller-selected surface/region relation; no semantic verdict."""
    rgb, world = high["rgb"], high["world"]
    h, w = rgb.shape[:2]
    if world.shape != (h, w, 3):
        raise ValueError("Recorded high RGB/world shapes differ")
    calibration = high["calibration"]
    if (calibration["height"], calibration["width"]) != (h, w):
        raise ValueError("High calibration dimensions differ")
    k = np.asarray(calibration["intrinsic_K"], dtype=float)
    c2w = np.asarray(calibration["extrinsic_cam2world"], dtype=float)
    if (
        k.shape != (3, 3)
        or c2w.shape != (4, 4)
        or not np.isfinite(k).all()
        or not np.isfinite(c2w).all()
        or abs(np.linalg.det(k)) <= 1e-12
    ):
        raise ValueError("Invalid high camera calibration")
    rotation = c2w[:3, :3]
    if (
        not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6, rtol=0)
        or not np.isclose(np.linalg.det(rotation), 1, atol=1e-6, rtol=0)
        or not np.allclose(c2w[3], [0, 0, 0, 1], atol=1e-9, rtol=0)
    ):
        raise ValueError("Invalid camera-to-world rigid transform")
    obj_rc = _points([held_feature], (1, 1), (h, w))[0]
    region_rc = _points(target_region, (4, 8), (h, w))
    plane_rc = _points(plane_samples, (4, 8), (h, w))
    obj, object_spread = _sample(world, obj_rc)
    sampled = [_sample(world, p) for p in plane_rc]
    anchors = np.array([p[0] for p in sampled])
    origin = anchors.mean(axis=0)
    _, singular, vh = np.linalg.svd(anchors - origin)
    normal = vh[-1]
    normal *= 1 if normal[2] >= 0 else -1
    residual = float(np.abs((anchors - origin) @ normal).max())
    if singular[1] <= 1e-6 or residual > 0.01 or normal[2] < np.cos(np.deg2rad(15)):
        raise ValueError(
            "Plane is degenerate, inconsistent or not approximately horizontal"
        )
    # Pixel-to-camera convention exactly matches tools._world_from_depth.
    pixels = np.c_[region_rc[:, 1], region_rc[:, 0], np.ones(len(region_rc))]
    rays = pixels @ np.linalg.inv(k).T @ c2w[:3, :3].T
    camera_origin = c2w[:3, 3]
    denominator = rays @ normal
    if np.any(np.abs(denominator) <= 1e-9):
        raise ValueError("Region ray is parallel to the selected plane")
    distances = ((origin - camera_origin) @ normal) / denominator
    if np.any(distances <= 0):
        raise ValueError("Region intersects the selected plane behind the camera")
    region = camera_origin + distances[:, None] * rays
    xy = region[:, :2]
    following = np.roll(xy, -1, axis=0)
    edges = following - xy
    turns = edges[:, 0] * np.roll(edges[:, 1], -1) - edges[:, 1] * np.roll(
        edges[:, 0], -1
    )
    # Explicit ordered convex subset only; never repair/cross-sort/hull a bad polygon.
    if not (np.all(turns > 1e-10) or np.all(turns < -1e-10)):
        raise ValueError(
            "Select a non-crossing convex visible subregion in boundary order"
        )
    offsets = xy[None, :, :] - xy[:, None, :]
    sides = edges[:, 0, None] * offsets[:, :, 1] - edges[:, 1, None] * offsets[:, :, 0]
    if not (np.all(sides >= -1e-10) or np.all(sides <= 1e-10)):
        raise ValueError("Selected region crosses itself or is not convex")
    cross = xy[:, 0] * following[:, 1] - following[:, 0] * xy[:, 1]
    twice_area = cross.sum()
    if abs(twice_area) <= 1e-10:
        raise ValueError("Selected region has no usable area")
    center_xy = ((xy + following) * cross[:, None]).sum(axis=0) / (3 * twice_area)
    center_z = origin[2] - np.dot(normal[:2], center_xy - origin[:2]) / normal[2]
    center = np.r_[center_xy, center_z]
    target = np.array(eef, dtype=float)
    if target.shape != (3,) or not np.isfinite(target).all():
        raise ValueError("Current EEF position is unavailable")
    target[:2] += center_xy - obj[:2]
    projected = k @ (rotation.T @ (center - camera_origin))
    center_rc = (projected[:2] / projected[2])[::-1]
    return {
        "held_feature_xyz": obj.tolist(),
        "held_feature_patch_spread_m": object_spread,
        "plane_sample_xyz": anchors.tolist(),
        "plane_patch_spread_m": [float(p[1]) for p in sampled],
        "plane_max_residual_m": residual,
        "plane_normal_xyz": normal.tolist(),
        "selected_region_xyz": region.tolist(),
        "selected_region_center_xyz": center.tolist(),
        "selected_region_center_pixel_rc": center_rc.tolist(),
        "eef_target_xyz_keep_height": target.tolist(),
        "xy_correction_m": float(np.linalg.norm(center_xy - obj[:2])),
        "semantic_status": "caller_selected_not_verified",
        "limits": "Selected feature is not a footprint center; selected region is not the full opening. No holding, height clearance, path, release or task-success conclusion.",
    }


def _overlays(high, held_feature, target_region, plane_samples, center_rc=None):
    """Return original-sized numbered image and a labeled crop, never JSON image data."""
    from PIL import Image, ImageDraw

    image = Image.fromarray(high["rgb"]).copy()
    draw = ImageDraw.Draw(image)
    h, w = high["rgb"].shape[:2]
    region = _points(target_region, (4, 8), (h, w))
    plane = _points(plane_samples, (4, 8), (h, w))
    obj = _points([held_feature], (1, 1), (h, w))
    draw.line(
        [(float(c), float(r)) for r, c in [*region, region[0]]], fill="cyan", width=3
    )
    for prefix, points, color in (
        ("O", obj, "yellow"),
        ("P", plane, "magenta"),
        ("R", region, "cyan"),
    ):
        for index, (r, c) in enumerate(points):
            draw.ellipse((c - 5, r - 5, c + 5, r + 5), outline=color, width=2)
            draw.text(
                (c + 6, r + 3),
                f"{prefix}{index}",
                fill=color,
                stroke_width=1,
                stroke_fill="black",
            )
    if center_rc is not None:
        r, c = center_rc
        draw.line([(c - 8, r), (c + 8, r)], fill="lime", width=3)
        draw.line([(c, r - 8), (c, r + 8)], fill="lime", width=3)
        draw.text((c + 9, r + 3), "C", fill="lime", stroke_width=1, stroke_fill="black")
    all_rc = np.vstack([obj, region, plane])
    lo = np.maximum(np.floor(all_rc.min(axis=0) - 24).astype(int), 0)
    hi = np.minimum(np.ceil(all_rc.max(axis=0) + 25).astype(int), [h, w])
    bounds = [int(lo[1]), int(lo[0]), int(hi[1]), int(hi[0])]
    crop = image.crop(tuple(bounds))
    output = []
    for picture in (image, crop):
        encoded = io.BytesIO()
        picture.save(encoded, format="PNG")
        output.append(encoded.getvalue())
    return output, bounds


class PlacementTools:
    """Opt-in review then one gripper-preserving XY alignment; no autonomous release."""

    def __init__(self, sensors, primitives):
        self.sensors, self.primitives = sensors, primitives
        self.pending = None
        self.preview_lock = threading.Lock()

    @tool(readonly=True)
    def preview_placement(
        self,
        step: Annotated[int, Field(ge=0)],
        camera: Literal["agentview", "wrist"],
        held_feature: Pixel,
        target_region: Annotated[list[Pixel], Field(min_length=4, max_length=8)],
        plane_samples: Annotated[list[Pixel], Field(min_length=4, max_length=8)],
    ) -> ToolResult:
        """Preview held-feature alignment to a visibly suitable plate/opening subregion.

        Use integer [row,column] pixels in the latest calibrated high image. O is a
        visible held-object feature; R outlines a fully visible convex usable
        subregion in boundary order; P marks visible support/rim plane samples.
        Inspect returned O/P/R marks before align_placement. This is conditional
        geometry, not identity, whole-object clearance or grasp verification.
        """
        # Toolkit excludes actions while readonly calls are active; serialize two
        # simultaneous previews so only the last completed preview remains usable.
        with self.preview_lock:
            return self._preview(
                step, camera, held_feature, target_region, plane_samples
            )

    def _preview(self, step, camera, held_feature, target_region, plane_samples):
        self.pending = None
        frames = self.sensors.frames()
        if not frames or step != frames[-1]["step"]:
            return ToolResult(
                data={
                    "status": "refresh_required",
                    "reason": "Use an explicit latest step",
                }
            )
        frame = frames[-1]
        if camera not in {"agentview", "wrist"}:
            return ToolResult(
                data={"status": "unavailable", "reason": "Unknown calibrated camera"}
            )
        high = frame["cameras"][camera].get("high")
        if high is None:
            return ToolResult(
                data={
                    "status": "unavailable",
                    "reason": "High RGB/world/calibration required",
                }
            )
        try:
            images, crop = _overlays(high, held_feature, target_region, plane_samples)
        except (KeyError, ValueError, np.linalg.LinAlgError) as exc:
            return ToolResult(data={"status": "resample_required", "reason": str(exc)})
        result = {
            "step": step,
            "camera": camera,
            "image_size": list(high["rgb"].shape[:2]),
            "crop_bounds_xyxy": crop,
            "crop_coordinate_rule": "Inputs remain integer [row,column] in the full image",
            "labels": {
                "O": "held feature",
                "P": "support/rim plane samples",
                "R": "visible target subregion",
            },
        }
        try:
            geometry = placement_geometry(
                high,
                frame["proprio"]["robot0_eef_pos"],
                held_feature,
                target_region,
                plane_samples,
            )
        except (KeyError, ValueError, np.linalg.LinAlgError) as exc:
            return ToolResult(
                data={**result, "status": "resample_required", "reason": str(exc)},
                images=images,
            )
        result.update(geometry)
        result["labels"]["C"] = "computed target in the selected region"
        images, _ = _overlays(
            high,
            held_feature,
            target_region,
            plane_samples,
            geometry["selected_region_center_pixel_rc"],
        )
        if geometry["xy_correction_m"] > 0.30:
            return ToolResult(
                data={
                    **result,
                    "status": "requires_waypoint",
                    "reason": "Choose an intermediate carry-height translation, then preview again",
                },
                images=images,
            )
        preview_id = uuid.uuid4().hex
        self.pending = {
            "id": preview_id,
            "step": step,
            "camera": camera,
            "pose": {
                k: np.array(v, dtype=float).copy() for k, v in frame["proprio"].items()
            },
            "calibration": {
                k: np.asarray(high["calibration"][k]).copy()
                for k in ("intrinsic_K", "extrinsic_cam2world")
            },
            "target": list(geometry["eef_target_xyz_keep_height"]),
        }
        return ToolResult(
            data={**result, "status": "review_required", "preview_id": preview_id},
            images=images,
        )

    @tool
    def align_placement(self, preview_id: str) -> ToolResult:
        """Accept the displayed O/P/R roles and execute its frozen XY target once.

        Reselect with preview_placement if any mark is on the wrong surface or
        region. Holds current EEF height, orientation and gripper target through
        translate_to; inspect new images before lowering or releasing.
        """
        pending, self.pending = self.pending, None
        if pending is None or pending["id"] != preview_id:
            return ToolResult(data={"error": "No matching unused preview"})
        if self.primitives.env.terminated or self.primitives.env.truncated:
            return ToolResult(data={"error": "Environment episode ended"})
        frame = self.sensors.frames()[-1]
        if frame["step"] != pending["step"]:
            return ToolResult(
                data={"error": "Preview is stale; reselect in the latest image"}
            )
        high = frame["cameras"][pending["camera"]].get("high")
        if high is None or any(
            not np.array_equal(high["calibration"][k], v)
            for k, v in pending["calibration"].items()
        ):
            return ToolResult(data={"error": "Preview camera calibration changed"})
        raw = self.primitives.env.raw_obs()
        if any(
            not np.allclose(raw[k], v, rtol=0, atol=1e-7)
            for k, v in pending["pose"].items()
        ):
            return ToolResult(data={"error": "Robot pose changed; preview again"})
        result = EefControl(self.primitives).translate_to(pending["target"])
        result.data.update(
            name="align_placement",
            preview_id=preview_id,
            semantic_status="model_accepted_not_verified",
        )
        return result
