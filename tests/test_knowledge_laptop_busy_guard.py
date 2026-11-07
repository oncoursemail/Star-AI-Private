"""Collect the laptop busy guard tests (server/knowledge/tests/test_laptop_busy_guard.py) in the repo suite."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server" / "knowledge" / "tests"))

from test_laptop_busy_guard import *  # noqa: E402,F401,F403
