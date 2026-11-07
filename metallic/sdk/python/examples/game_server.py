"""Game server or backend: heartbeat every 30 s with a server key read from a file (never from source code)."""
import os
from pathlib import Path
import time

from metallic_api import MetallicAPI, MetallicAPIError

key = Path(os.environ["METALLIC_SERVER_KEY_FILE"]).read_text(encoding="utf-8").strip()
api = MetallicAPI(os.environ["METALLIC_API_URL"], token=key, fingerprint=os.environ.get("METALLIC_API_FINGERPRINT"))
while True:
    try:
        api.server_heartbeat({"game": "RC", "server_id": "rc-eu-1", "players": 12, "max_players": 40})
    except MetallicAPIError as exc:
        time.sleep(exc.retry_after or 30)
        continue
    time.sleep(30)
