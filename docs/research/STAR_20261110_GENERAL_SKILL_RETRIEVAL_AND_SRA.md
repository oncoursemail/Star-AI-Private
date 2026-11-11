# STAR research: general Agent Skill retrieval and controlled incorporation

**Research date:** 2026-11-10  
**Implementation branch:** `feat/general-skill-bm25-retrieval-20261110-auto11`

## Executive finding

STAR already has a portable Agent Skills library, project/personal/bundled skill roots, a read-only Tool Workshop, Roblox/Godot skill packs, and a separate embedding router. The missing piece found in this pass was not another skill corpus: the Tool Workshop's `skills` source ranked candidates by substring presence and returned them in catalog order. That made retrieval depend on wording and filesystem order, not relative relevance.

This change adds dependency-free BM25 ranking over skill **names and descriptions only**, then routes the Tool Workshop's existing `skills` source through that ranked search. It does not read skill bodies during search, call an embedding server, download external skills, execute scripts, or grant permissions.

## Primary research: Skill Retrieval Augmentation (SRA)

The April 27, 2026 paper *Skill Retrieval Augmentation for Agentic AI* formalizes a three-stage pipeline:

1. **Retrieval:** find candidate capability packages from a large corpus.
2. **Incorporation:** decide whether a candidate is actually needed and which skill(s) to load.
3. **Application:** use the loaded procedure correctly and improve the task result.

The distinction matters: retrieving a relevant skill is not proof that the agent selected it, followed it, or benefited from it.

SRA-Bench contains 5,400 capability-intensive instances, 636 manually authored gold skills and a 26,262-skill corpus containing 25,626 distractors. It spans theorem application, logical reasoning, tool workflows, medical-calculator tasks, mathematical concepts and software-library use. The paper reports that retrieval-based augmentation can help, but also identifies skill incorporation as a separate bottleneck.

Two results are especially important for STAR:

- In the paper's need-awareness analysis, overall skill-loading rate was 36.9% both when the evaluated model answered correctly without a skill and when it answered incorrectly without a skill (a +0.1 percentage-point difference). The gold-skill loading rates were 30.0% and 30.5%. In that study, the agents did not meaningfully increase skill use when they demonstrably needed external capability.
- In controlled distractor experiments, injecting every retrieved skill's full contents became more brittle as hard-negative distractors increased. Progressive disclosure—showing compact metadata first and revealing full content only after selection—was more stable under noise.

These results argue against dumping more skills into every prompt. STAR should retrieve compact metadata, select deliberately, load only the chosen body, and then measure whether using it actually improves task success.

### Research references

- Paper: https://arxiv.org/abs/2604.24594
- Official toolkit: https://github.com/oneal2000/SR-Agents
- MIT-licensed dataset card: https://huggingface.co/datasets/WeihangSu/SRA-Bench
- Dataset corpus file: https://huggingface.co/datasets/WeihangSu/SRA-Bench/blob/main/corpus/corpus.json

The SRA corpus file is about 232 MB. STAR should keep it outside the application/repository and download a pinned snapshot only for an explicit benchmark campaign. The MIT dataset license does not remove the need to preserve source attribution and dataset version/digest.

## Existing STAR architecture inspected

- `star/agent_skills.py`: discovers skills from project `.agents/skills`, project `skills`, personal `home/skills`, and bundled roots. It caps the catalog at 200 entries, validates names/frontmatter, rejects symlink escapes, and separates metadata discovery from explicit `load()` and `read_reference()`.
- `star/tool_workshop.py`: provides project-scoped, read-only custom tool recipes. Its `skills` source previously scanned `list()` and returned any item with a substring hit, in catalog order.
- `star/skill_packs/__init__.py`: uses a keyword-first, one-pack-at-a-time policy for the compact Roblox/Godot guidance path.
- `star/skill_routing.py`: provides an opt-in embedding fallback for skill packs. It is a separate router and is not replaced by this BM25 metadata search.
- `benchmarks/skill_pack_routing.py` and `docs/evals.md`: measure the existing skill-pack routing and Roblox task outcomes. They do not measure general installed-skill retrieval, need-aware loading, or end-to-end skill application across arbitrary Agent Skills.

## Implementation

### 1. Metadata-only BM25 search

Added `SkillLibrary.search(query, limit=5)`:

