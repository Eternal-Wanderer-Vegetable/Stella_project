# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Environment snapshot primitives with no imports from legacy Stella packages."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from io import StringIO

from dotenv.parser import parse_stream
from dotenv.variables import parse_variables

_RAW_ASSIGNMENT = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=(.*)$")


def capture_external_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Capture the process environment before legacy configuration imports it."""
    source = os.environ if environ is None else environ
    return {str(key): str(value) for key, value in source.items()}


def parse_dotenv(
    text: str,
    *,
    environment: Mapping[str, str] | None = None,
    override: bool = False,
) -> dict[str, str]:
    """Parse dotenv text using python-dotenv grammar and explicit interpolation state.

    ``override=False`` matches the legacy base-file load; ``override=True`` matches
    the selected profile overlay. Unlike ``load_dotenv``, this does not mutate the
    process environment.
    """
    base_environment = {} if environment is None else dict(environment)
    new_values: dict[str, str] = {}
    for binding in parse_stream(StringIO(text)):
        if binding.key is None or binding.value is None:
            continue
        interpolation_environment: dict[str, str]
        if override:
            interpolation_environment = {**base_environment, **new_values}
        else:
            interpolation_environment = {**new_values, **base_environment}
        atoms = parse_variables(binding.value)
        new_values[binding.key] = "".join(
            atom.resolve(interpolation_environment) for atom in atoms
        )
    return new_values


def parse_env(text: str) -> dict[str, str]:
    """Return uppercase ``KEY=right-hand-side`` values without dotenv decoding.

    This preserves the long-standing deploy merge contract: quotes and inline
    comments remain in the raw right-hand side so merge/write operations can carry
    user text forward unchanged.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _RAW_ASSIGNMENT.match(line)
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values
