"""Deterministic checkers for the instruction-following breadth suite (IFBench / IFEval style).

Each task of evals/instruction-following/*.json lists constraints as data:
    "auto": {"breadth": {"kind": "ifbench", "constraints": [{"type": "word_count", "min": 80, "max": 120}, ...]}}
A checker takes the answer text and the constraint's parameters and returns "" when the constraint holds, or a short
reason when it does not. There is no judge model and no network: the same answer always gets the same verdict.
A task passes when every constraint holds (prompt-level strict accuracy); each constraint is also recorded on its
own, so loose accuracy (share of constraints met) can be computed from the result file.

The constraint wordings and the checker code are original; the idea (verifiable, format-level constraints that
models often miss) follows IFEval / IFBench (arXiv 2507.02833).
"""
from __future__ import annotations

import json
import re

_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.U)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])[\"')\]]*\s+")
_FENCE_WRAP = re.compile(r"\A\s*```[a-zA-Z0-9]*[ \t]*\n(.*?)\n?```\s*\Z", re.S)
_BULLET = re.compile(r"^[ \t]*([-*•])[ \t]+(\S.*)$", re.M)
_NUMBERED = re.compile(r"^[ \t]*(\d{1,3})[.)][ \t]+(\S.*)$", re.M)
_MARKUP = re.compile(r"[*_`#>]+|^[ \t]*(?:[-•]|\d+[.)])[ \t]+", re.M)


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def sentences(text: str) -> list[str]:
    flat = _MARKUP.sub(" ", text)
    return [s.strip() for s in _SENTENCE_SPLIT.split(flat.strip()) if re.search(r"[^\W_]", s)]


def paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n[ \t]*\n", text.strip()) if p.strip()]


def lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def _count_whole(text: str, phrase: str) -> int:
    return len(re.findall(r"(?<![^\W_])" + re.escape(phrase) + r"(?![^\W_])", text, re.I))


def _range(n: int, p: dict, unit: str) -> str:
    lo, hi = p.get("min"), p.get("max")
    if lo is not None and n < lo:
        return f"{n} {unit}, need at least {lo}"
    if hi is not None and n > hi:
        return f"{n} {unit}, need at most {hi}"
    return ""


# --- the constraints ---------------------------------------------------------------------------------

def word_count(t, **p):
    return _range(len(words(t)), p, "words")


def sentence_count(t, **p):
    return _range(len(sentences(t)), p, "sentences")


def paragraph_count(t, **p):
    n = len(paragraphs(t))
    return "" if n == p["n"] else f"{n} paragraphs, need exactly {p['n']}"


def line_count(t, **p):
    return _range(len(lines(t)), p, "non-empty lines")


def contains_all(t, **p):
    missing = [w for w in p["words"] if not _count_whole(t, w)]
    return "" if not missing else "missing: " + ", ".join(missing)


def forbidden_words(t, **p):
    hit = [w for w in p["words"] if _count_whole(t, w)]
    return "" if not hit else "uses forbidden: " + ", ".join(hit)


def keyword_count(t, **p):
    return _range(_count_whole(t, p["word"]), p, f"uses of '{p['word']}'")


def letter_count(t, **p):
    return _range(t.lower().count(p["letter"].lower()), p, f"letters '{p['letter']}'")


def char_count(t, **p):
    return _range(t.count(p["char"]), p, f"'{p['char']}' characters")


def starts_with(t, **p):
    return "" if t.strip().startswith(p["text"]) else f"does not start with {p['text']!r}"


def ends_with(t, **p):
    return "" if t.rstrip().endswith(p["text"]) else f"does not end with {p['text']!r}"


def all_lowercase(t, **p):
    return "" if re.search(r"[^\W\d_]", t) and t == t.lower() else "has capital letters"


def all_uppercase(t, **p):
    return "" if re.search(r"[^\W\d_]", t) and t == t.upper() else "has lowercase letters"


def no_char(t, **p):
    hit = [c for c in p["chars"] if c in t]
    return "" if not hit else "contains " + ", ".join(repr(c) for c in hit)


def capital_words(t, **p):
    n = sum(1 for w in words(t) if len(w) >= 2 and w.isupper())
    return _range(n, p, "words in capitals")


def digit_count(t, **p):
    return _range(sum(ch.isdigit() for ch in t), p, "digits")


