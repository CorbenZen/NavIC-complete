"""Compatibility launcher for the NavIC FastAPI/Uvicorn service."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.python_uvicorn.run import main

if __name__ == "__main__":
    main()
