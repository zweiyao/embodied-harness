# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""UniVTAC contact tasks using an independently installed simulator."""


def get_robot_spec():
    """Resolve the RPent descriptor only in the planner environment."""
    from robots.univtac.robot_spec import get_robot_spec as factory

    return factory()


def get_toolkit(**kwargs):
    """Keep planner dependencies out of the simulator's Python environment."""
    from robots.univtac.robot_spec import get_toolkit as factory

    return factory(**kwargs)


def native_catalog():
    """Load tool declarations without importing Isaac Sim."""
    from robots.univtac.toolkit import native_catalog as catalog

    return catalog()


__all__ = ["get_robot_spec", "get_toolkit", "native_catalog"]
