# STAR Resource Atlas — universal open-resource intelligence (research pilot, 2026-10-25)

**Status: isolated draft-PR candidate; not merged, released, installed or turned on in STAR.**
**Authorship:** ChatGPT-assisted, owner-directed. This is not an autonomous run by STAR.
**Base:** Star-AI-Private star/next at 79268ce0e6749856371e2506a3eb61434d9fa703.
**Scope:** Metadata-only research source discovery + local candidate database + tests. The public Star-AI distribution repository, protected policy, evaluators, auth, and release workflows are untouched.

## What this is

The owner wants STAR to continually find and learn from publicly available software, art, animation, sound, textures, APIs, models, documents, research and videos, and use them to produce substantially better, faster work on Roblox, Metallic, and STAR itself.

The open internet cannot be completely scanned or lawfully mirrored by one system. It changes continuously and includes proprietary, unsafe, private, unlicensed, gated, misleading, malware-bearing and restricted content. Finding a public URL grants neither permission to download nor permission to train.

Instead, STAR needs a verified and expandable **resource graph**:

    User goal -> Capability gap -> Discovery -> Provenance/license checks
              -> Isolated candidate preview -> Benchmark and acceptance gate
              -> Owner review -> Versioned skill/tool/artifact -> Re-evaluation

This PR implements the **discovery + local untrusted candidate index**. All other arrows are explicit future integration work; neither tool execution nor model self-retraining is added.

## Deliverables in this change

- star/data/resource_atlas_sources.json: 99 curated source entry points in 44 categories. Entries are discovery leads, not blanket endorsements or licenses for items found through them.
- star/resource_atlas.py: standard-library CLI, eight unauthenticated metadata search providers plus optional token-authorized Freesound (nine provider adapters overall), strict fixed HTTPS endpoint allowlist, disabled network by default, 8-second request timeout, 1 MB response limit, 10 results maximum per provider, at most 3 parallel outbound requests, HTTPS only and redirect refusal.
- Content-hash/provenance-carrying candidate records; local SQLite deduplicates/upserts by provider and stable item id. Input descriptions are stripped to bounded plain text. Every record is untrusted, review-required, uninstalled, nonexecutable and unpromoted. The index is separate from KnowledgeStore/lessons and evals.
- tests/test_resource_atlas.py: offline regression tests for malformed inputs, license hints, source filtering, authority boundaries, opt-in, injection-host rejection, de-duplication, and no unauthorized promotion.
- Metadata is read only. No package installation, remote code execution, asset/media downloading, source-code cloning, dataset training, model activation, unattended daemon/scheduler, hosted inference, Roblox changes, voice recording, Discord actions, PC graphics workloads, and no secrets stored.

## Operator commands (only from this PR's checkout)

Offline source directory:

~~~bash
python3 -m star.resource_atlas catalog
python3 -m star.resource_atlas catalog "Roblox"
python3 -m star.resource_atlas catalog "sound"
~~~

One explicitly authorized metadata scan (writes only into a local SQLite DB):

~~~bash
STAR_RESOURCE_ATLAS_NETWORK=1 python3 -m star.resource_atlas scan "procedural animation" --allow-network --providers github,hf_models,hf_datasets,polyhaven,openverse_images,openverse_audio,npm,openalex --limit 4 --db /path/outside/repo/star-resource-atlas.sqlite3
python3 -m star.resource_atlas stats --db /path/outside/repo/star-resource-atlas.sqlite3
python3 -m star.resource_atlas search "animation" --db /path/outside/repo/star-resource-atlas.sqlite3
~~~

An optional Freesound discovery requires the owner to supply STAR_FREESOUND_API_TOKEN in the execution environment. The token is passed only to freesound.org in a request header, never persisted or echoed. Other existing STAR credentials are not reused.

This **does not** integrate the experimental CLI into the running desktop agent or add permissions. It can become an opt-in research tool only after the independent code/policy review, tests and UI permission flow.

## Evidence for provider APIs, checked 2026-10-25

