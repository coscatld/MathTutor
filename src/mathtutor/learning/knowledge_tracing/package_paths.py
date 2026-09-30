"""Read-only locations of bundled student-model packages (no NumPy import)."""
from pathlib import Path

ASSETS = Path(__file__).with_name("assets")
BUNDLED_PACKAGE = ASSETS / "assist2009-source-v2-seed29"
