# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Public CLI executes a bounded real-weight policy chunk and finish."""

from tests.e2e_tests.common import publish_check


def test_policy_chain(robodojo_scenario):
    publish_check("robodojo_policy_chain", robodojo_scenario.policy_chain)
