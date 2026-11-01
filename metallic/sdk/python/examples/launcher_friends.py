"""Launcher-style use: the signed-in player's friends and what they are playing (first-party sign-in token)."""
import os

from metallic_api import MetallicAPI

api = MetallicAPI(os.environ["METALLIC_API_URL"], token=os.environ["METALLIC_TOKEN"],
                  fingerprint=os.environ.get("METALLIC_API_FINGERPRINT"))
for f in api.list_friends()["friends"]:
    p = f["presence"]
    print(f"{f['display_name'] or f['username']}: {p['status']}{' ' + p['game'] if p.get('game') else ''}")
api.set_presence({"status": "playing", "game": "RC"})
