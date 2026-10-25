"""Evidence-first game observation, mechanic hypotheses and reusable design candidates.

This module never controls a game or treats an LLM's interpretation as proven fact.
It accepts a bounded trace of observed steps from an owned recording or approved
sandbox playtest. Save writes unreviewed observations through STAR's KnowledgeStore;
only a separate trusted review flow can promote them to general knowledge.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .knowledge import KnowledgeStore

MAX_STEPS = 64
MAX_SECONDS = 3 * 3600
ACTIONS = frozenset({
    "observe", "move", "look", "jump", "interact", "attack",
    "select", "use", "wait", "open_menu", "other",
})
SOURCE_KINDS = frozenset({"local_video", "owned_studio_playtest", "owner_observation"})
_SOURCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,119}\Z")
DESIGN_PROMPTS = {
    "move": "Prototype movement acceleration, collision response and camera feel.",
    "look": "Prototype camera sensitivity, targeting and line-of-sight feedback.",
    "jump": "Prototype jump arcs, coyote time and landing feedback.",
    "interact": "Prototype readable interaction cues, range checks and feedback.",
    "attack": "Prototype hit confirmation, cooldowns and server-authoritative damage.",
    "select": "Prototype inventory clarity and keyboard/controller selection.",
    "use": "Prototype tool feedback, cooldown and state changes.",
    "open_menu": "Prototype accessible navigation and responsive menu transitions.",
}


def _text(value: Any, name: str, max_chars: int, *, required: bool = True) -> str:
    if type(value) is not str or len(value) > max_chars or (required and not value.strip()):
        raise ValueError(f"{name} must be text of at most {max_chars} characters")
    return value.strip()


def validate_episode(raw: Any) -> dict:
    """Parse a claimed trace; no event is considered independent verification."""
    if type(raw) is not dict:
        raise ValueError("Episode must be an object")
    if set(raw) != {"game", "source_kind", "source_id", "steps"}:
        raise ValueError("Episode needs game, source_kind, source_id and steps only")
    game = _text(raw["game"], "game", 100)
    kind = raw["source_kind"]
    if type(kind) is not str or kind not in SOURCE_KINDS:
        raise ValueError("Unsupported source kind")
    source = _text(raw["source_id"], "source_id", 120)
    if not _SOURCE_ID.fullmatch(source):
        raise ValueError("Source ID must be an opaque, credential-free identifier")
    entries = raw["steps"]
    if type(entries) is not list or not 1 <= len(entries) <= MAX_STEPS:
        raise ValueError("Supply 1 to 64 bounded events")
    normalized: list[dict] = []
    previous = -1.0
    for index, event in enumerate(entries):
        if type(event) is not dict or set(event) - {"at", "action", "seen", "outcome", "success", "frame_sha256"}:
            raise ValueError(f"Invalid step {index}")
        at = event.get("at")
        if type(at) not in (int, float) or not 0 <= at <= MAX_SECONDS or at <= previous:
            raise ValueError("Timestamps must strictly increase within 3 hours")
        previous = float(at)
        action = event.get("action")
        if type(action) is not str or action not in ACTIONS:
            raise ValueError(f"Unsupported action in step {index}")
        success = event.get("success")
        if success is not None and type(success) is not bool:
            raise ValueError("success must be true, false or null")
        digest = event.get("frame_sha256")
        if digest is not None and (type(digest) is not str or not re.fullmatch(r"[a-f0-9]{64}", digest)):
            raise ValueError("frame_sha256 must be a SHA-256 digest of an observed frame")
        normalized.append({
            "at": float(at), "action": action,
            "seen": _text(event.get("seen", ""), "seen", 500, required=False),
            "outcome": _text(event.get("outcome", ""), "outcome", 500, required=False),
            "success": success, "frame_sha256": digest,
        })
    return {"game": game, "source_kind": kind, "source_id": source, "steps": normalized}


def digest_episode(episode: dict) -> str:
    data = json.dumps(episode, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def analyze_episode(raw: dict) -> dict:
    """Make testable candidates from repeated observations; never infer causation."""
    episode = validate_episode(raw)
    by_action: dict[str, list[dict]] = defaultdict(list)
    for step in episode["steps"]:
        by_action[step["action"]].append(step)
    candidates = []
    experiments = []
    design_ideas = []
    for action, steps in sorted(by_action.items()):
        positives = sum(step["success"] is True for step in steps)
        negatives = sum(step["success"] is False for step in steps)
        unknowns = len(steps) - positives - negatives
        evidence_times = [step["at"] for step in steps[:6]]
        if positives and negatives:
            label = "mixed_results"
            test = (f"Repeat {action} in the same starting state with one variable changed; "
                    "measure the result before attributing cause.")
        elif len(steps) < 2 or unknowns == len(steps):
            label = "insufficient_evidence"
            test = f"Repeat {action} in a controlled private playtest and record a measurable before/after state."
        else:
            label = "repeatable_candidate"
            test = (f"Test {action} with a matched control and at least one failure case; "
                    "validate physics/server behavior separately.")
        candidates.append({
            "action": action, "status": label, "count": len(steps),
            "successes": positives, "failures": negatives, "ungraded": unknowns,
            "evidence_times": evidence_times,
            "claim": "Possible interaction pattern; the trace alone cannot prove game mechanics.",
        })
        if action != "observe":
            experiments.append({"action": action, "question": test, "status": "not_run"})
        if action in DESIGN_PROMPTS:
            design_ideas.append({
                "inspired_by": action, "idea": DESIGN_PROMPTS[action],
                "status": "prototype_not_built", "evidence_times": evidence_times[:3],
            })
    return {
        "schema": 1, "game": episode["game"], "source_kind": episode["source_kind"],
        "source_id": episode["source_id"], "episode_sha256": digest_episode(episode),
        "observations": len(episode["steps"]),
        "candidate_mechanics": candidates,
        "suggested_experiments": experiments[:12],
        "original_design_ideas": design_ideas[:10],
        "verified_mechanics": 0,
        "limitations": (
            "Supplied descriptions and outcome labels are untrusted observations, not "
            "measured gameplay state. Video alone cannot establish hidden rules, "
            "hitboxes or server logic. Confirm with authorized sandbox playtests."
        ),
    }


def save_candidate(home: Path, project: str, raw: dict) -> dict:
    """Explicit opt-in only; prevents model-generated content entering reviewed memory."""
    report = analyze_episode(raw)
    content = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(content) > 16000:
        raise ValueError("Episode report too large; reduce event descriptions")
    store = KnowledgeStore(Path(home) / "knowledge")
    try:
        note = store.add_note(
            project=project, kind="observation", text=content,
            source="game-experience:" + report["episode_sha256"],
            revision=report["episode_sha256"],
        )
    finally:
        store.close()
    return {
        "note_id": note, "project": project, "reviewed": False,
        "episode_sha256": report["episode_sha256"],
        "note": "Saved as a candidate only. Not used as verified general knowledge.",
    }


def search_candidates(home: Path, project: str, query: str, limit: int = 6) -> dict:
    if type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError("Limit must be 1 to 12")
    query = _text(query, "query", 300)
    store = KnowledgeStore(Path(home) / "knowledge")
    try:
        notes = store.find(project, query, reviewed_only=False, limit=50)
    finally:
        store.close()
    found = []
    for note in notes:
        if not note.source.startswith("game-experience:"):
            continue
        try:
            body = json.loads(note.text)
        except ValueError:
            continue
        found.append({
            "note_id": note.id, "reviewed": note.reviewed, "source": note.source,
            "game": body.get("game"), "observations": body.get("observations"),
            "candidate_mechanics": body.get("candidate_mechanics", [])[:8],
        })
        if len(found) >= limit:
            break
    return {"project": project, "candidates": found,
            "note": "Unreviewed candidates must not become system facts or training labels."}
