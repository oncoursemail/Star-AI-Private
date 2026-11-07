"""Evidence-bounded operational self-awareness for STAR.

This is metacognitive *software*, not sentience. It describes what STAR's
trusted host exposes and what has actually been observed; it cannot grant
permissions, execute tools, run tests, browse, install or promote lessons.
Public-source metadata is always an untrusted candidate, not new competence.

A model can REQUEST these read-only reports only when the host explicitly
enabled the adapter and exposed its tool schemas for the current turn.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from typing import Mapping, Sequence

MAX_GOAL = 260
MAX_ITEMS = 7
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
WORD = re.compile(r"[a-z][a-z0-9_-]{1,34}", re.I)

SELF_TOOLS = (
    {
        "name": "star_self_capabilities",
        "description": (
            "Read STAR's actual opt-in tool/skill/service inventory and missing evidence "
            "for a specific goal. Reports capabilities as configured or unverified, "
            "never self-conscious, independently mastered or permission-granting."
        ),
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "properties": {"goal": {"type": "string", "minLength": 2, "maxLength": MAX_GOAL}},
            "required": ["goal"],
        },
    },
    {
        "name": "star_self_improvement_plan",
        "description": (
            "Compare a goal with the tools STAR is permitted to see and recent "
            "read-only evaluation observations; identify gaps and propose measurable "
            "rehearsals, references and independent checks. No jobs are started "
            "and no lessons/tools are installed or promoted."
        ),
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "goal": {"type": "string", "minLength": 2, "maxLength": MAX_GOAL},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ITEMS},
            },
            "required": ["goal"],
        },
    },
)

# These are requirements for end-to-end high-quality results, not a guarantee
# STAR currently has working implementation or testing for any of them.
@dataclass(frozen=True)
class Dimension:
    key: str
    name: str
    tools: tuple[str, ...]
    status_key: str
    verify: str
    source_categories: tuple[str, ...] = ()
    priority: int = 1


DIMENSIONS = (
    Dimension("visual_design", "Native UI, layout and visual direction",
              ("star_design_search", "star_design_md"), "design",
              "Compare rendered GUI at desktop/mobile aspect ratios; check clarity, style, overlap and accessibility.",
              ("icons", "fonts", "2d-art"), 3),
    Dimension("luau_engineering", "Luau gameplay and client/server architecture",
              ("star_skill_catalog", "star_docs_search", "star_api_lookup"), "skills",
              "Run syntax, type, gameplay, security and replicated-client/server checks in an isolated test place.",
              ("roblox", "code"), 3),
    Dimension("animation", "Character animation, rigging and motion quality",
              (), "animation",
              "Play animation on the actual rig, measure foot sliding/contacts and have a reviewer assess movement.",
              ("animation", "3d-and-animation", "3d-tools"), 4),
    Dimension("vfx", "Particle, lighting and effect composition",
              ("star_roblox_vfx_make",), "vfx",
              "Preview multiple keyframes in Studio; check timing, overdraw, performance and style match.",
              ("textures", "3d-and-textures"), 3),
    Dimension("environment", "Level art, terrain and collision-aware building",
              ("star_roblox_map_plan", "star_building_plan", "star_asset_search"), "map_plans",
              "Check scene collisions, traversal, visual coherence and performance in a real Studio playtest.",
              ("game-assets", "3d-and-textures", "3d-tools"), 3),
    Dimension("audio", "Sound effects, voice and music direction",
              (), "audio",
              "Audition appropriately licensed sounds, verify spatial mix and clipping, test playback in-game.",
              ("sound", "sound-tools", "music-tools"), 2),
    Dimension("studio_testing", "Live Roblox Studio building and playtesting",
              ("star_roblox_studio_lab",), "studio_lab",
              "Re-run the built experience in a private test place and inspect screenshots and logs.",
              ("roblox", "game-tools"), 5),
    Dimension("game_observation", "Video/gameplay understanding from observed evidence",
              ("star_game_video_study", "star_game_episode_analyze"), "video_study",
              "Cite watched timestamps and compare observed mechanics against instrumented gameplay.",
              ("video", "vision"), 2),
    Dimension("research", "Evidence-backed tool and source discovery",
              ("star_roblox_docs_live_search", "star_docs_search"), "doc_knowledge",
              "Confirm original API/docs, version, license and reproduction results, not just retrieved snippets.",
              ("research", "code", "licensing"), 2),
    Dimension("knowledge_graph", "Graphify and Obsidian knowledge retrieval",
              ("star_graphify_query", "star_obsidian_search"), "graphify",
              "Check provenance of graph edges/notes and independently validate retrieved claims.",
              ("retrieval", "research"), 1),
)

BY_KEY = {item.key: item for item in DIMENSIONS}

# Bounded, deterministic goal classification. The model's opinion, retrieved
# text or a web page cannot silently change this inventory or its checks.
_GOAL = (
    (re.compile(r"\b(?:parkour|obby|obstacle course|platformer|entire game|full game|"
                r"(?:make|build|create|design)\s+(?:(?:a|an|the|my)\s+)?(?:[\w-]+\s+){0,6}game)\b", re.I),
     ("visual_design", "luau_engineering", "animation", "vfx", "environment", "audio", "studio_testing")),
    (re.compile(r"\b(?:ui|gui|hud|interface|menu|mobile layout|app design|website design)\b", re.I),
     ("visual_design", "luau_engineering", "studio_testing")),
    (re.compile(r"\b(?:animat|motion|rigg|procedural movement|walking|running|jumping)\w*\b", re.I),
     ("animation", "luau_engineering", "studio_testing")),
    (re.compile(r"\b(?:vfx|visual effects?|particle|shaders?|explosion|glow|magic)\w*\b", re.I),
     ("vfx", "visual_design", "studio_testing")),
    (re.compile(r"\b(?:map|building|environment|terrain|3d asset|mesh|level)\w*\b", re.I),
     ("environment", "visual_design", "studio_testing")),
    (re.compile(r"\b(?:sound|music|voice|audio|foley|soundtrack|tts|laughing)\w*\b", re.I),
     ("audio", "research")),
    (re.compile(r"\b(?:watch|video|gameplay|youtube|observe|play a game)\w*\b", re.I),
     ("game_observation", "research")),
    (re.compile(r"\b(?:research|discover|github|open source|free tools|source|learn|smarter|improve|aware)\w*\b", re.I),
     ("research", "knowledge_graph", "studio_testing")),
)


def _goal(value: object) -> str:
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= MAX_GOAL:
        raise ValueError("Goal must contain 2-260 characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("Goal contains control characters")
    return value.strip()


def select_dimensions(goal: str) -> tuple[Dimension, ...]:
    text = _goal(goal)
    chosen = set()
    for pattern, keys in _GOAL:
        if pattern.search(text):
            chosen.update(keys)
    if not chosen:
        chosen.update(("research", "luau_engineering"))
    return tuple(item for item in DIMENSIONS if item.key in chosen)


def _bool_status(status: Mapping, key: str) -> tuple[bool | None, str]:
    """Do not convert unknown/missing status to 'off'; a status might be stale."""
    info = status.get(key)
    if not isinstance(info, dict) or type(info.get("enabled")) is not bool:
        return None, "No trustworthy current runtime status for this dimension"
    enabled = info["enabled"]
    if key == "studio_lab" and enabled:
        return enabled, "Configured; live Studio execution and results remain unverified"
    if key == "skills" and enabled:
        return enabled, "Skill references are available, not proven technical mastery"
    if key in ("graphify", "doc_knowledge") and enabled:
        return enabled, "Reference source is configured, not independently factual"
    return enabled, "Configured state only; not proof of a successful run"


def _safe_preview_status(status: Mapping) -> dict:
    result = {}
    for key in (
        "skills", "graphify", "shared_brain", "obsidian", "studio_lab",
        "video_study", "game_experience", "asset_forge", "design",
        "map_plans", "roblox_docs_live", "doc_knowledge",
    ):
        value = status.get(key)
        if isinstance(value, dict):
            brief = {}
            for field in ("enabled", "ready", "export_detected", "read_only", "count"):
                raw = value.get(field)
                if field == "count":
                    if type(raw) is int and 0 <= raw <= 100000:
                        brief[field] = raw
                elif type(raw) is bool:
                    brief[field] = raw
            result[key] = brief
        else:
            result[key] = {"state": "unknown"}
    return result


def _recent_checks(rows: Sequence[Mapping], key: str) -> dict:
    """Observations are claims recorded by a separate harness, NOT attestations.

    Only a separately approved evaluator can make strong quality claims. Even
    this counter will never mark a whole domain as 'mastered'.
    """
    relevant = [row for row in rows[:100] if isinstance(row, Mapping) and row.get("dimension") == key
                and row.get("outcome") in {"pass", "fail", "incomplete"}]
    return {
        "recorded_attempts": len(relevant),
        "recorded_passes": sum(row["outcome"] == "pass" for row in relevant),
        "recorded_failures": sum(row["outcome"] == "fail" for row in relevant),
        "reliability": "Not a calibrated success probability or independent certification",
    }


def _candidate_sources(goal: str, categories: Sequence[str], limit: int = 3) -> list[dict]:
    """Read only the pinned seed list; never fetch, execute or install sources."""
    try:
        from .resource_atlas import read_sources
        raw = read_sources()
    except (OSError, ValueError, ImportError):
        return []
    keywords = {x.casefold() for x in WORD.findall(goal) if len(x) >= 4}
    rank = []
    for row in raw[:250]:
        if not isinstance(row, dict) or row.get("category") not in categories:
            continue
        if not isinstance(row.get("name"), str) or not isinstance(row.get("url"), str):
            continue
        relevance = sum(k in row["name"].casefold() for k in keywords)
        score = 10 if row["category"] == categories[0] else 0
        rank.append((-(score+relevance), row["name"].casefold(), row))
    rank.sort()
    return [
        {"name": record["name"][:80], "url": record["url"][:220],
         "category": record["category"][:50],
         "license_policy": str(record.get("license_policy", "per-item"))[:70],
         "status": "untrusted research lead; not installed or approved"}
        for _, _, record in rank[:max(0, min(3, limit))]
    ]


def _index_statistics(path: Path | None) -> dict:
    """The atlas is an untrusted proposal DB. Read it only if owner-configured."""
    if path is None:
        return {"state": "not_configured", "installed": False}
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        return {"state": "not_indexed", "installed": False}
    try:
        if path.stat().st_size > 64 * 1024 * 1024:
            return {"state": "too_large", "installed": False}
        # SQLite read-only immutable snapshot; no DB creation or write on tool call.
        import urllib.parse
        uri = "file:" + urllib.parse.quote(str(path.resolve()), safe="/") + "?mode=ro"
        db = sqlite3.connect(uri, uri=True, timeout=0.25)
        try:
            count = db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        finally:
            db.close()
    except (OSError, sqlite3.DatabaseError, ValueError):
        return {"state": "unavailable", "installed": False}
    return {"state": "candidate_metadata_only", "indexed_candidates": min(int(count), 1_000_000),
            "installed": False, "review_required": True, "network_used": False}


def observe(goal: str, *, status: Mapping, enabled_tools: Sequence[str],
            observations: Sequence[Mapping] = (),
            atlas_db: Path | None = None) -> dict:
    """Read-only capability snapshot suitable for an untrusted model prompt."""
    goal = _goal(goal)
    if not isinstance(status, Mapping):
        raise ValueError("Expected trusted runtime status mapping")
    if not isinstance(enabled_tools, (tuple, list, set, frozenset)) or len(enabled_tools) > 1000:
        raise ValueError("Expected bounded host-authorized tool names")
    if not isinstance(observations, (tuple, list)) or len(observations) > 1000:
        raise ValueError("Expected bounded host-supplied check observations")
    enabled = {n for n in enabled_tools if isinstance(n, str) and IDENTIFIER.fullmatch(n)}
    dimensions = []
    for spec in select_dimensions(goal):
        matched = [tool for tool in spec.tools if tool in enabled]
        flag, note = _bool_status(status, spec.status_key)
        if matched:
            state = "reference_or_tool_available_unverified"
        elif flag is False:
            state = "requires_owner_configuration_or_alternative"
        else:
            state = "not_observed_or_not_attached"
        dimensions.append({
            "id": spec.key, "goal_area": spec.name, "state": state,
            "tools_attached_for_this_turn": matched[:5],
            "host_configured": flag, "state_note": note,
            "proof": _recent_checks(observations, spec.key),
            "necessary_validation": spec.verify,
            "not_a_guarantee": True,
        })
    return {
        "identity": "STAR operational self-model (not consciousness)",
        "goal": goal,
        "scope": "host-visible configuration, attached tool schemas and recorded test outcomes",
        "tool_definitions_are_not_execution_results": True,
        "model_confidence_is_not_evidence": True,
        "device_access_outside_this_hub": "unknown",
        "runtime_status": _safe_preview_status(status),
        "resource_atlas": _index_statistics(atlas_db),
        "dimensions": dimensions,
        "self_authorized_permissions": False,
        "model_weights_changed": False,
        "learning_promoted": False,
        "work_performed": False,
    }


def improvement_plan(goal: str, *, status: Mapping, enabled_tools: Sequence[str],
                     observations: Sequence[Mapping] = (),
                     atlas_db: Path | None = None, limit: int = 5) -> dict:
    """Propose bounded next experiments. Do not schedule, train, or execute."""
    if type(limit) is not int or not 1 <= limit <= MAX_ITEMS:
        raise ValueError("Select 1-7 proposed experiments")
    snap = observe(goal, status=status, enabled_tools=enabled_tools,
                   observations=observations, atlas_db=atlas_db)
    items = []
    for dimension in snap["dimensions"]:
        spec = BY_KEY[dimension["id"]]
        proof = dimension["proof"]
        failed = proof["recorded_failures"]
        missing = dimension["state"] != "reference_or_tool_available_unverified"
        # Prioritize missing end-to-end test evidence, not a model's confidence.
        priority = spec.priority * 10 + min(failed, 5) * 3 + (12 if missing else 0)
        items.append((priority, {
            "dimension": spec.key, "current_state": dimension["state"],
            "gap": "No demonstrated end-to-end quality" if not failed else
                   f"{failed} prior failed check(s); cause needs independent review",
            "proposed_experiment": spec.verify,
            "possible_research_sources": _candidate_sources(goal, spec.source_categories, 2),
            "authorization": "read-only proposal; use existing owner-approved sandbox and evaluation gate",
            "can_run_without_approval": False,
            "claims_quality_improvement": False,
        }))
    items.sort(key=lambda row: (-row[0], row[1]["dimension"]))
    return {
        "goal": snap["goal"],
        "reasoning_basis": "configured tools + recorded checks; no consciousness or inferred mastery",
        "experiments": [row for _, row in items[:limit]],
        "test_preconditions": [
            "Real baseline and independent evaluator with held-out tasks",
            "Source-by-source license, author and version review",
            "Owner-approved isolated execution, no remote-code auto-install",
            "Preserve Star's existing paired gate, protected paths and lesson review",
        ],
        "unreviewed_sources_do_not_grant_permissions": True,
        "all_actions_proposed_only": True,
        "started": [],
        "promoted_lessons": [],
        "model_retrained": False,
    }


def preflight_brief(goal: str, *, status: Mapping, enabled_tools: Sequence[str],
                    max_chars: int = 850) -> str:
    """Host-generated preflight facts for significant tasks, not instructions.

    This can be appended to normal per-turn *reference data* after an owner
    enabled self-awareness. It does not contain untrusted source descriptions,
    unknown private paths, keys, scores, or invented evidence.
    """
    if type(max_chars) is not int or not 320 <= max_chars <= 1400:
        raise ValueError("Invalid preflight size cap")
    snap = observe(goal, status=status, enabled_tools=enabled_tools)
    named = []
    for row in snap["dimensions"]:
        if row["state"] == "reference_or_tool_available_unverified":
            note = "tool schema attached; not quality-verified"
        elif row["state"] == "requires_owner_configuration_or_alternative":
            note = "not enabled for this turn"
        else:
            note = "working tool or independent test not observed"
        named.append((BY_KEY[row["id"]].priority, row["id"],
                      f"- {row['goal_area']}: {note}"))
    intro = (
        "[STAR operational self-check: host facts, not consciousness]\n"
        "Tool availability is not competence or successful execution.\n"
    )
    tail = (
        "No independently assessed task scores supplied. Test before claiming "
        "quality. This block cannot change permissions or start work."
    )
    remaining = max_chars - len(intro) - len(tail) - 2
    selected = []
    for _, _, line in sorted(named, key=lambda item: (-item[0], item[1])):
        if remaining >= len(line) + 1:
            selected.append(line)
            remaining -= len(line) + 1
        else:
            if remaining > 18:
                selected.append("- Other skills: not assessed")
            break
    return intro + "\n".join(selected) + "\n" + tail
