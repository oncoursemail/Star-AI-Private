"""STAR's inner life: memory that surfaces when it should, nightly reflection, opinions, dreams, a self she revises, and
proactive messages to close friends. Built so the chat path pays almost nothing: everything slow happens at night.

store.py       one SQLite file: episodes (FTS5), cards, diary, opinions, backstory, seeds, dreams, self-model history
recall.py      per-message recall: a cue, at most 2 short lines, forgetting curve x importance, honest "not stored"
context.py     turn_context(memory, person, text) -> card + note for the social chat (off by default: measurement pending)
reflect.py     nightly: diary, relationship cards, opinion updates, consolidation and forgetting, consistency audit
opinions.py    her takes and her backstory, looked up by topic, never pasted whole
reachout.py    proactive messages: night-written seeds, a no-model scorer, close friends only, caps and quiet hours
dreams.py      sleeping dreams from the day's fragments, a morning fade, a mood nudge, a dream she may tell a friend
self_model.py  her self-description that she revises nightly within bounds, with a journal; fixed boundaries it cannot change
night.py       the night job, `python -m star.inner tick`, the star-home plug-in hook

Added 10-26 (docs/agents/brain-20261026.md; settings.py: default ON on her own PC, OFF elsewhere):
stream.py        memory stream: every perception/chat/game event/thought, recency x importance x relevance, embeddings,
                 bi-temporal facts (valid_from / invalid_at), inbox write path, forget + cascade
embed.py         the brain's /v1/embeddings when reachable, else a local hash embedder
structured.py    JSON-schema constrained model calls + tolerant parsing (dreams, cards, diary, audit, self review)
insights.py      reflection on the stream: insights with evidence links
planner.py       day plan (study/practise/play/social/create/rest), energy model, activity choice
consolidate.py   night: replay, facts, lessons, emotional processing, dream fallback, prune/merge, morning note
selfview.py      self-model view (identity, interests, calibrated skills, relationships, timeline) + summary line
mind.py          the core that ties these into star-home (wrap_life), the night tick, social chat hooks
journal_view.py  the owner's journal page / JSON
memeval.py       a small LongMemEval-style memory test (recall, update, temporal, abstention)

Notes and measurements: docs/agents/inner-life-20261026.md.
"""
from .context import TurnContext, turn_context          # noqa: F401
from .night import register_home_activities, run_night, tick  # noqa: F401
