import sys
from pathlib import Path

# Make the in-repo `tests/` package importable for the fake backend, and ensure
# `src/` is on the path (pyproject also configures this for pytest).
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