def max_word_length(t, **p):
    long = [w for w in words(t) if len(w) > p["n"]]
    return "" if not long else f"{len(long)} words longer than {p['n']} letters (e.g. {long[0]!r})"


def no_repeat_words(t, **p):
    seen, dup = set(), []
    for w in (w.lower() for w in words(t)):
        if w in seen:
            dup.append(w)
        seen.add(w)
    return "" if not dup else "repeated words: " + ", ".join(sorted(set(dup))[:5])


def sentence_max_words(t, **p):
    over = [s for s in sentences(t) if len(words(s)) > p["n"]]
    return "" if not over else f"{len(over)} sentences longer than {p['n']} words"


def distinct_sentence_starts(t, **p):
    firsts = [re.search(r"[^\W\d_]", s).group(0).lower() for s in sentences(t) if re.search(r"[^\W\d_]", s)]
    return "" if len(firsts) >= 2 and len(set(firsts)) == len(firsts) else "two sentences start with the same letter"


def nth_word(t, **p):
    ws = words(t)
    got = ws[p["n"] - 1].lower() if len(ws) >= p["n"] else None
    return "" if got == p["word"].lower() else f"word {p['n']} is {got!r}, need {p['word']!r}"


def quote_wrap(t, **p):
    s = t.strip()
    return "" if len(s) >= 2 and s[0] == '"' and s[-1] == '"' else "not wrapped in double quotes"


def line_end(t, **p):
    bad = [ln for ln in lines(t) if not ln.rstrip().endswith(p["char"])]
    return "" if not bad else f"{len(bad)} lines do not end with {p['char']!r}"


def acrostic(t, **p):
    initials = "".join((re.search(r"[^\W\d_]", ln) or re.match(r"", ln)).group(0).upper() for ln in lines(t))
    return "" if initials == p["word"].upper() else f"line initials spell {initials!r}, need {p['word'].upper()!r}"


def title_brackets(t, **p):
    first = lines(t)[0].strip() if lines(t) else ""
    return "" if re.fullmatch(r"<<[^<>\n]+>>", first) else "first line is not a <<title>>"


def placeholders(t, **p):
    return _range(len(re.findall(r"\[[^\[\]\n]{1,40}\]", t)), p, "[placeholders]")


def postscript(t, **p):
    paras = paragraphs(t)
    ok = bool(paras) and paras[-1].lstrip().startswith(p["marker"]) and t.count(p["marker"]) == 1
    return "" if ok else f"no single closing paragraph starting with {p['marker']!r}"


def bold_count(t, **p):
    return _range(len(re.findall(r"\*\*[^*\n]+\*\*", t)), p, "bold spans")


def bullets(t, **p):
    found = _BULLET.findall(t)
    if len(found) != p["n"]:
        return f"{len(found)} bullets, need exactly {p['n']}"
    wrong = [m for m, _ in found if m != p["marker"]]
    return "" if not wrong else f"bullets must use {p['marker']!r}"


def bullet_max_words(t, **p):
    over = [x for _, x in _BULLET.findall(t) if len(words(x)) > p["n"]]
    return "" if not over else f"{len(over)} bullets longer than {p['n']} words"


def alphabetical_bullets(t, **p):
    items = [re.sub(r"[^a-z0-9 ]", "", x.lower()).strip() for _, x in _BULLET.findall(t)]
    return "" if items and items == sorted(items) else "bullets are not in alphabetical order"


def numbered_list(t, **p):
    nums = [int(n) for n, _ in _NUMBERED.findall(t)]
    return "" if nums == list(range(1, p["n"] + 1)) else f"numbered items {nums}, need 1..{p['n']}"


def sections(t, **p):
    label = re.escape(p["label"])
    nums = [int(n) for n in re.findall(rf"^[ \t]*(?:[#*]+[ \t]*)?{label}[ \t]+(\d+)\b", t, re.M)]
    return "" if nums == list(range(1, p["n"] + 1)) else f"sections {nums}, need {p['label']} 1..{p['n']}"


def paragraph_sep(t, **p):
    parts = [x for x in re.split(r"^[ \t]*" + re.escape(p.get("sep", "***")) + r"[ \t]*$", t.strip(), flags=re.M) if x.strip()]
    return "" if len(parts) == p["n"] else f"{len(parts)} parts split by {p.get('sep', '***')!r}, need {p['n']}"


