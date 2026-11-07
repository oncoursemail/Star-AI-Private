# STAR Creator Intelligence: VFX, procedural geometry, reference research and companions
**Research intake:** October 24, 2026. **Status:** reviewed source notes and one **offline** EditableMesh preview generator in a draft PR. No Roblox Studio acceptance or claimed model-weight improvement.

## Input evidence (four user-provided videos, six screenshots)
Evidence summaries only; do not commit third-party video frames or republish other people's assets.

| Reference | Direct visual evidence | Grounded takeaway | Not proven |
| --- | --- | --- | --- |
| Clip: blue ice/energy destruction (TikTok Mapify/Codex) | Pieces and bright blue trails circulate after a ground burst in Roblox. | Layer moving mesh fragments, rim flashes, trailing ribbons, easing and staged decay. | An entire production-ready effect was built in five minutes or by one prompt. |
| Clip: anime combat VFX | Bright orange weapon sweep, arcs and impact feedback around two Roblox avatars. | Coordinate authored animation markers, anticipation, 0.1–0.25s impact, sparks, slash silhouette, and dissipating trail with camera/SFX. | Quality across camera angles, mobile performance, network replication, or combat authority. |
| Clip: animated water and EditableMesh announcement | Deformable coastal-looking waves and an official Roblox devforum API post. | Profile one bounded wave mesh and serial batched updates at controlled visual FPS. | Realistic fluid physics, collision, unlimited scalability or guaranteed FPS gains. |
| Clip: ThatPet desktop companion | Character reacts to coding-agent activity on desktop. | Use structured `thinking/working/needs-approval/failed/completed` events to drive STAR's own chibi companions. | We need or can copy ThatPet assets, sound, proprietary scripts, or branding. |
| Screenshot: Obsidian + Claude + Graphify | People propose local notes and knowledge graphs. | Maintain per-project durable Markdown evidence with linked sources; retrieve sparingly. | That an Obsidian vault or graph automatically makes model weights more intelligent. |
| Screenshot: VFX Forge and 'Quinkles' particles | A comment suggests VFX helpers/plugins. | Evaluate tools by editable output, license, update activity, perf and maintainability; preserve native Luau sources. | Identity and capabilities of 'Quinkles' plugin from a comment alone. |
| Screenshot: Blender MCP | A Blender rigging/tool connection is suggested. | Extend STAR's existing Blender bridge via guarded scene-schema tools, mesh/rig validation, export previews and signed provenance. | That unguarded generated Blender Python is safe to execute. |

## Existing STAR components (avoid duplicate infrastructure)
- `star/roblox_vfx_studio.py`: ability timeline and style profiles, Lua modules, guarded Studio test path, frame evidence and advisory critique; OFF until opted in. Extend its visual benchmarks rather than create a second VFX engine.
- `star/roblox_vfx_compiler.py`: bounded offline JSON-to-Luau VFX compiler.
- `star/blender_mcp.py` and `star/blender_bridge.py`: existing scoped first-party Blender tools; do not replace with unrestricted arbitrary Python execution.
- `star/obsidian_bridge.py`: read-only local Markdown vault search and wikilink paths. `star/graphify_bridge.py`: read-only adapter for Graphify exports.
- `star/media_features.py`: optional ffmpeg bounded video frames and optional audio transcription. Needs temporal event indexing for large videos, not just sampling four frames.
- Active companion work is already in PR #549; coordinate without replacing creator-approved mascot identity.

## Verified 2026 geometry research
Roblox's Aug 6 beta announcement and Sept 15 full-release update explicitly state batched mesh methods are available in published experiences. Official signatures: `BatchAdd(Enum.MeshAttribute.Vertex, positions)`, `BatchAdd(Enum.MeshAttribute.Face, listOfVertexIdArrays)`, `BatchSetValues(ids, values)`, `BatchGetValues(ids)`. All mutating methods run **serially**; parallel Actors may execute read-only spatial mesh queries. Reported speedups of ~8x (batch) and ~2x (parallel read workload) do not translate to an automatic game FPS guarantee. Roblox memory/eligibility restrictions, mesh-size limits, asset rendering overhead and mobile fill-rate remain bottlenecks.

The new `star/roblox_editablemesh_batch.py` is **not connected to Star's automatic Studio tool list**. It returns a source string for an opt-in **client-local, non-colliding, no-replication** preview with mobile/balanced/desktop tiers, cached vertex IDs, 12–24 visual Hz updates, 288–3200 triangles and static fallback. For real water, separately design material/UV normals, depth, buoyancy, physics, LOD distance and server-client replication policy. Don't create one mesh per player or rebuild MeshParts per frame.

