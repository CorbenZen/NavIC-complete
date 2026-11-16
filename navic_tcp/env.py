"""Minimal, dependency-free .env loading for local entry points.

Production deployments should provide real environment variables through their
process manager or container.  This helper only fills variables that are not
already set, so an explicit shell export always wins.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | Path = ".env") -> bool:
    """Load KEY=VALUE pairs from *path* without overriding the environment."""
    candidate = Path(path)
    if not candidate.is_file():
        return False
    for raw in candidate.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return True
