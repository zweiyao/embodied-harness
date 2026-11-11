# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
import collections
import json
import pathlib
import statistics

import numpy as np

ROOT = pathlib.Path("/home/zwy/work/embodied_harness/experiments")


def load(names):
    rows = []
    for n in names:
        rows += json.loads((ROOT / n / "results.json").read_text())
    return [
        r
        for r in rows
        if r.get("official_success") is not None
        and r.get("classification") != "unexpected"
    ]


groups = {
    "flash": load(
        [
            "libero10-task-qwenflash-3000s-50-20261106",
            "libero10-task-qwenflash-1500s-continuation-20261106",
        ]
    ),
    "astra": load(
        [
            "libero10-task-astra-50-20261105",
            "libero10-task-astra-50-20261105/continuation",
            "libero10-task-astra-50-20261105/resume34",
            "libero10-task-astra-50-20261105/resume32",
        ]
    ),
}
out = {}
for group, rows in groups.items():
    records = []
    replay = collections.Counter()
    projection = []
    for r in rows:
        p = pathlib.Path(r["path"])
        ev = [json.loads(x) for x in (p / "events.jsonl").read_text().splitlines()]
        req = {}
        calls = []
        errors = []
        moves = []
        picks = []
        mem = []
        single = []
        regions = []
        region_records = []
        world_cache = {}
        turn = 0
        first_action = None
        for e in ev:
            q = e["payload"]
            k = e["kind"]
            if k == "model_request":
                turn += 1
            if k == "tool_request":
                req[q["call_id"]] = q
                calls.append(q)
                if (
                    q["name"]
                    in [
                        "move_to",
                        "move_pose",
                        "pi0_pick",
                        "pi0_doubled",
                        "release",
                        "set_gripper",
                        "rotate_pitch",
                        "rotate_wrist",
                    ]
                    and first_action is None
                ):
                    first_action = turn
                if q["name"] == "read_text_file":
                    mem.append(q["arguments"].get("path", ""))
            if k != "tool_response":
                continue
            z = q.get("result", {})
            a = req.get(q["call_id"], {}).get("arguments", {})
            name = q["name"]
            if not isinstance(z, dict):
                continue
            if z.get("error"):
                errors.append(
                    {
                        "name": name,
                        "error": z["error"],
                        "args": a,
                        "details": z.get("errors"),
                    }
                )
            if name in ["move_to", "move_pose"] and "log" in z:
                log = z["log"]
                res = log.get("result", {})
                cmd = log.get("command", {})
                dist = res.get("final_dist_m")
                tol = cmd.get("tol", 0.01)
                moves.append(
                    {
                        "step": z["step"],
                        "distance": dist,
                        "tol": tol,
                        "target": cmd.get("xyz"),
                        "final": res.get("final_eef_pos"),
                        "steps_used": res.get("steps_used"),
                        "max_steps": cmd.get("max_steps", 80),
                        "name": name,
                    }
                )
            if name == "pi0_pick" and "log" in z:
                picks.append(z["log"].get("result", {}))
            if name == "back_project" and "world_xyz" in z:
                single.append((a, z))
            if name == "back_project" and "center_xyz" in z:
                regions.append(
                    float(
                        np.linalg.norm(
                            np.array(z["center_xyz"])[:2]
                            - np.array(z["median_xyz"])[:2]
                        )
                    )
                )
                region_records.append((a, z))
        if group == "flash":
            for a, z in single:
                artifact = z["source_artifact"]
                step = z["step"]
                key = (artifact, step)
                if key not in world_cache:
                    f = p / artifact / f"{step:02d}.npz"
                    world_cache[key] = np.load(f)["array"]
                world = world_cache[key]
                rr, cc = z["pixel"]
                expected = np.round(world[rr, cc].astype(float), 4)
                replay["single_calls"] += 1
                if np.allclose(expected, z["world_xyz"], atol=1e-7):
                    replay["exact_matches"] += 1
                meta = json.loads(
                    (
                        p
                        / (
                            z["camera"]
                            + "_metadata"
                            + ("_high" if z["resolution"] == "high" else "")
                            + ".json"
                        )
                        / f"{step:02d}.json"
                    ).read_text()
                )
                cam = (
                    np.linalg.inv(np.array(meta["extrinsic_cam2world"]))
                    @ np.r_[np.array(z["world_xyz"]), 1]
                )
                pix = np.array(meta["intrinsic_K"]) @ cam[:3]
                uv = pix[:2] / pix[2]
                projection.append(float(np.linalg.norm(uv - [cc, rr])))
        if group == "flash":
            for a, z in region_records:
                key = (z["source_artifact"], z["step"])
                if key not in world_cache:
                    world_cache[key] = np.load(
                        p / z["source_artifact"] / f"{z['step']:02d}.npz"
                    )["array"]
                rr = z["row_range"]
                cc = z["col_range"]
                w = (
                    world_cache[key][rr[0] : rr[1], cc[0] : cc[1]]
                    .reshape(-1, 3)
                    .astype(float)
                )
                w = w[np.isfinite(w).all(axis=1) & (np.abs(w).sum(axis=1) > 1e-6)]
                if a.get("z_min") is not None:
                    w = w[w[:, 2] >= a["z_min"]]
                if a.get("z_max") is not None:
                    w = w[w[:, 2] <= a["z_max"]]
                center = np.round(
                    [
                        (w[:, 0].min() + w[:, 0].max()) / 2,
                        (w[:, 1].min() + w[:, 1].max()) / 2,
                        np.median(w[:, 2]),
                    ],
                    4,
                )
                replay["region_calls"] += 1
                if np.allclose(center, z["center_xyz"], atol=1e-7) and np.allclose(
                    np.round(np.median(w, axis=0), 4), z["median_xyz"], atol=1e-7
                ):
                    replay["region_exact_matches"] += 1
        names = collections.Counter(x["name"] for x in calls)
        records.append(
            {
                "task": r["task"],
                "seed": r["seed"],
                "run_id": r["run_id"],
                "success": r.get("evaluation_success", r["official_success"]),
                "status": r["status"],
                "turns": r["turns"],
                "seconds": r["elapsed_s"],
                "actions": r.get("actions"),
                "first_action_request": first_action if group == "flash" else None,
                "calls": dict(names),
                "error_count": len(errors),
                "errors": errors,
                "reads": len(mem),
                "unique_reads": len(set(mem)),
                "moves": moves,
                "picks": {
                    "total": len(picks),
                    "reported_success": sum(x.get("success") is True for x in picks),
                },
                "region_center_median_over_5cm": sum(x > 0.05 for x in regions),
            }
        )
    counts = collections.Counter()
    err = collections.Counter()
    for x in records:
        counts.update(x["calls"])
        err.update(e["name"] for e in x["errors"])
    summary = {
        "runs": len(records),
        "total_calls": sum(counts.values()),
        "calls": dict(counts),
        "error_calls": dict(err),
        "runs_with_errors": sum(x["error_count"] > 0 for x in records),
        "runs_without_errors_failed": sum(
            x["error_count"] == 0 and not x["success"] for x in records
        ),
        "reads": sum(x["reads"] for x in records),
        "repeated_reads": sum(x["reads"] - x["unique_reads"] for x in records),
        "move_calls": sum(len(x["moves"]) for x in records),
        "moves_over_3cm": sum(
            m["distance"] is not None and m["distance"] > 0.03
            for x in records
            for m in x["moves"]
        ),
        "pick_calls": sum(x["picks"]["total"] for x in records),
        "pick_reported_success": sum(x["picks"]["reported_success"] for x in records),
    }
    if group == "flash":
        summary.update(
            zero_action_runs=sum(x["actions"] == 0 for x in records),
            first_action_request_median=statistics.median(
                x["first_action_request"]
                for x in records
                if x["first_action_request"] is not None
            ),
            replay=dict(replay),
            reprojection_pixel_median=statistics.median(projection),
            reprojection_pixel_max=max(projection),
        )
    out[group] = {"summary": summary, "runs": records}
print(json.dumps(out, ensure_ascii=False, indent=2))