## Measurable VFX improvement loop (candidate next slice)
1. **Reference intake:** owner-supplied still/video; checksum, timestamp, limited keyframes, speech/transcript (if available), camera/shot boundaries, rights note and uncertainty fields. No network-based face identity recognition or copied proprietary assets.
2. **Art brief:** preserve approved style and palette; identify focal impact at 1–3 fixed camera distances, silhouette, shape language, exact timing beats and world-scale reference.
3. **Timeline build:** bind animation markers to VFX cues, generate editable mesh/particle/beam/trail assets and typed Luau; server authoritative hit detection and cooldowns, client renders.
4. **Studio capture:** in isolated owner-approved test place, 4+ phases (anticipation, hit, sustain, dissolve), high and low graphics, visible occlusion, cleanup and 2-client replication tests.
5. **Quality gate:** measured frame-time cost (p50/p95), overdraw on mobile, allocated vertices, active emitters, cleanup leaks, color/readability assessment, impact delay in ms, and human visual acceptance. No made-up visual score. Retry only failures with specific evidence.
6. **Verified lesson:** commit useful recipe with doc URL, API-version stamp, license/provenance, fixtures and demonstrated tests; mark new lessons as proposals pending owner review.

### VFX Forge / particles comparison
VFX Forge is an external Roblox plugin, not a verified STAR-native module. Look for opt-in editable exports, licensed assets, source inspection, price, creator support, update recency and mobile benchmarks. The name 'Quinkles Particles' in the screenshot remains **unverified**; do not install a similarly named plugin on a trusted Studio workstation without checking the actual creator and license.

### Blender MCP / 3D character and companion workflow
Blender's official MCP Server is interesting for explanations and scene diagnostics; Blender itself warns it executes LLM-generated Python **without safety guards**. Use STAR's constrained scene APIs on sandboxed assets, and keep full arbitrary Python execution disabled. Plan: mesh topology check → normals/manifold check → rig weights → animation loops → render previews → inspect silhouette and identity consistency → export GLB/FBX → import in owner-approved Studio test place.

For desktop companions, borrow **the state-event pattern** from ThatPet, not its code or designs. Drive STAR/Astro/Ember/Claude visuals using privacy-minimized event types, explicit local controls, low idle CPU and accessibility options; let companions play and emote without reading the user's chats by default.

### Durable knowledge: Obsidian vs Graphify vs lightweight files
- Obsidian is an optional **viewer/editor of plain Markdown**; a vault is not a smarter foundation model. STAR already has a read-only vault reader; avoid duplicate app-specific storage.
- A graph of `asset -> uses technique -> Roblox API -> tested in commit -> source` is valuable **when it can show evidence of every edge**. Prefer existing Graphify export reader; benchmark whether adding graph expansion beats keyword + embedding retrieval on held-out project questions. Some graph paths merely add distracting tokens.
- Per project keep `brief.md`, `style.md`, `shots.md`, `tests.md`, `source-manifest.json`, `verified-lessons.md` with explicit source, date, revision, reliability and permission scope. Never auto-promote user-private notes or model speculation into validated facts.
- Obsidian Local REST API can expose read/write operations over authenticated loopback; require independent opt-in and avoid unrestricted write or shell command access. Keep default reader read-only.

## Evaluation and release gates
**Delivered in this PR:** the original `frost_cyclone` and `cinematic_sword_arc` cue presets on the existing guarded VFX Studio pathway; offline EditableMesh preview source generator; unit tests; opt-in mesh skill routing; VFX composer guidance; and evidence-backed research notes. **Not delivered:** a new frontier model, automatic model training, production-ready water, installed plugins, video ingestion UI, real Roblox playtests, Blender code execution, any public release or auto-merge.

Acceptance before enabling defaults: Python `compileall` / pytest / Luau analyzer; review generated syntax; Studio playtest and 2-client visuals on authorized test place; profile low-end phone vs baseline; measure visual review; compare held-out coding/VFX eval outcomes with unchanged baseline; independent reviewer and green CI. Keep `STAR_SKILL_PACKS` opt-in for `roblox-editablemesh-batching` until tests show benefit.

## Source links (primary when available)
- Official Roblox batch release and parallel query notes: https://devforum.roblox.com/t/full-release-editablemesh-batching-apis-parallel-queries/4779401
- Roblox EditableMesh API: https://create.roblox.com/docs/reference/engine/classes/EditableMesh
- Roblox AssetService: https://create.roblox.com/docs/reference/engine/classes/AssetService
- Roblox particle emitters: https://create.roblox.com/docs/effects/particle-emitters
- Roblox community plugin VFX Forge: https://devforum.roblox.com/t/plugin-vfx-forge-an-advanced-custom-vfx-system/3867553
- Blender official MCP / security warning: https://www.blender.org/lab/mcp-server/
- Obsidian Local REST API + MCP plugin: https://community.obsidian.md/plugins/obsidian-local-rest-api
- Obsidian Vault Retrieval: https://community.obsidian.md/plugins/vault-retrieval
- ThatPet agent event model: https://thatpet.app/
- GraphRAG background: https://microsoft.github.io/graphrag/
