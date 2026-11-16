"""Lazy package exports.

Importing a package executes its ``__init__`` before the requested submodule.
Several backend packages re-export objects that live in ``navic_tcp``, which
reads environment variables at import time.  Building the environment first is
therefore mandatory.  These lazy exports defer the heavy imports until an
attribute is actually accessed.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any

ExportMap = dict[str, tuple[str, str]]


def make_getattr(package: str, exports: ExportMap) -> Callable[[str], Any]:
    """Build a module-level ``__getattr__`` for *exports*."""

    def __getattr__(name: str) -> Any:
        try:
            module_name, attribute = exports[name]
        except KeyError:
            raise AttributeError(
                f"module {package!r} has no attribute {name!r}"
            ) from None
        return getattr(import_module(module_name), attribute)

    return __getattr__


__all__ = ["ExportMap", "make_getattr"]
