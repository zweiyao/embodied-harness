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

"""Prompt bundle dataclass for robot-contributed LLM prompts.

Lives in :mod:`rpent.robots` so each robot's
``prompt_bundle.py`` (e.g. :mod:`robots.libero.prompt_bundle`)
can import it without depending on the RPC transport layer.
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from rpent.prompt.composition import ComposedPrompt
from rpent.prompt.utils import PromptNode, format_prompt

PromptFactory = Callable[..., PromptNode]


@dataclass(frozen=True)
class PromptBundle:
    """Python-defined prompt factories for one robot."""

    system: PromptFactory
    user: PromptFactory

    def render(
        self,
        variant: str,
        *,
        variables: Mapping[str, object] | None = None,
    ) -> str:
        """Render one prompt variant (``"system"`` or ``"user"``)."""
        return self.render_with_sources(variant, variables=variables)[0]

    def render_with_sources(self, variant: str, *, variables=None) -> tuple[str, dict]:
        """Render once and return the source files and exact rendered-text hash."""
        factory = getattr(self, variant)
        prompt = factory(variables)
        values = dict(variables or {})
        layered = isinstance(prompt, ComposedPrompt)
        files = list(prompt.sources) if layered else []
        if layered:
            values.update(prompt.variables)
        text = format_prompt(prompt, variables=values)
        source = (
            inspect.getsourcefile(factory)
            if inspect.isfunction(factory) or inspect.ismethod(factory)
            else None
        )
        if source and Path(source).is_file():
            files.insert(
                0,
                {
                    "section": "factory",
                    "path": str(Path(source).resolve()),
                    "sha256": hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                },
            )
        return text, {
            "factory": f"{getattr(factory, '__module__', type(factory).__module__)}.{getattr(factory, '__qualname__', type(factory).__qualname__)}",
            "layered": layered,
            "files": files,
            "rendered_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
