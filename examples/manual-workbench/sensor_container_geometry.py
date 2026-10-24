# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
import numpy as np


def _hull(points):
    """Convex hull of measured XY points, counterclockwise."""
    points = sorted(set(map(tuple, points)))

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    halves = []
    for ordered in (points, points[::-1]):
        half = []
        for point in ordered:
            while len(half) >= 2 and cross(half[-2], half[-1], point) <= 0:
                half.pop()
            half.append(point)
        halves.extend(half[:-1])
    return np.asarray(halves, dtype=float)


def run(frames, params):
    """Measure a visible opening; semantic point selection belongs to the caller."""
    step = params.get("step", -1)
    frame = (
        frames[-1]
        if step == -1
        else next((f for f in frames if f["step"] == step), None)
    )
    if frame is None:
        return {
            "error": "step unavailable",
            "available_steps": [f["step"] for f in frames],
        }
    camera = params.get("camera", "agentview")
    data = frame["cameras"][camera].get("high")
    if data is None:
        return {
            "error": "high-resolution RGB/world observation not recorded",
            "step": frame["step"],
            "camera": camera,
            "resolution": "high",
        }
    world = data["world"]
    h, w = world.shape[:2]
    image_h, image_w = params.get("image_size", [1024, 1024])
    if data["rgb"].shape[:2] != (h, w) or (image_h, image_w) != (h, w):
        return {
            "error": "image_size must match the recorded high-resolution RGB/world pair",
            "step": frame["step"],
            "camera": camera,
            "recorded_image_size": [h, w],
        }
    eef = np.asarray(frame["proprio"]["robot0_eef_pos"], dtype=float)

    def sample(point):
        if not (0 <= point[0] < image_h and 0 <= point[1] < image_w):
            return {"pixel_rc": point, "error": "pixel outside declared image_size"}
        row, col = point
        patch = world[
            max(0, row - 1) : min(h, row + 2), max(0, col - 1) : min(w, col + 2), :3
        ].reshape(-1, 3)
        valid = patch[
            np.isfinite(patch).all(axis=1) & (np.abs(patch).sum(axis=1) > 1e-6)
        ]
        anchor = world[row, col, :3]
        if not np.isfinite(anchor).all() or np.abs(anchor).sum() <= 1e-6:
            return {"pixel_rc": point, "error": "invalid selected-pixel depth"}
        # A rim patch often also sees the table behind it. Keep the local
        # surface attached to the selected pixel rather than average across it.
        count = len(valid)
        valid = valid[np.linalg.norm(valid - anchor, axis=1) <= 0.025]
        if len(valid) < 3:
            return {"pixel_rc": point, "error": "insufficient locally consistent depth"}
        low, median, high = np.quantile(valid, [0.1, 0.5, 0.9], axis=0)
        spread = float(np.linalg.norm(high - low))
        return {
            "pixel_rc": point,
            "world_xyz": median.tolist(),
            "spread_m": spread,
            "excluded_neighbor_count": count - len(valid),
            "quality": "mixed_surface" if spread > 0.04 else "locally_consistent",
        }

    samples = [sample(p) for p in params["rim_points"]]
    result = {
        "step": frame["step"],
        "camera": camera,
        "input_image_size": [image_h, image_w],
        "depth_image_size": [h, w],
        "resolution": "high",
        "source_artifacts": data.get("source_artifacts", {}),
        "coordinates": "world XYZ metres; world +Z is up",
        "rim_samples": samples,
        "limitations": "Caller identifies the inner rim and object. Local depth consistency does not verify identity. Sampled polygon is not the full free space; no hidden floor, collision clearance, grasp or task success is inferred.",
    }
    if any("error" in s or s["quality"] != "locally_consistent" for s in samples):
        result["status"] = "resample_flagged_points"
        result["guidance"] = (
            "Only replace flagged pixels with nearby visible inner-rim pixels; do not repeat all measurements. Avoid background and cloth wall below the rim."
        )
        return result
    xyz = np.asarray([s["world_xyz"] for s in samples])
    if np.ptp(xyz[:, 2]) > 0.06:
        # A strict majority at a common height can exclude a stray table pixel
        # without asking the planner to measure the entire opening again.
        groups = [
            np.flatnonzero((xyz[:, 2] >= z) & (xyz[:, 2] <= z + 0.04))
            for z in xyz[:, 2]
        ]
        inliers = max(groups, key=len)
        if len(inliers) < max(4, int(np.ceil(0.75 * len(xyz)))):
            return {
                **result,
                "status": "inconsistent_rim",
                "guidance": "No dominant rim-height group. Replace pixels on the floor, background or occluder with visible inner-rim pixels.",
            }
        result["excluded_rim_indices"] = [
            i for i in range(len(xyz)) if i not in inliers
        ]
        result["height_consensus"] = (
            "Excluded minority at a different height; opening uses only the remaining points. This does not verify semantic identity."
        )
        xyz = xyz[inliers]
    hull = _hull(xyz[:, :2])
    if len(hull) < 3:
        return {**result, "status": "insufficient_opening_coverage"}
    following = np.roll(hull, -1, axis=0)
    cross = hull[:, 0] * following[:, 1] - following[:, 0] * hull[:, 1]
    area = float(cross.sum() / 2)
    if area < 0.0001 or np.ptp(xyz[:, 2]) > 0.06:
        return {
            **result,
            "status": "inconsistent_rim",
            "guidance": "Select points around the same approximately horizontal opening, not its floor or side walls.",
        }
    center = ((hull + following) * cross[:, None]).sum(axis=0) / (6 * area)
    rim_z = float(np.max(xyz[:, 2]))
    result.update(
        status="measured",
        opening={
            "center_xy": center.tolist(),
            "sampled_polygon_xy": hull.tolist(),
            "rim_top_z": rim_z,
            "rim_z_range": [float(xyz[:, 2].min()), rim_z],
            "sampled_area_m2": area,
        },
        eef_to_opening_xy=(center - eef[:2]).tolist(),
        guidance="Use this measured center for the opening, not a depth point on its visible inner wall. Reuse it while the container stays stationary; robot movement alone does not require remeasuring a static container. Check returned action images for changes.",
    )
    if "object_bottom_point" in params:
        point = sample(params["object_bottom_point"])
        result["object_bottom_sample"] = point
        if "error" not in point and point["quality"] == "locally_consistent":
            bottom = np.asarray(point["world_xyz"])
            edges = following - hull
            offset = bottom[:2] - hull
            margins = (
                edges[:, 0] * offset[:, 1] - edges[:, 1] * offset[:, 0]
            ) / np.linalg.norm(edges, axis=1)
            result["relation"] = {
                "sample_to_opening_center_xy": (center - bottom[:2]).tolist(),
                "sample_above_rim_m": float(bottom[2] - rim_z),
                "sample_inside_rim_polygon": bool(np.min(margins) > 0),
                "sample_edge_margin_m": float(np.min(margins)),
                "eef_to_sample_xyz": (bottom - eef).tolist(),
                "interpretation": "Point-only relation, not full-object clearance. Positive above_rim means above sampled rim; negative means below. If the point is occluded or belongs to background, discard this relation. A point inside/below the rim does not prove the object has been released.",
            }
    return result
