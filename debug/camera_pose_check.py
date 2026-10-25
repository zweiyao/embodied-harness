# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Standalone camera-cache check; no UniVTAC task, robot or pilot reservation.

Run with the independent Isaac Python/wrapper and its normal launch environment.
This creates one empty simulation stage and two cameras, then translates their
parent transforms by 0.10 m. camera-check.json is written before Kit closes and
is authoritative even if Kit exits the process directly.
"""

import argparse
import gc
import json
import sys
import traceback
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    result = {"passed": False, "status": "starting", "pilot_episode": False}
    output = args.output_dir / "camera-check.json"
    output.write_text(json.dumps(result, indent=2))
    app = sim = None
    cameras = {}
    cleanup_failed = False
    try:
        from isaaclab.app import AppLauncher

        app = AppLauncher(
            {"headless": True, "enable_cameras": True, "device": args.device}
        ).app

        import isaaclab.sim as sim_utils
        import numpy as np
        import omni.usd
        from isaaclab.sensors import TiledCamera, TiledCameraCfg
        from pxr import Gf, UsdGeom

        sim = sim_utils.SimulationContext(
            sim_utils.SimulationCfg(dt=1 / 120, device=args.device)
        )
        stage = omni.usd.get_context().get_stage()
        surface = sim_utils.CuboidCfg(
            size=(4.0, 4.0, 0.05),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.4, 0.6, 0.8)),
        )
        surface.func("/World/Surface", surface, translation=(0.0, 0.0, -0.1))
        light = sim_utils.DomeLightCfg(intensity=1000.0)
        light.func("/World/Light", light)
        translations = {}
        for name, live, y in (("cached", False, -0.2), ("live", True, 0.2)):
            parent = UsdGeom.Xform.Define(stage, f"/World/{name}")
            translations[name] = parent.AddTranslateOp()
            translations[name].Set(Gf.Vec3d(0.0, y, 1.0))
            cameras[name] = TiledCamera(
                TiledCameraCfg(
                    prim_path=f"/World/{name}/Camera",
                    update_latest_camera_pose=live,
                    width=96,
                    height=64,
                    data_types=["rgb", "depth"],
                    update_period=1 / 120,
                    spawn=sim_utils.PinholeCameraCfg(clipping_range=(0.01, 20.0)),
                    offset=TiledCameraCfg.OffsetCfg(convention="opengl"),
                )
            )
        # This initializes only the standalone camera stage, never a task reset.
        sim.reset()

        def render(count):
            for _ in range(count):
                sim.render()
                for camera in cameras.values():
                    camera.update(1 / 120, force_recompute=True)

        def snapshot(camera):
            data = camera.data
            matrix = UsdGeom.XformCache().GetLocalToWorldTransform(
                stage.GetPrimAtPath(camera.cfg.prim_path)
            )
            world_q = matrix.ExtractRotationQuat()
            ros_q = world_q * Gf.Quatd(0.0, Gf.Vec3d(1.0, 0.0, 0.0))
            return {
                "position_w": data.pos_w[0].cpu().numpy().tolist(),
                "quaternion_wxyz": data.quat_w_ros[0].cpu().numpy().tolist(),
                "stage_position_w": list(matrix.ExtractTranslation()),
                "stage_ros_quaternion_wxyz": [ros_q.GetReal(), *ros_q.GetImaginary()],
                "rgb_shape": list(data.output["rgb"].shape),
                "finite_depth_pixels": int(data.output["depth"].isfinite().sum()),
            }

        render(12)
        before = {name: snapshot(camera) for name, camera in cameras.items()}
        for name, y in (("cached", -0.2), ("live", 0.2)):
            translations[name].Set(Gf.Vec3d(0.1, y, 1.0))
        render(6)
        after = {name: snapshot(camera) for name, camera in cameras.items()}
        checks = {}
        for name in cameras:
            observed_delta = np.subtract(
                after[name]["position_w"], before[name]["position_w"]
            )
            stage_delta = np.subtract(
                after[name]["stage_position_w"], before[name]["stage_position_w"]
            )
            checks[f"{name}_stage_moved_0_10_m"] = bool(
                np.allclose(stage_delta, [0.1, 0, 0], atol=1e-5)
            )
            expected_delta = [0.1, 0, 0] if name == "live" else [0, 0, 0]
            checks[f"{name}_expected_cache_behavior"] = bool(
                np.allclose(observed_delta, expected_delta, atol=1e-5)
            )
            checks[f"{name}_rgb_and_depth_available"] = (
                after[name]["rgb_shape"] == [1, 64, 96, 3]
                and after[name]["finite_depth_pixels"] > 0
            )
        live = after["live"]
        checks["live_pose_matches_stage"] = bool(
            np.allclose(live["position_w"], live["stage_position_w"], atol=1e-5)
        )
        q = np.asarray(live["quaternion_wxyz"])
        expected_q = np.asarray(live["stage_ros_quaternion_wxyz"])
        checks["live_ros_orientation_matches_stage"] = bool(
            min(np.linalg.norm(q - expected_q), np.linalg.norm(q + expected_q)) < 1e-5
        )
        result.update(
            status="completed",
            passed=all(checks.values()),
            before=before,
            after=after,
            checks=checks,
        )
    except BaseException as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        (args.output_dir / "camera-check-error.txt").write_text(traceback.format_exc())
        traceback.print_exc()
        sys.stderr.flush()
    finally:
        output.write_text(json.dumps(result, indent=2, allow_nan=False))
        print(json.dumps(result), flush=True)
        if app is not None:
            cleanup = {"stage": "starting", "app_close_returned": False}
            cleanup_path = args.output_dir / "camera-cleanup.json"

            def mark_cleanup(stage):
                cleanup["stage"] = stage
                cleanup_path.write_text(json.dumps(cleanup, indent=2))

            try:
                if sim is not None:
                    # This fork's standalone STOP callback otherwise renders
                    # forever when close_stage stops the timeline.
                    mark_cleanup("unsubscribe_simulation_callbacks")
                    sim.clear_all_callbacks()
                    sim.clear_instance()
                mark_cleanup("release_camera_annotators")
                cameras.clear()
                gc.collect()
                if sim is not None:
                    import omni.replicator.core as rep

                    mark_cleanup("destroy_camera_render_products")
                    rep.vp_manager.destroy_hydra_textures("Replicator")
                    mark_cleanup("stop_timeline")
                    sim.stop()
            except Exception as exc:
                cleanup_failed = True
                cleanup["error"] = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
                sys.stderr.flush()
            finally:
                mark_cleanup("app_close_entered")
                app.close()
                cleanup["app_close_returned"] = True
                mark_cleanup("closed")
    return 0 if result["passed"] and not cleanup_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
