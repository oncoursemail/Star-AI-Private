#!/usr/bin/env python3
"""Inspect same-UID Desktop Commander remote hosts. Exit 0=present, 1=absent, 2=unknown."""
import argparse
import errno
import json
import os
from pathlib import Path
import sys
ENTRIES = ("/node_modules/@wonderwhy-er/desktop-commander/dist/index.js", "/.bin/desktop-commander")

def matches_remote(argv):
    return any(arg.startswith("/") and arg.endswith(ENTRIES) and argv[i + 1] == "remote"
               for i, arg in enumerate(argv[:-1]))

def inspect(proc_root=Path("/proc"), uid=None):
    uid, found, uncertain = os.getuid() if uid is None else uid, [], False
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return [], True
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        fd = None
        try:
            fd = os.open(entry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            if os.fstat(fd).st_uid != uid:
                continue
            with os.fdopen(os.open("cmdline", os.O_RDONLY | os.O_CLOEXEC, dir_fd=fd), "rb") as stream:
                data = stream.read(65537)
            if len(data) > 65536:
                uncertain = True
            elif matches_remote([os.fsdecode(a) for a in data.rstrip(b"\0").split(b"\0")]):
                executable = os.readlink("exe", dir_fd=fd).removesuffix(" (deleted)")
                if Path(executable).name in ("node", "nodejs") and os.fstat(fd).st_uid == uid:
                    found.append(int(entry.name))
        except OSError as error:
            uncertain |= error.errno not in (errno.ENOENT, errno.ESRCH, errno.ENOTDIR)
        finally:
            if fd is not None:
                os.close(fd)
    return sorted(found), uncertain

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    for flag in ("--check", "--json", "--self-test"):
        options.add_argument(flag, action="store_true")
    args = parser.parse_args()
    if args.self_test:
        import unittest
        return 0 if unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromName("test_remote_agent_present")).wasSuccessful() else 2
    pids, uncertain = inspect()
    if args.json:
        print(json.dumps({"pids": pids}))
    return 0 if pids else 2 if uncertain else 1

if __name__ == "__main__":
    sys.exit(main())
