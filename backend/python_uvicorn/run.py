"""Start the NavIC backend (FastAPI + embedded TCP receiver).

Run from the repository root:

    .venv-local/bin/python backend/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn

from backend.python_fastapi.application.core.config import (
    get_settings,
    load_environment,
)


def main() -> None:
    load_environment()
    settings = get_settings()
    settings.apply_defaults()
    # Uvicorn owns the main thread; the FastAPI lifespan starts and closes the
    # embedded TCP receiver in the same event loop.
    uvicorn.run(
        "backend.python_fastapi.application.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level,
        # OAuth callbacks and one-time links contain sensitive query strings;
        # Uvicorn's default access log writes those URLs verbatim.
        access_log=False,
    )


if __name__ == "__main__":
    main()
