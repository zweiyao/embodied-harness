import numpy as np


def run(frames, params):
    """Summarize calibrated patches; never infer object identity or success."""
    step = params.get("step", -1)
    frame = frames[-1] if step == -1 else next((f for f in frames if f["step"] == step), None)
    if frame is None:
        return {"error": "step unavailable", "available_steps": [f["step"] for f in frames]}
    camera = params.get("camera", "agentview")
    data = frame["cameras"][camera]
    world, depth, rgb = data["world"], data["depth"], data["rgb"]
    h, w = world.shape[:2]
    if depth.shape[:2] != (h, w) or rgb.shape[:2] != (h, w):
        return {"error": "RGB/depth/world resolution mismatch"}
    eef = np.asarray(frame["proprio"]["robot0_eef_pos"], dtype=float)
    radius = params.get("radius", 2)
    out = []
    for point in params["points"]:
        row, col = int(round(point[0]*(h-1))), int(round(point[1]*(w-1)))
        r0, r1 = max(0, row-radius), min(h, row+radius+1)
        c0, c1 = max(0, col-radius), min(w, col+radius+1)
        xyz = world[r0:r1,c0:c1,:3].reshape(-1,3)
        z = depth[r0:r1,c0:c1].reshape(-1)
        good = np.isfinite(xyz).all(axis=1) & np.isfinite(z) & (z > 0) & (np.abs(xyz).sum(axis=1)>1e-6)
        item = {"point_rc_normalized":point,"pixel_rc":[row,col],"valid_count":int(good.sum()),"patch_count":int(good.size)}
        if good.sum() < 3:
            item["error"] = "insufficient valid depth"
        else:
            q = np.quantile(xyz[good], [.1,.5,.9], axis=0)
            item.update(world_p10_xyz=q[0].tolist(),world_median_xyz=q[1].tolist(),world_p90_xyz=q[2].tolist(),eef_to_patch_xyz=(q[1]-eef).tolist(),depth_p10_p90=np.quantile(z[good],[.1,.9]).tolist(),rgb_median=np.median(rgb[r0:r1,c0:c1].reshape(-1,3)[good],axis=0).tolist())
        out.append(item)
    return {"step":frame["step"],"camera":camera,"image_size":[h,w],"coordinates":"world XYZ in metres; normalized row/column of calibrated image, not policy image", "patches":out,"limitations":"Visible surface samples only. Depth spread may indicate edges or mixed surfaces. No semantic identity, object extent, grasp or placement success inferred."}