- Uses BM25-style inverse document frequency and term-frequency saturation.
- Scores skill names more heavily than descriptions.
- Adds a small exact-phrase bonus.
- Uses stable deterministic tie-breaking and existing source precedence.
- Supports bounded queries and limits (2–200 characters; 1–20 results).
- Returns only name, description, source, ranking score and matched terms.
- Does not open `SKILL.md` bodies, references or assets during search.
- Does not call a model, embedding endpoint, network service or external index.

The score is a ranking value, **not** a calibrated probability, confidence score, quality rating or authorization signal.

### 2. Tool Workshop integration

The Tool Workshop's existing `skills` source now calls `SkillLibrary.search` when the built-in library is present. A compatibility fallback remains for older adapters that only implement `list()`.

This improves the actual reusable research-tool workflow without adding a new always-on tool schema or changing the default model prompt. The custom recipe remains project-scoped, read-only, previewable and subject to its existing human-approval workflow.

### 3. Tests added

`tests/test_agent_skill_search.py` covers:

- Title and description relevance.
- Stable ranking and result limits.
- Metadata-only output (no body, file path or reference leakage).
- Project-skill precedence over a personal duplicate.
- Empty results for unrelated queries.
- Invalid queries and limits, including booleans masquerading as integers.
- Tool Workshop use of ranked results.

## How this should evolve into full SRA

The current change deliberately implements the inexpensive first stage. The next architecture should keep these stages separate:

| Stage | Proposed STAR behavior | Required evidence |
|---|---|---|
| Candidate retrieval | BM25 metadata search; optional dense/hybrid reranking for larger corpora | Recall@K, MRR, nDCG@K |
| Need assessment | Compare a skill-free attempt or calibrated capability estimate against the task requirement | Skill-free correctness, calibration and false-load rate |
| Incorporation | Show compact previews; load only explicitly selected, allowlisted skills | Gold-skill load precision/recall; distractor resistance |
| Application | Trace actual tool/workflow use rather than accepting model self-report | Host-observed load/use events and objective task grader |
| Utility | Paired no-skill versus skill-assisted runs under identical conditions | Paired score/success gain, latency and token overhead |
| Retention | Promote reusable skills only after independent transfer checks and review | Cross-task and cross-domain holdouts |

### Recommended evaluation arms

For each frozen task and model identity, compare:

1. No skill.
2. Retrieved metadata only.
3. Selected skill body.
4. Gold skill (diagnostic upper bound; never available to the agent during ordinary runs).
5. Hard-negative distractor(s).
6. Progressive disclosure versus full-content injection.

Keep backbone, runner, tool policy, prompt template, output/context budget, grader, task order and sampling settings fixed. Interleave paired arms and preregister the task roster. Separate retrieval recall from whether a skill was loaded, whether it was actually applied, and whether the final task score improved.

Use objective task-specific graders and host-observed tool/load traces. A model saying "I used the skill" is not proof. Report failures and infrastructure errors separately; never turn missing runs into wins. Keep any SRA-Bench gold annotations out of the agent-visible prompt.

## Performance and rollout limits

- Search scans the existing bounded catalog (maximum 200 entries) and uses only short metadata. This is designed to avoid an extra embedding-server request in the Tool Workshop path.
- No latency benchmark was run; no speedup or retrieval-quality gain is claimed yet.
- The search is lexical BM25, not semantic retrieval. Paraphrase recall must be measured before changing defaults.
- The external 26,262-skill SRA corpus is not vendored and is not automatically installed.
- Search returns metadata only. It does not automatically call `load()`, read references, execute a skill script, install an MCP server, access a workspace, or authorize an external action.
- Agent Skill contents remain untrusted instructions/reference data. Existing tool permissions and owner approvals remain authoritative.
- No default skill pack, embedding setting, production model, memory database, game control, microphone, avatar, OBS or broadcast behavior is changed.

## Next recommended milestones

1. Add a two-stage host tool interface: `search skills` returns compact metadata; a separate bounded `load skill` expands one candidate by exact catalog name and content digest.
2. Record host-observed retrieval/load/application events with opaque IDs and content digests, not raw prompts or viewer data.
3. Add an offline SRA-Bench adapter that verifies a pinned dataset snapshot and maps task families to STAR's runner/grader without committing the 232 MB corpus.
4. Run paired skill-free/skill-assisted evaluations across coding, reasoning, tool workflows and game-development tasks.
5. Add distractor and skill-free-correct controls; measure false loading, gold loading, task utility, prompt-token overhead and p50/p95 latency.
6. Only change default skill exposure after a frozen holdout shows a reproducible improvement without regressions.

The central principle is **retrieve broadly, expose narrowly, load deliberately, and promote only when measured downstream utility justifies the context and latency cost**.