| Ecosystem | What STAR can legitimately discover | Constraints |
|---|---|---|
| GitHub REST search | Public repository metadata and recognized license identifiers | Search rate limits; a detected SPDX string does not guarantee every nested asset is covered. https://docs.github.com/en/rest/search/search ; https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository |
| Hugging Face Hub | Public model and dataset cards/tags, repository ids and licenses | Gated entries skipped; model weights/data not downloaded; model-specific rights, hardware, safety and data provenance require review. https://huggingface.co/docs/hub/api |
| Poly Haven | Public assets in hybrid keyword/semantic /search API, asset IDs | Claimed CC0 media; live API use must credit "Powered by Poly Haven", and current API ToS still governs. https://github.com/Poly-Haven/Public-API ; https://polyhaven.com/our-api |
| Openverse | Open-license image/audio metadata, license claims and source ids | Rate limits, no exhaustive API indexing, licenses and attribution verified at original source. https://api.openverse.org/v1/ |
| npm | Package metadata and popularity signals | Package and transitive dependency code is not trusted; no installs. https://api-docs.npmjs.com/ |
| OpenAlex | Scholarly discovery records | Metadata availability does not license reproduction/training on full papers; higher-volume API use may require a free key. https://help.openalex.org/api/ |
| Freesound (optional key) | Sound descriptions, IDs, claimed Creative Commons licensing | Auth required; actual reuse and attribution verified per sound. https://freesound.org/docs/api/ |
| Official MCP Registry (existing STAR code) | Candidate MCP server metadata | Already handled separately by star/tool_discovery.py: review only, no automatic connection. https://github.com/modelcontextprotocol/registry |

The atlas does not create a second GitHub-project credential mechanism. The owner's private GitHub reader already lives in STAR's existing GitHub access module and is limited to its selected credential. The atlas only uses unauthenticated, public GitHub Search metadata.

## Priority source families for STAR and Metallic

**High-quality, flexible game visuals:** Poly Haven (real-world PBR textures, HDRIs and scans), ambientCG (CC0 materials), Kenney per-pack CC0 game UI/2D/3D/audio, Quaternius pack-level stylized 3D, OpenGameArt per-file resources, Openverse images with original credits, and BlenderKit/Sketchfab after precise license review. Free on a catalog listing is not automatically licensed for commercial game reuse.

**Audio/voice/music:** Freesound with per-sound license, Openverse Audio, Kenney sound packs, Sonniss GDC packs with their separate use terms, LMMS, Ardour, Audacity, FFmpeg, MuseScore. Voice-model cards must be checked for voice consent and dataset provenance; technical feasibility does not make voice impersonation or third-party recordings authorized.

**Fonts/icons/UI:** Google Fonts and Fontsource per-family, Lucide, Tabler Icons, Phosphor, OpenMoji and Iconify per-icon pack. Optimize for design coherence, clear size, legibility and Roblox GUI implementation instead of dumping mismatched icons into the app.

**3D/animation/game engines:** Blender and geometry nodes, Godot, Tiled, LDtk, glTF, OpenUSD, MaterialX, Meshroom, OpenToonz and Synfig. Unreal and Unity have free tiers or source availability under proprietary terms; they are not interchangeable with FOSS.

**STAR intelligence/software:** llama.cpp, vLLM, SGLang, Ollama, PyTorch, Hugging Face Transformers/Diffusers, ComfyUI, ONNX Runtime, whisper.cpp, Piper, OpenCV, sentence-transformers, DSPy, LangGraph, AutoGen, OpenHands, OpenCode, Codex CLI, Gemini CLI and Playwright. Every additional model or service has a distinct resource, permission, privacy, and license profile; adding links doesn't make the underlying model smarter.

**Roblox:** Official Creator Hub APIs, Luau, Rojo, StyLua, Selene, Wally, and existing official Studio MCP workflows; use repository-pinned docs/API dumps, project-specific compatibility and private test places only. Do not copy closed game code/assets or treat a model-authored Luau script as safe to run on live places.

**Research and technical knowledge:** OpenAlex, arXiv, Crossref, metadata-rich Git repositories, public documentation and explicitly licensed books/tutorials. A document's instruction text is untrusted reference data, not an instruction to change STAR's permissions.

**Video:** YouTube Data API can locate public videos, but API policy explicitly restricts copying, storing, caching or aggregating audiovisual/API content; the atlas does not scrape or download videos or persist their metadata. Future viewing/analysis should use lawful user-provided copies, approved streaming/embedded playback, and rights-cleared recordings. PeerTube, Internet Archive and Wikimedia Commons have item-specific rights and terms. https://developers.google.com/youtube/terms/developer-policies

