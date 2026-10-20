#!/usr/bin/env python3
"""Publish whether the STAR brain is serving chat, for the Windows-VM gate (runs inside the starai container).

    python3 brain_watch.py /data/star-re/winvm/shared/brain-state.json

Every 0.25 s it reads /slots of star-fast and star-voice through the local router and writes (atomically)
    {"t": epoch, "chat": bool, "busy": bool, "idle_s": seconds since anything was busy, "lock": quiet-lock owner}
chat = star-fast slot 0 (kept for the owner's chat, see star/background_cap.py) or any star-voice slot is working.
busy = any star-fast/star-voice slot is working. lock = owner of the server quiet lock (/opt/star/lock) or "".
Only these fields leave the container; the API key stays here.
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("STAR_BRAIN_URL", "http://127.0.0.1:8080")
LOCK = "/opt/star/lock/owner"


def slots(model, key):
    req = urllib.request.Request(BASE + "/slots?model=" + model, headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=2) as r:
        return json.loads(r.read())


def state(fast, voice):
    """(chat, busy) from the two /slots lists."""
    fast_busy = [s.get("id") for s in fast if s.get("is_processing")]
    voice_busy = any(s.get("is_processing") for s in voice)
    return (0 in fast_busy) or voice_busy, bool(fast_busy) or voice_busy


def lock_owner():
    try:
        with open(LOCK, encoding="utf-8") as f:
            return (f.read().split() or [""])[0][:40]
    except OSError:
        return ""


def main():
    out = sys.argv[1]
    with open("/opt/star/secrets/api_keys", encoding="utf-8") as f:
        key = f.read().split()[0]
    last_busy = time.time()
    while True:
        try:
            chat, busy = state(slots("star-fast", key), slots("star-voice", key))
        except Exception:
            chat, busy = True, True  # unknown = assume the owner is chatting
        now = time.time()
        if busy:
            last_busy = now
        tmp = out + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"t": round(now, 2), "chat": chat, "busy": busy, "idle_s": round(now - last_busy, 1),
                       "lock": lock_owner()}, f)
        os.replace(tmp, out)
        time.sleep(0.25)


if __name__ == "__main__":
    main()
