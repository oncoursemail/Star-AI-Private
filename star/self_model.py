"""STAR's evidence-grounded *operational* self-model for the active agent turn.

This module is intentionally NOT a consciousness simulator, an authority layer,
a persistent memory store, or proof that an attached tool works. It only reports
trusted host observations: schemas attached to THIS request and the outcomes
that the host actually received. It does not read files or call the network.

The model's prose, retrieved pages, and tool arguments cannot grant capabilities
or create success receipts.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
import re

SELF_TOOL = {
    "name": "star_self_state",
    "description": (
        "Inspect STAR's actual attached tools and host-observed tool outcomes "
        "in THIS conversation turn. Read-only. Attached is not the same as "
        "connected or tested. Does not prove consciousness, task success, "
        "permission to run code, or any improvement in model weights."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "tool_names": {
                "type": "array", "maxItems": 12, "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 90},
                "description": "Optional exact tool names to check against this turn's attached schemas.",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
}
_SELF_NAME = SELF_TOOL["name"]
_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,89}$")
_SELF_TRIGGER = re.compile(
    r"\b(?:self[- ]?awar(?:e|eness)|introspect\w*|metacognit\w*|"
    r"what (?:are|were) you (?:doing|working on|able to do)|"
    r"what can you (?:actually )?do|"
    r"what (?:tools|skills|capabilities|permissions|limits) "
    r"(?:do you have|are (?:currently )?available)|"
    r"what do you (?:know|have|remember) about (?:yourself|your tools)|"
    r"show (?:me )?(?:your|star'?s) (?:current )?(?:capabilities|tools|status)|"
    r"star (?:awareness|self[- ]?model|capabilities))\b", re.I,
)
_MAX_SCHEMAS = 256
_MAX_RETURNED = 72
_MAX_EVENTS = 12


def wants_self_inspection(prompt: str) -> bool:
    """Prompt-gate schema overhead: ordinary chat never gets another tool."""
    return isinstance(prompt, str) and bool(_SELF_TRIGGER.search(prompt[:8000]))


class TurnSelfModel:
    """Transient host-owned ledger. Not user-editable memory or a security gate.

    Actual authorization remains in star.policy and each tool adapter.
    Nothing recorded here is evidence that the final user task was successful.
    """

    def __init__(self, definitions: Sequence[Mapping[str, object]]) -> None:
        if not isinstance(definitions, (list, tuple)) or len(definitions) > _MAX_SCHEMAS:
            raise ValueError("Attached tool set exceeds the self-model limit")
        names: set[str] = set()
        for definition in definitions:
            if not isinstance(definition, Mapping):
                continue
            function = definition.get("function")
            if not isinstance(function, Mapping):
                continue
            name = function.get("name")
            if isinstance(name, str) and _TOOL_NAME.fullmatch(name):
                names.add(name)
        self._attached = frozenset(names)
        self._events: deque[dict] = deque(maxlen=_MAX_EVENTS)

    def record(self, name: str, *, executed: bool, is_error: bool,
               uncertain: bool = False) -> None:
        """Record an actual host dispatch result; never store output or arguments."""
        if name == _SELF_NAME:
            return
        if any(type(flag) is not bool for flag in (executed, is_error, uncertain)):
            raise TypeError("Host evidence flags must be booleans")
        safe_name = name if isinstance(name, str) and _TOOL_NAME.fullmatch(name) else "(invalid)"
        status = ("outcome_uncertain" if uncertain else
                  "rejected_before_execution" if not executed else
                  "tool_reported_error" if is_error else
                  "tool_returned_without_error")
        self._events.append({
            "tool": safe_name,
            "attached": safe_name in self._attached,
            "status": status,
        })

    def inspect(self, tool_names: Sequence[str] = ()) -> dict:
        """Show observed capabilities without confusing registration with proof."""
        if not isinstance(tool_names, (list, tuple)) or len(tool_names) > 12:
            raise ValueError("Provide at most twelve exact tool names")
        if len(set(tool_names)) != len(tool_names) or any(
            not isinstance(name, str) or not _TOOL_NAME.fullmatch(name) for name in tool_names
        ):
            raise ValueError("Tool names must be unique, valid identifiers")
        offered = sorted(self._attached)
        events = list(self._events)
        last_status = events[-1]["status"] if events else None
        next_step = {
            None: "No tool action has been observed in this turn.",
            "outcome_uncertain": "Read back state with an authorized tool before retrying a possibly applied action.",
            "rejected_before_execution": "Do not bypass the missing authorization; ask for an allowed route.",
            "tool_reported_error": "Inspect the failure and choose a bounded, authorized corrective action.",
            "tool_returned_without_error": "A tool returned normally; verify the overall task independently.",
        }[last_status]
        return {
            "scope": "current_turn_only",
            "kind": "operational_self_model_not_consciousness",
            "tool_count": len(offered),
            "attached_tools": offered[:_MAX_RETURNED],
            "tools_omitted": max(0, len(offered) - _MAX_RETURNED),
            "requested_tools": [
                {"name": name, "status": "attached_schema_only" if name in self._attached
                 else "not_attached_to_this_turn"} for name in tool_names
            ],
            "recent_tool_outcomes": events,
            "suggested_next_check": next_step,
            "limits": [
                "Attached schema does not prove a live connection, permission for new actions, or reliable performance.",
                "A successful tool response is not proof that the finished work passed tests or meets visual quality.",
                "No tool outcome by itself demonstrates learning, increased intelligence, or subjective consciousness.",
                "Other background processes and hardware state are not inspected by this tool.",
            ],
        }
