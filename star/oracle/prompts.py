"""The scored prompt for one request under one config: Star's plain-chat system message, the user's words and the
same per-turn reference blocks the app adds for the prompt-side settings (api hints, worked examples, gold examples).

This is an approximation of a real turn: no documentation search, no tools, no memory, and gold examples are ranked
by the app's word ranking (the live app prefers embeddings). Both arms of a comparison get the same approximation, so
it cancels in the paired margin; it is still why L2 is calibrated against full evals before anyone trusts it.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .config import TEMPLATES, Config


@lru_cache(maxsize=1)
def default_system() -> str:
    from ..agent import make_system_message
    from ..brain_router import ROBLOX_QUALITY_NOTES
    return make_system_message("", tools_attached=False, guidance=ROBLOX_QUALITY_NOTES)["content"]


@lru_cache(maxsize=4)
def _worked_bank(path: str):
    from .. import worked_examples
    return worked_examples.parse_export(Path(path).read_bytes())


def sections(prompt: str, settings: dict, *, exclude_answer: str = "") -> list[tuple[str, str]]:
    """(heading, text) blocks in the order desktop_core adds them. `exclude_answer`: an example whose answer is the
    text being scored is skipped (it would be copied, not judged)."""
    out: list[tuple[str, str]] = []
    if settings.get("api_hints_enabled") is True:
        from .. import api_hints
        from ..slop import bundled_api_dump
        dump = bundled_api_dump()
        block = api_hints.hint_block(prompt, dump) if dump is not None else ""
        if block:
            out.insert(0, (api_hints.BLOCK_HEADING, block))
    if settings.get("worked_bank"):
        from .. import worked_examples
        budget = int(settings.get("worked_bank_chars", worked_examples.MAX_PROMPT_CHARS))
        parts, used = [], 0
        rows = [r for r in _worked_bank(settings["worked_bank"])
                if not exclude_answer or r.response.strip() != exclude_answer.strip()]
        for example, _score in worked_examples.rank(prompt, rows):
            line = (f"[checked practice {used + 1}; claimed automated checks, unreviewed; not Studio verification]\n"
                    f"Request: {example.instruction}\nExample response:\n{example.response}\n[end checked practice]\n")
            if len(line) + sum(map(len, parts)) > budget:
                continue
            parts.append(line)
            used += 1
        if parts:
            out.append((worked_examples.HEADING, "".join(parts)))
    if settings.get("gold_examples_enabled") is True:
        from .. import gold_bank
        items = [i for i in gold_bank.load() if not exclude_answer or i.answer.strip() != exclude_answer.strip()]
        ranked = gold_bank.rank_by_words(prompt, items)
        block, _used = gold_bank.render([item for _, item in ranked[:gold_bank.MAX_EXAMPLES * 2]])
        if block:
            out.append((gold_bank.HEADING, block))
    return out


def prefix(cfg: Config, prompt: str, *, exclude_answer: str = "") -> str:
    """The model input up to the first answer token."""
    from ..context_layout import context_block, final_user_text
    blocks = sections(prompt, cfg.settings, exclude_answer=exclude_answer)
    user = final_user_text(prompt, context_block(blocks, limit=20000) if blocks else "")
    template, _eos = TEMPLATES[cfg.template]
    return template.format(system=cfg.system if cfg.system is not None else default_system(), user=user,
                           assistant_prefix=cfg.assistant_prefix)


def target(cfg: Config, answer: str) -> str:
    return answer + TEMPLATES[cfg.template][1]