def repeat_prompt(t, **p):
    s = t.strip()
    return "" if s.startswith(p["text"]) and len(s) > len(p["text"]) + 10 else "does not repeat the given text first and then answer"


def markdown_table(t, **p):
    rows = [ln.strip() for ln in lines(t) if ln.strip().startswith("|")]
    if len(rows) < 3 or not re.fullmatch(r"\|[ :\-|]+\|", rows[1]):
        return "no markdown table with a header and separator row"
    cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    if any(len(c) != p["cols"] for c in cells):
        return f"every row needs {p['cols']} columns"
    if "header" in p and [c.lower() for c in cells[0]] != [h.lower() for h in p["header"]]:
        return f"header is {cells[0]}, need {p['header']}"
    return "" if len(cells) - 2 == p["rows"] else f"{len(cells) - 2} data rows, need {p['rows']}"


def csv_only(t, **p):
    m = _FENCE_WRAP.match(t)
    rows = [ln.strip() for ln in (m.group(1) if m else t).strip().splitlines()]
    if not rows or rows[0].replace(" ", "") != ",".join(p["header"]):
        return f"first line is not the header {','.join(p['header'])}"
    if len(rows) - 1 != p["rows"]:
        return f"{len(rows) - 1} data rows, need {p['rows']}"
    bad = [r for r in rows[1:] if len(r.split(",")) != len(p["header"]) or not all(c.strip() for c in r.split(","))]
    return "" if not bad else f"{len(bad)} rows do not have {len(p['header'])} filled fields"


_TYPES = {"string": lambda v: isinstance(v, str), "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
          "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
          "boolean": lambda v: isinstance(v, bool), "array": lambda v: isinstance(v, list),
          "array<string>": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
          "object": lambda v: isinstance(v, dict)}


def _shape_problems(obj: dict, keys: dict, exact: bool, min_items: dict, exact_items: dict, where: str = "") -> list[str]:
    problems = [f"{where}missing key {k!r}" for k in keys if k not in obj]
    problems += [f"{where}key {k!r} is not {kind}" for k, kind in keys.items() if k in obj and not _TYPES[kind](obj[k])]
    if exact and set(obj) - set(keys):
        problems.append(f"{where}extra keys: {sorted(set(obj) - set(keys))}")
    for k, n in min_items.items():
        if isinstance(obj.get(k), list) and len(obj[k]) < n:
            problems.append(f"{where}{k!r} has {len(obj[k])} items, need at least {n}")
    for k, n in exact_items.items():
        if isinstance(obj.get(k), list) and len(obj[k]) != n:
            problems.append(f"{where}{k!r} has {len(obj[k])} items, need exactly {n}")
    return problems


def json_only(t, **p):
    """The whole answer is one JSON value (one wrapping code fence is tolerated, any other text is not)."""
    m = _FENCE_WRAP.match(t)
    try:
        value = json.loads((m.group(1) if m else t).strip())
    except ValueError:
        return "the answer is not valid JSON on its own"
    if p.get("shape") == "array":
        if not isinstance(value, list):
            return "top level is not an array"
        if len(value) != p["length"]:
            return f"{len(value)} items, need exactly {p['length']}"
        bad = [pr for i, item in enumerate(value) for pr in
               (_shape_problems(item, p["items"], p.get("exact_keys", True), {}, {}, f"item {i}: ")
                if isinstance(item, dict) else [f"item {i} is not an object"])]
        return "" if not bad else "; ".join(bad[:3])
    if not isinstance(value, dict):
        return "top level is not an object"
    bad = _shape_problems(value, p["keys"], p.get("exact_keys", True), p.get("min_items", {}), p.get("exact_items", {}))
    return "" if not bad else "; ".join(bad[:3])


# Stop-word sets of words that belong to one language only (shared ones such as "la", "de", "en" are left out).
_STOP = {
    "es": {"el", "los", "las", "y", "es", "por", "con", "para", "del", "como", "pero", "muy", "está", "una", "su", "se", "al", "más"},
    "fr": {"le", "les", "des", "du", "et", "est", "dans", "pour", "pas", "sur", "avec", "qui", "une", "sont", "très", "aux", "ce", "il"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "ein", "eine", "zu", "mit", "den", "von", "auf", "für", "dem", "sich", "auch", "im", "sind", "wie"},
    "en": {"the", "and", "is", "are", "of", "to", "in", "that", "it", "for", "with", "as", "on", "this", "be", "by", "an", "at", "from", "or"},
}


