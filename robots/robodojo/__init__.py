# Copyright 2026 The RPent Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""RoboDojo (Isaac Sim) robot extension for RPent."""

from robots.robodojo.robot_spec import get_robot_spec, get_toolkit


def native_catalog() -> list[dict]:
    from robots.robodojo.catalog import native_catalog as build_catalog

    return build_catalog()


def validate_selection(selected: list[dict]) -> None:
    from robots.robodojo.catalog import validate_selection as validate

    validate(selected)


__all__ = ["get_robot_spec", "get_toolkit", "native_catalog", "validate_selection"]
