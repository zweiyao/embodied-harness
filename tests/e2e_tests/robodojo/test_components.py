# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Real component and cancellation checks; no task-success assertion."""

from tests.e2e_tests.common import publish_check


def test_environment(robodojo_scenario):
    _, result = robodojo_scenario.environment
    publish_check("robodojo_environment", result)


def test_pi05(robodojo_scenario):
    publish_check("robodojo_pi05", robodojo_scenario.pi05)


def test_sam3(robodojo_scenario):
    publish_check("robodojo_sam3", robodojo_scenario.sam3)


def test_cancellation(robodojo_scenario):
    publish_check("robodojo_cancellation", robodojo_scenario.cancellation)
