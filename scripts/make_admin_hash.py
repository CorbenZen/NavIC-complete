"""Generate an ADMIN_PASSWORD_HASH value for production (e.g. Render).

Usage:
    .venv-local/bin/python scripts/make_admin_hash.py          # hidden typing
    .venv-local/bin/python scripts/make_admin_hash.py --show   # visible typing

By default the password is read at a hidden prompt, typed twice to catch typos, and is
never printed or written to disk. Only the salted scrypt hash is printed.
"""

from __future__ import annotations

import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from navic_tcp.security import hash_password, verify_password


def main() -> int:
    # --show echoes the typed password for terminals where hidden input is
    # confusing; the screen is cleared before the hash is printed.
    show = "--show" in sys.argv[1:]
    ask = input if show else getpass
    label = "visible" if show else "hidden"
    password = ask(f"Type your new admin password ({label}), then Enter: ")
    confirm = ask("Type it again to confirm, then Enter: ")
    if show:
        print("\033[2J\033[H", end="")
    if not password:
        print("\nNo password entered. Run the script again.")
        return 1
    if password != confirm:
        print("\nThe two passwords did not match. Run the script again.")
        return 1
    value = hash_password(password)
    assert verify_password(password, value)
    print("\nCopy this whole line into Render as ADMIN_PASSWORD_HASH:\n")
    print(value)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
