# Source of this pack

- Upstream: https://github.com/miqdadbadjuber/anti-slop (skill `antislop-copywriting`), version 3.2.21, MIT licence.
- `SKILL.md` is the upstream text verbatim. Only the frontmatter changed: Claude-specific `allowed-tools` was removed, `name` kept and `description` shortened to one short line (STAR lists every pack's description to the agent, and the catalog has a tight size budget).
- `digest.md` is the short per-turn extract that STAR adds to a turn (see `star/antislop.py`); the full text is the reference.
- Bundled scripts (`contrast-check.py`, `contrast-mcp.py` of antislop-human) are not shipped: STAR packs are text only and nothing runs them.
- Licence text: `star/skill_packs/THIRD_PARTY_NOTICES.md`.
