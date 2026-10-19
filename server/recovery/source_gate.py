#!/usr/bin/env python3
import os, sys
command = os.environ.get("SSH_ORIGINAL_COMMAND", "")
if command == "health":
    print("star-recovery-export-v1")
    sys.exit(0)
if command != "export":
    print("Only the configured recovery export is permitted", file=sys.stderr)
    sys.exit(126)
os.execv("/usr/bin/python3", ["/usr/bin/python3", "/home/star/.local/share/star-recovery/recovery_export.py", "--config", "/home/star/.config/star-recovery/export.json"])
