# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Compact repeated camera bookkeeping without reducing live motion feedback."""


def compact_camera_metadata(metadata):
    """Keep geometry/quality and frame identity; full timestamps remain in artifacts."""
    return {
        **metadata,
        "cameras": {
            name: {
                key: value
                for key, value in camera.items()
                if key
                not in {
                    "frame_monotonic",
                    "host_received_monotonic",
                    "host_received_s",
                    "color_timestamp_ms",
                    "depth_timestamp_ms",
                    "timestamp_domain",
                    "depth_timestamp_domain",
                    "producer_pid",
                    "serial",
                    "frame_age_reference",
                }
            }
            for name, camera in metadata.get("cameras", {}).items()
        },
    }
