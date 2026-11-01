"""Resolve an explicitly requested Rust edition without inventing a target.

The default stays 2021 for compatibility with existing Litha projects. Edition
selection is separate from the rustc version; no compiler is installed or run
here. A conflicting or unsupported target must remain unverified.
"""
from __future__ import annotations

import re

SUPPORTED = frozenset({"2015", "2018", "2021", "2024"})
DEFAULT = "2021"
_EDITION = re.compile(
    r"\brust\s*(?:edition\s*)?(20\d{2})\b|"
    r"\bedition\s*(?:[=:]\s*[\"']?\s*|\s+)(20\d{2})\b",
    re.I,
)
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})[ \t]*([^\n`]*)$")
_TOML_EDITION = re.compile(r"^\s*edition\s*=\s*[\"'](20\d{2})[\"']\s*(?:#.*)?$", re.M)


def _prose_and_editions(context: str) -> tuple[str, set[str]]:
    """Strip source fences, including an unfinished final fence, linearly."""
    prose: list[str] = []
    body: list[str] = []
    editions: set[str] = set()
    fence = ""
    toml = False
    for line in context.splitlines(keepends=True):
        if not fence:
            opening = _FENCE.fullmatch(line.rstrip("\r\n"))
            if opening:
                fence = opening.group(1)
                toml = opening.group(2).strip().lower() in {"toml", "cargo.toml"}
                body = []
            else:
                prose.append(line)
            continue
        closing = line.strip()
        if len(closing) >= len(fence) and set(closing) == {fence[0]}:
            if toml:
                editions.update(_TOML_EDITION.findall("".join(body)))
            fence = ""
            toml = False
        elif toml:
            body.append(line)
    if fence and toml:
        editions.update(_TOML_EDITION.findall("".join(body)))
    return "".join(prose), editions


def resolve(context: str = "", explicit: str | None = None) -> str:
    """Use a validated explicit field, or a single target in prose/Cargo TOML.

    Quoted Rust source is excluded so a string literal such as
    ``println!(\"Rust 2024\")`` cannot change the compiler target. A TOML fence
    may declare the edition, but is never executed and cannot set rustc flags.
    """
    if explicit is not None:
        if type(explicit) is not str or explicit not in SUPPORTED:
            raise ValueError("unsupported Rust edition; choose 2015, 2018, 2021 or 2024")
        return explicit
    prose, editions = _prose_and_editions(context)
    editions.update(next(value for value in match.groups() if value) for match in _EDITION.finditer(prose))
    if editions - SUPPORTED:
        raise ValueError("unsupported Rust edition; choose 2015, 2018, 2021 or 2024")
    if len(editions) > 1:
        raise ValueError("ambiguous Rust edition; specify one target edition")
    return next(iter(editions), DEFAULT)