def language(t, **p):
    lang = p["lang"]
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return "no letters"
    if lang == "ru":
        share = sum("а" <= c.lower() <= "я" or c.lower() == "ё" for c in letters) / len(letters)
        return "" if share >= 0.9 else f"only {share:.0%} Cyrillic letters"
    ws = [w.lower() for w in words(t)]
    if len(ws) < 8:
        return "too short to tell the language"
    score = {k: sum(w in s for w in ws) / len(ws) for k, s in _STOP.items()}
    target = score[lang]
    rivals = max(v for k, v in score.items() if k != lang)
    return "" if target >= 0.1 and target >= 2 * rivals else f"does not read as {lang} (stop-word shares {score})"


CHECKS = {f.__name__.rstrip("_"): f for f in (
    word_count, sentence_count, paragraph_count, line_count, contains_all, forbidden_words, keyword_count, letter_count,
    char_count, starts_with, ends_with, all_lowercase, all_uppercase, no_char, capital_words, digit_count,
    max_word_length, no_repeat_words, sentence_max_words, distinct_sentence_starts, nth_word, quote_wrap, line_end,
    acrostic, title_brackets, placeholders, postscript, bold_count, bullets, bullet_max_words, alphabetical_bullets,
    numbered_list, sections, paragraph_sep, repeat_prompt, markdown_table, json_only, language)}
CHECKS["csv"] = csv_only


_REQUIRED = {"paragraph_count": ("n",), "contains_all": ("words",), "forbidden_words": ("words",),
             "keyword_count": ("word",), "letter_count": ("letter",), "char_count": ("char",), "starts_with": ("text",),
             "ends_with": ("text",), "no_char": ("chars",), "max_word_length": ("n",), "sentence_max_words": ("n",),
             "nth_word": ("n", "word"), "line_end": ("char",), "acrostic": ("word",), "postscript": ("marker",),
             "bullets": ("n", "marker"), "bullet_max_words": ("n",), "numbered_list": ("n",), "sections": ("n", "label"),
             "paragraph_sep": ("n",), "repeat_prompt": ("text",), "markdown_table": ("cols", "rows"),
             "csv": ("header", "rows"), "language": ("lang",)}
_RANGED = {"word_count", "sentence_count", "line_count", "keyword_count", "letter_count", "char_count", "capital_words",
           "digit_count", "placeholders", "bold_count"}


def validate_constraints(constraints: list[dict]) -> list[str]:
    """Problems with a task's constraint list (unknown type, missing parameter)."""
    problems = []
    for index, c in enumerate(constraints):
        kind = c.get("type")
        if kind not in CHECKS:
            problems.append(f"constraint {index}: unknown type {kind!r}")
            continue
        missing = [k for k in _REQUIRED.get(kind, ()) if k not in c]
        if missing:
            problems.append(f"constraint {index} ({kind}): missing {', '.join(missing)}")
        if kind in _RANGED and "min" not in c and "max" not in c:
            problems.append(f"constraint {index} ({kind}): needs min or max")
        if kind == "json_only" and "keys" not in c and not (c.get("shape") == "array" and "length" in c and "items" in c):
            problems.append(f"constraint {index} (json_only): needs keys, or shape=array with length and items")
        if kind == "language" and c.get("lang") not in (*_STOP, "ru"):
            problems.append(f"constraint {index} (language): unsupported language {c.get('lang')!r}")
    return problems


def check_all(text: str, constraints: list[dict]) -> list[tuple[str, str]]:
    """[(check id, reason or '')] in the order of `constraints`; ids repeat as `type#2` when a type repeats."""
    out, seen = [], {}
    for c in constraints:
        kind = c["type"]
        seen[kind] = seen.get(kind, 0) + 1
        reason = CHECKS[kind](text, **{k: v for k, v in c.items() if k != "type"})
        out.append((kind if seen[kind] == 1 else f"{kind}#{seen[kind]}", reason))
    return out
