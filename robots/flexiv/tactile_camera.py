# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Independent UVC left-fingertip capture; no robot or gripper commands."""

import argparse
import base64
import json
import os
import time
import uuid
from pathlib import Path

import numpy as np


def read_snapshot(directory, *, now=None):
    """Return a fresh atomic image/metadata pair, or an explicit missing reading."""
    try:
        with np.load(Path(directory) / "left.npz", allow_pickle=False) as bundle:
            metadata = json.loads(str(bundle["metadata"]))
            image = bundle["jpeg"].tobytes()
        age = (time.time() if now is None else now) - metadata["received_at_s"]
        if not 0 <= age <= 2:
            return {**metadata, "status": "stale", "age_s": age}, None
        return {**metadata, "status": "available", "age_s": age}, image
    except (OSError, ValueError, KeyError) as exc:
        return {"status": "unavailable", "side": "left", "reason": str(exc)}, None


def attach_snapshot(observation, directory):
    metadata, image = read_snapshot(directory)
    observation["tactile"] = {"left": metadata}
    if image is not None:
        # The generic observation loader accepts PNG or JPEG encoded images.
        observation["images_png"]["tactile_left"] = base64.b64encode(image).decode()


def main():
    import cv2

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True, help="Stable /dev/v4l/by-id path")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    directory = Path(args.output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    try:
        if not capture.isOpened():
            raise RuntimeError(f"Cannot open tactile sensor {args.device}")
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        session = uuid.uuid4().hex
        sequence, last_publish = 0, 0.0
        while True:
            ok, frame = capture.read()
            received = time.time()
            if not ok:
                raise RuntimeError("Tactile camera read failed")
            sequence += 1
            if time.monotonic() - last_publish < 0.1:
                continue
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                raise RuntimeError("Tactile image encoding failed")
            metadata = {
                "side": "left",
                "serial": args.serial,
                "capture_session": session,
                "sequence": sequence,
                "received_at_s": received,
                "timestamp_kind": "host_receipt_not_hardware_synchronized",
                "image": "tactile_left.png",
                "resolution_wh": [frame.shape[1], frame.shape[0]],
                "image_kind": "raw_uvc_unrectified",
                "pixel_axes": "x right, y down; not robot base axes",
                "reference_load": "unknown",
                "force_calibrated": False,
            }
            temporary = directory / "left.tmp"
            with temporary.open("wb") as stream:
                np.savez(stream, jpeg=encoded, metadata=json.dumps(metadata))
            os.replace(temporary, directory / "left.npz")
            last_publish = time.monotonic()
    finally:
        capture.release()


if __name__ == "__main__":
    main()
