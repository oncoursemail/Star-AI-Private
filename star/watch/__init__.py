"""STAR watches videos on her PC like a person: browses YouTube in her own browser, picks what she likes, listens and
looks, reacts out loud like a reaction streamer, and learns from it.

choose.py      interest weights + curiosity queue + novelty + recommendations -> which video; watch history
browser.py     HostBrowser: her normal browser by keyboard shortcuts and clicks (star-home Executor); VisionScreenReader
captions.py    yt-dlp text only: captions, metadata, search; CaptionHearing (captions as a hearing source)
hearing.py     HubHearing: star.senses SensesHub (all PC audio, streaming speech-to-text) as a hearing source
frames.py      LiveFrameSampler: keeps only novel screenshots (same signature as star/video_sampling.py)
understand.py  rolling understanding: what is happening, who talks, key moments, interest
react.py       moment detector, reaction policy (reaction_density), reactor (one short line + prosody)
session.py     WatchSession: the per-second loop for one video
learn.py       summary + facts into knowledge (source URL), practice goals from tutorials, history
activity.py    the "watch_videos" activity (register_home_activities), configure() for the voice/senses parts
Settings: <home>/watch/settings.json (settings.py). Notes and research: docs/agents/watch-videos-20261026.md.
"""
from .activity import ensure_interest, configure, register_home_activities, run  # noqa: F401
from .settings import WatchSettings  # noqa: F401
