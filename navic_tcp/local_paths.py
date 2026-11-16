"""Local application data paths shared by NavIC's database configuration."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import suppress
from pathlib import Path

from sqlalchemy.engine import URL


def local_data_dir() -> Path:
    """Return NavIC's persistent per-user data directory (XDG compliant)."""
    override = os.getenv("NAVIC_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")).expanduser()
    return base / "navic"


def default_database_path() -> Path:
    return local_data_dir() / "navic.sqlite3"


def default_database_url() -> str:
    """Build an absolute SQLite URL, avoiding dependence on the launch cwd."""
    return URL.create("sqlite", database=str(default_database_path())).render_as_string(
        hide_password=False
    )


def prepare_local_database(database_url: str, legacy_path: Path) -> Path | None:
    """Safely import the old repository-local DB once, without changing it.

    SQLite's backup API gives a consistent snapshot even if the source is in
    use. A temporary file and atomic replace prevent a partial destination if
    the process is interrupted. Existing destination data always wins.
    """
    target = default_database_path()
    expected_url = default_database_url()
    if database_url != expected_url or target.exists() or not legacy_path.is_file():
        return None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Parent directory is not writable (CI, sandbox, read-only FS).
        return None
    fd, temporary_name = tempfile.mkstemp(prefix="navic-import-", suffix=".sqlite3", dir=target.parent)
    os.close(fd)
    try:
        with sqlite3.connect(f"file:{legacy_path.resolve()}?mode=ro", uri=True) as source:
            with sqlite3.connect(temporary_name) as destination:
                source.backup(destination)
                result = destination.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise RuntimeError("Legacy NavIC database failed SQLite integrity check")
        os.replace(temporary_name, target)
        return target
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def ensure_sqlite_parent(database_url: str) -> None:
    """Create the parent directory for an absolute SQLite database URL."""
    if not database_url.startswith("sqlite:///"):
        return
    value = database_url[len("sqlite:///"):]
    if value == ":memory:":
        return
    path = Path("/" + value.lstrip("/")) if database_url.startswith("sqlite:////") else Path(value)
    with suppress(OSError):
        path.parent.expanduser().mkdir(parents=True, exist_ok=True)
