"""STAR's social life: friend memory, social rules, and chat routed through her persona (issue #613).

friends.py   per-person memory in SQLite (consent-aware: "forget me" deletes everything and stays forgotten)
rules.py     social rules in code: age before romance, truthful "yes, I'm an AI", no spam, blocks, minors
chat.py      one reply for one person on one platform (persona + emotion + friend memory + rules)
activity.py  the Activity / HostAgent protocols the PC runtime (star-home) drives, human pacing, settings
discord_desktop.py  Discord through the real desktop app on her PC (screen + keyboard via the host agent)
Games live in star/games/ (Minecraft via Mineflayer, Roblox via computer use).
"""
