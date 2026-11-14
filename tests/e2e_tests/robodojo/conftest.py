# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Opt-in prepared RoboDojo GPU runtime."""

import os
from pathlib import Path

import pytest

from tests.e2e_tests.robodojo.scenario import RoboDojoScenario


@pytest.fixture(scope="session")
def robodojo_scenario():
    return RoboDojoScenario(Path(os.environ["RPENT_E2E_OUTPUT_DIR"]))
