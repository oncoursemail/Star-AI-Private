#!/usr/bin/env python3
import os, sys
from pathlib import Path
# Each allowed command runs the exporter with one fixed owner-only config (~/.config, outside git).
CONFIGS = {"export": "export.json", "export-kb": "export-kb.json"}
command = os.environ.get("SSH_ORIGINAL_COMMAND", "")
if command == "health":
    print("star-recovery-export-v1")
    sys.exit(0)
if command not in CONFIGS:
    print("Only the configured recovery export is permitted", file=sys.stderr)
    sys.exit(126)
exporter = Path(__file__).resolve().parent / "recovery_export.py"
config = Path.home() / ".config/star-recovery" / CONFIGS[command]
os.execv("/usr/bin/python3", ["/usr/bin/python3", str(exporter), "--config", str(config)])
