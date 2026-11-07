"""Blind judge for generated pictures: Star's vision model looks, plain code decides.

Vision models tend to confirm whatever the prompt says, and to explain away a fifth leg. So the first look is
BLIND: the model never sees the prompt, it only lists what is in the picture and counts legs, arms, fingers,
heads and tails, and reads any text. This module then compares those counts with what the species allows. A second
look answers the yes/no checks derived from the prompt. The score only ranks and gates; it is not proof.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .image_prompt import parse_json

BLIND_QUESTION = (
    'Look carefully at this picture. List every animal, person or creature in it. For each one count only what you '
    'can actually see, never guess. Reply with ONE JSON object and nothing else: '
    '{"subjects":[{"kind":"name of the creature","count":1,"visible_legs":0,"visible_arms":0,"heads":0,"tails":0,'
    '"ears":0,"fingers_per_hand":[],"limbs_attach_naturally":true}],"text":["each piece of text you can read, exactly as written"],'
    '"problems":"any merged, extra, missing or melted body parts, or an empty string"}. '
    'Use "fingers_per_hand":[5,5] style lists for visible hands. Use null for a number you cannot see.')

# species class -> {part: (fewest ok, most ok)}. Fewer than the full number can be hidden behind the body; more cannot.
QUADRUPED = {'visible_legs': (2, 4), 'heads': (0, 1), 'tails': (0, 1), 'ears': (0, 2), 'visible_arms': (0, 0)}
HUMAN = {'visible_legs': (0, 2), 'visible_arms': (0, 2), 'heads': (0, 1)}
BIRD = {'visible_legs': (0, 2), 'heads': (0, 1), 'visible_arms': (0, 0)}
_GROUPS = {
    'quadruped': (QUADRUPED, 'cow bull ox calf horse pony foal donkey zebra dog puppy wolf fox cat kitten lion tiger '
                  'sheep lamb goat pig deer elk moose bear rabbit elephant giraffe camel lamb'),
    'human': (HUMAN, 'person man woman boy girl child kid human people player runner rider driver baby adult '
              'astronaut knight soldier character'),
    'bird': (BIRD, 'bird duck chicken hen rooster eagle owl parrot sparrow crow goose swan pigeon penguin'),
    'spider': ({'visible_legs': (6, 8), 'heads': (0, 1)}, 'spider tarantula'),
    'insect': ({'visible_legs': (0, 6), 'heads': (0, 1)}, 'ant bee beetle butterfly fly insect wasp'),
    'fish': ({'visible_legs': (0, 0), 'visible_arms': (0, 0), 'heads': (0, 1)}, 'fish shark salmon goldfish trout'),
}
_KIND = {word: name for name, (_, words) in _GROUPS.items() for word in words.split()}
PART_WORDS = {'visible_legs': 'legs', 'visible_arms': 'arms', 'heads': 'heads', 'tails': 'tails', 'ears': 'ears'}


@dataclass
class Verdict:
    anatomy_ok: bool = True
    issues: list[str] = field(default_factory=list)       # hard problems (the repair prompt uses these)
    soft: list[str] = field(default_factory=list)         # counts a hidden limb could explain
    text_read: list[str] = field(default_factory=list)
    checks_yes: int = 0
    checks_total: int = 0
    blank: bool = False
    judged: bool = True
    score: float = 0.0
    text_ok: bool | None = None      # None: no in-picture text was expected; True/False: every expected string was read exactly

    @property
    def passed(self) -> bool:
        return (self.judged and self.anatomy_ok and not self.blank and self.text_ok is not False
                and (self.checks_total == 0 or self.checks_yes * 3 >= self.checks_total * 2))

    @property
    def clear(self) -> bool:
        """A pass with nothing left to doubt, so the picture may be taken without judging the other drafts: clean anatomy, no
        soft count, exact words when words were expected, and every yes/no check answered yes (with three or more checks one
        "no" is allowed: the checks are the rewriter's and some are matters of taste, such as "is it realistic")"""
        allowed_no = 1 if self.checks_total >= 3 else 0
        return self.passed and not self.soft and self.checks_yes >= self.checks_total - allowed_no

    def brief(self) -> str:
        if not self.judged:
            return 'not judged'
        parts = ['anatomy ok' if self.anatomy_ok else 'anatomy FAIL: ' + '; '.join(self.issues[:2])]
        if self.checks_total:
            parts.append(f'prompt match {self.checks_yes}/{self.checks_total}')
        if self.text_ok is not None:
            parts.append('text read back exactly' if self.text_ok else 'text NOT read back exactly')
        if self.blank:
            parts.append('blank picture')
        return ', '.join(parts)

    def as_note(self) -> dict:
        return {'anatomy_ok': self.anatomy_ok, 'issues': self.issues, 'soft': self.soft, 'text_read': self.text_read,
                'checks_yes': self.checks_yes, 'checks_total': self.checks_total, 'blank': self.blank,
                'judged': self.judged, 'score': round(self.score, 3), 'passed': self.passed,
                'text_ok': self.text_ok, 'clear': self.clear}


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def kind_of(name: str) -> str:
    """The species class of a name the judge gave ('Holstein cows' -> 'quadruped'), or ''.

    Only the last word counts (the head noun): "player ship" is a ship, not a player.
    """
    words = re.findall(r'[a-z]+', str(name).lower())
    if not words:
        return ''
    word = words[-1]
    for form in (word, word[:-1] if word.endswith('s') else word, word[:-2] if word.endswith('es') else word):
        if form in _KIND:
            return _KIND[form]
    return ''


def check_anatomy(subjects) -> tuple[list[str], list[str]]:
    """(hard issues, soft notes) from the blind judge's subject list. All counts are compared here, in code."""
    hard: list[str] = []
    soft: list[str] = []
    for item in subjects if isinstance(subjects, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get('kind') or 'creature')[:30]
        group = kind_of(name)
        if not group:        # aliens, robots, sprites, monsters: no rule says what is normal, so nothing is a hard failure
            if item.get('limbs_attach_naturally') is False:
                soft.append(f'{name}: limbs may not attach naturally')
            continue
        if item.get('limbs_attach_naturally') is False:
            hard.append(f'each {name} needs limbs that attach naturally to the body')
        # counts are totals over `count` individuals ("2 people, 4 legs visible")
        each = max(1, min(_number(item.get('count')) or 1, 12))
        for key, (low, high) in _GROUPS[group][0].items():
            count = _number(item.get(key))
            if count is None:
                continue
            word = PART_WORDS.get(key, key)
            if count > high * each:
                hard.append(f'{name}: exactly {high} {word} each, not {count}' if high else f'{name}: no {word}')
            elif count < low * each:
                (hard if (low * each - count) > 1 else soft).append(f'{name}: {low}-{high} {word}, saw {count}')
        if group == 'human':
            for fingers in item.get('fingers_per_hand') or []:
                count = _number(fingers)
                if count is not None and (count > 5 or count < 3):
                    hard.append(f'{name}: five fingers on each hand, not {count}')
    return hard, soft


def _normal(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def text_matches(expected: list[str], read: list[str]) -> float:
    """Share of expected strings that appear exactly (case and punctuation aside) in what the judge read."""
    if not expected:
        return 1.0
    seen = _normal(' '.join(read))
    return sum(_normal(e) in seen for e in expected) / len(expected)


def exact_text(expected: list[str], read: list[str]) -> bool:
    """True when EVERY expected string was read as a whole (case and punctuation aside): "PIZZA" is not in "PIZZAS"."""
    if not expected:
        return True
    seen = ' ' + _normal(' '.join(read)) + ' '
    return all(' ' + _normal(e) + ' ' in seen for e in expected if _normal(e))


def parse_blind(reply: str) -> tuple[list[str], list[str], list[str]] | None:
    """(hard, soft, text read) from the blind reply, or None when the reply is not usable JSON."""
    data = parse_json(reply)
    if not data or not isinstance(data.get('subjects'), list):
        return None
    hard, soft = check_anatomy(data['subjects'])
    problems = data.get('problems')
    if isinstance(problems, str) and re.search(r'\b(extra|merged|fused|melt|missing|duplicate|deform|extra limb)', problems, re.I):
        soft.append('judge noted: ' + problems[:100])
    text = [str(t)[:80] for t in (data.get('text') or []) if isinstance(t, (str, int))] if isinstance(data.get('text'), list) else []
    return hard, soft, text


def parse_answers(reply: str, count: int) -> int | None:
    """How many of `count` yes/no questions were answered yes. Accepts a JSON list/object or numbered lines."""
    data = parse_json(reply)
    answers = None
    if data:
        raw = data.get('answers')
        answers = raw if isinstance(raw, list) else None
    if answers is None:
        answers = re.findall(r'^\s*\d+[\).:-]?\s*(yes|no)\b', reply or '', re.I | re.M)
    if len(answers) < count:
        return None
    return sum(str(a).strip().lower().startswith('y') or a is True for a in answers[:count])


def is_blank(image_path: Path) -> bool:
    """A flat or near-flat picture (a failed render) needs no vision call."""
    from .pil_safe import Image
    with Image.open(image_path) as picture:
        small = picture.convert('L').resize((32, 32))
        values = list(small.tobytes())
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5 < 4.0


def judge(settings, image_path: Path, checks: tuple[str, ...], *, expected_text: list[str] | None = None,
          ask=None, checks_image: Path | None = None, parallel: bool = False) -> Verdict:
    """Judge one picture. `ask(settings, question, [path], max_tokens=...)` returns an object with `.text`.

    `checks_image` is a smaller copy for the yes/no questions (the vision server reads the picture again for every call, at
    about 25 tokens a second, so a coarse look at the subject and setting is cheaper than a second fine one).
    `parallel=True` asks the yes/no questions at the same time as the blind look (the server answers two requests at once:
    measured 13 s instead of 25 s for the pair); the answers are only used when the blind look passes."""
    if ask is None:
        from .vision import ask as vision_ask
        ask = vision_ask
    verdict = Verdict(blank=is_blank(image_path))
    if verdict.blank:
        verdict.anatomy_ok = False
        verdict.issues.append('the picture is blank')
        return verdict
    numbered = '\n'.join(f'{i}. {q}' for i, q in enumerate(checks, 1))
    check_question = ('Answer each question about this picture with yes or no, from what you see. Reply with '
                      'JSON only: {"answers":["yes","no",...]} in order.\n' + numbered)
    early = None
    if parallel and checks:
        import concurrent.futures
        helper = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        early = helper.submit(lambda: ask(settings, check_question, [checks_image or image_path], max_tokens=120).text)
        helper.shutdown(wait=False)
    blind = parse_blind(ask(settings, BLIND_QUESTION, [image_path], max_tokens=450).text)
    if blind is None:           # one retry: small models sometimes wrap or truncate the JSON
        blind = parse_blind(ask(settings, BLIND_QUESTION, [image_path], max_tokens=450).text)
    if blind is None:
        verdict.judged = False
        return verdict
    hard, soft, read = blind
    verdict.issues, verdict.soft, verdict.text_read = hard, soft, read
    verdict.anatomy_ok = not hard
    if expected_text:
        verdict.text_ok = exact_text(expected_text, read)
        if not verdict.text_ok:
            verdict.issues.append('the words in the picture must read exactly: ' + ' / '.join(expected_text))
    if hard or verdict.text_ok is False:     # cheap first: no match check on a picture that already failed
        verdict.score = 0.05 * max(0, 3 - len(verdict.issues))
        return verdict
    if checks:
        reply = (early.result() if early is not None
                 else ask(settings, check_question, [checks_image or image_path], max_tokens=120).text)
        yes = parse_answers(reply, len(checks))
        if yes is not None:
            verdict.checks_yes, verdict.checks_total = yes, len(checks)
    match = verdict.checks_yes / verdict.checks_total if verdict.checks_total else 1.0
    stray = 0.1 if (expected_text is not None and not expected_text and verdict.text_read) else 0.0
    verdict.score = 0.5 + 0.4 * match - 0.05 * len(soft) - stray
    return verdict


def pick(verdicts: list[Verdict]) -> int:
    """Index of the best picture: passing ones first, then by score."""
    return max(range(len(verdicts)), key=lambda i: (verdicts[i].passed, verdicts[i].score, -i))
