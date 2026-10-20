#!/usr/bin/env python3
import os, sys
from pathlib import Path
command = os.environ.get("SSH_ORIGINAL_COMMAND", "")
if command == "health":
    print("star-recovery-export-v1")
    sys.exit(0)
if command != "export":
    print("Only the configured recovery export is permitted", file=sys.stderr)
    sys.exit(126)
# The exporter sits next to this gate; its owner-only config is in this account's ~/.config (outside git).
exporter = Path(__file__).resolve().parent / "recovery_export.py"
config = Path.home() / ".config/star-recovery/export.json"
os.execv("/usr/bin/python3", ["/usr/bin/python3", str(exporter), "--config", str(config)])