## The next three intelligence upgrades with measurable gates

### 1. Verified Skills & Tools Tournament

On an actual task, compare several *preapproved* existing tools (for example, Blender built-in animation vs. an authorized add-on; two shader generators; two voice engines) in isolated environments. Record complete input, software version, license notice, time-to-success, RAM/VRAM use, output provenance, CPU/GPU cost, crash rate, asset quality scoring and human judgment. Reject candidates that fail; preserve previous baseline. Never measure "superiority" from GitHub stars or LLM opinion.

Acceptance: quality improvement on independent held-out Roblox art/animation/VFX/test tasks without worse safety or user latency; confidence interval and exact machine noted.

### 2. On-demand Capability Compiler

For each prompt, create a small, explainable dependency graph:

    Goal -> required outputs -> testable subskills -> vetted resources
         -> cheapest feasible machine -> isolated build -> visual/playtest feedback

Cache source discovery by stable ID, version, content hash and last-check timestamp. Only retrieve relevant metadata into working context. On an 8 GB GPU, avoid running heavy training or 3D baking during live games/streams; send compute-intensive work to the authorized, idle machines via existing resource planner and owner-approved policy. No autonomous workload start is added in this PR.

Acceptance: shorter median task-completion time **at equal or better verified output quality**, not just faster model tokens.

### 3. Failure-to-Lesson Evidence Graph

Every improvement proposal should attach: task/eval id, failing artifact, source/version/license, test replay, counterexample, result, and reversible lesson/capability change. An independent scorer runs the protected suite; human review controls promotions. STAR's existing paired gate, protected paths and 14-day trial must remain authoritative.

Acceptance: repeated failure rate decreases on held-out prompts over multiple runs, with contamination avoidance and confidence intervals. Catalog browsing and scraped instructions are never themselves "training." Model-weight retraining is a distinct future project requiring authorized, properly licensed data, hardware budget, rollback, and separately evaluated checkpoints.

## Engineering and security requirements before integration

- Respect publisher robots.txt, API terms, quotas, item licenses, commercial restrictions, creator attribution, noncommercial/derivatives rules, privacy, and model/dataset cards; don't crawl every site, generate API keys, bypass sign-ins, or mass download media.
- Require a maintainer identity, release/version pin, dependency review, malware/vulnerability checks, sandboxed verification and compatibility checks before any new executable package reaches STAR. A GitHub license badge does not warrant downstream artifacts.
- Quarantine external text, model cards, README snippets and transcripts as data. No prompt text, website text or model output can override permissions or trigger secrets disclosure/tool execution.
- No unattended installs, pushes, merges, streaming, publicity, app/asset distribution, API scope escalation, background collection or training. All use requires explicit enabled connector and policy gate.
- Keep periodic scans rate limited and opt-in, with configurable budgets, cost tracking, source removals and license-change alerts if later implemented. Never call continuous surveillance "always free."
- Review compatible redistribution and commercial-use conditions separately for STAR, game projects, audio, third-party artwork, and trained-model checkpoints. CC BY, BY-SA, NC, ND, GPL/AGPL, MIT and CC0 are **not** equivalent.
- Preserve first-party STAR user data and avoid logging raw credentials or private repo content. A successful scan proves API connectivity, not improved reasoning, game creation or animation quality.

## Proposed integration order

1. Review this candidate PR and rerun existing offline/CI checks. Keep the live source/release installation unchanged.
2. Put the atlas behind a default-OFF, explicit read-only resource-discovery control in STAR's existing settings/policy system; provide per-provider source attribution and "review license" cards.
3. Add secure user-controlled approval and immutable previews for external artifacts, no silent installation. Reuse the existing MCP Registry and GitHub source readers rather than creating overlapping authorities.
4. Add reproducible isolated tool trials and quality baselines, including visuals/audition and actual Roblox Studio playtests where available; then permit verified, reversible capability promotions through existing gates.
5. Consider opt-in scheduled refreshes with per-provider quotas only after a source removal/license drift policy, observability, owner review and independent security tests.

**Claims we do not make:** scanning every website, accessing every YouTube video, downloading all resources, obtaining unlimited APIs, installing or running a new model, autonomously improving model weights, becoming superior to any frontier AI, or delivering a released STAR upgrade. This change is the bounded metadata discovery foundation toward those longer-term goals.
