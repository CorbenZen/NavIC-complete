"""Controller base class.

A controller owns the HTTP-facing decisions for one route family.  Most
operations delegate to the shared domain handler so the website keeps the
existing response contract; operations that can be expressed through the
backend service layer override ``Controller.resolve`` with a real function.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Operation = Callable[..., Any] | dict[str, Callable[..., Any]]


class Controller:
    """Route-family controller with optional per-path overrides."""

    operations: dict[str, Operation] = {}

    def resolve(self, path: str, method: str | None = None) -> Callable[..., Any] | None:
        """Return an override for *path* and *method*, or ``None`` to delegate."""
        operation = self.operations.get(path)
        if operation is None:
            return None
        if isinstance(operation, dict):
            if method is None:
                return None
            return operation.get(method.upper())
        return operation

    def handles(self, path: str) -> bool:
        return path in self.operations


__all__ = ["Controller", "Operation"]
