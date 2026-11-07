"""Watch settings: <home>/watch/settings.json (plain JSON, no secrets). Unknown keys are ignored."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
from pathlib import Path


@dataclass
class WatchSettings:
    enabled: bool = True
    reaction_density: float = 0.35       # 0 = silent viewer, 1 = talkative reaction streamer (react.ReactionPolicy)
    chat_reactions: bool = True          # also write each reaction as a chat line
    session_minutes: float = 25.0        # one watch_videos session (several videos)
    max_video_minutes: float = 20.0      # she leaves a longer video after this long
    min_watch_s: float = 45.0            # she never drops a video before this
    browse_scrolls: int = 6              # feed scrolls before she takes the best thing seen so far
    min_score: float = 0.18              # a video below this is scrolled past
    allow_shorts: bool = False
    allow_live: bool = True
    frame_interval_s: float = 4.0        # screenshot cadence while watching
    keep_frames: int = 6                 # novel frames kept for the model
    summary_every_s: float = 45.0        # rolling understanding refresh
    tick_s: float = 1.0
    resync_s: float = 60.0               # re-read the real player position from the screen
    speak_over_gap_s: float = 6.0        # a moment waits at most this long for the speaker to pause
    stale_moment_s: float = 10.0         # a reaction composed later than this after its moment is dropped
    only_when_owner_idle_s: float = 0.0  # >0: start a session only after this many idle seconds
    use_captions: bool = True            # fetch captions (yt-dlp) when the audio path is not available
    search_fallback: bool = True         # search by her interests when she cannot read the feed on screen
    max_videos_per_session: int = 3

    @classmethod
    def load(cls, home: Path) -> "WatchSettings":
        out = cls()
        known = {f.name for f in fields(cls)}
        try:
            raw = json.loads((Path(home) / "watch" / "settings.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return out
        if isinstance(raw, dict):
            for key, value in raw.items():
                if key in known and isinstance(value, (int, float, bool)):
                    try:
                        setattr(out, key, type(getattr(out, key))(value))
                    except (TypeError, ValueError):
                        pass
        out.reaction_density = min(1.0, max(0.0, out.reaction_density))
        return out

    def save(self, home: Path) -> Path:
        path = Path(home) / "watch" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")
        return path
