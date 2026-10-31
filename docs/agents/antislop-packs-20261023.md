# Anti-slop packs in STAR's own answers (2026-10-23, Claude)

Source: github.com/miqdadbadjuber/anti-slop v3.2.21 (MIT), six skills now in `star/skill_packs/antislop*/`.
- Layout per pack: `SKILL.md` (upstream text verbatim, frontmatter reduced to name + a shortened one-line description (the agent skill catalog has a tight size budget: with the full descriptions test_intelligence ran out of context)), `digest.md` (short extract STAR injects), `references/SOURCE.md` (provenance). Licence in `star/skill_packs/THIRD_PARTY_NOTICES.md`.
- Not shipped: `contrast-check.py` and `contrast-mcp.py` of antislop-human. Packs are text only and nothing in STAR runs bundled scripts.
- Routing: `star/antislop.py`, called from `desktop_core.reference_sections` after the Roblox packs. UI, web, copy and code-generation prompts get the core digest plus the best-matching specialised digest (ui, layoutmobile, human, copywriting, code), at most 5.2 KB. Roblox, Godot and named-engine prompts and quick chat get nothing. Off switch: `STAR_ANTISLOP=off`.
- Why digests: the verbatim texts are 9 to 58 KB; the pack loader's per-turn bodies are capped at 6.4 KB. Full text stays as reference.
- Not measured by the evaluation gate (docs/evals.md) yet; default ON by owner request.
- Tests: `tests/test_antislop_packs.py`.
