"""General-question help for STAR's own chat (desktop + Discord): the parts of the Litha router's general helper
(server/mesh/general, litha-smart lane) that were measured to help, rewritten for Star's voice.

- every general question: a short hidden note (answer with the key facts, say only what you are sure of);
- maths word problems: the model writes a tiny `name = expression` program, `calc_run` evaluates it exactly
  (ast + Fractions, never eval), the steps and the final number go into the turn;
- safety-sensitive questions: official safety facts (emergency numbers, crisis line, poison control).

Everything is added to the END of the user turn (same place as the clock and web results), so the system prompt
stays the cached prefix. Pure and dependency-free; server/mesh/general is not importable from star/ (server/ is not a
package and the Discord container ships only star/), so the classifier and calculator are copied here and a parity
test (tests/test_general_mode.py) keeps them in step with the router's copy.
"""
from __future__ import annotations

import ast
import re
from fractions import Fraction

# --- classifier (same regexes as server/mesh/general/classify.py, + Roblox/Studio words count as code) ---------------
SAFETY = re.compile(r"password|stranger|address|photo|pic(ture)?s? of|nude|kill (my ?self|me)|suicid|don.?t want to (be alive|live)|"
                    r"hurt (my ?self|me)|self.?harm|pills?|medicine|swallow|poison|dare[ds]?\b|challenge|bully|bullied|"
                    r"free robux|robux generator|log ?in|account|meet (up|me)|secret|touch(ed)? me|run away|weapon|drug|"
                    r"mean (messages|things)|group chat|cyber|scam", re.I)
WRITING = re.compile(r"\b(help me (write|make|fix|improve)|rewrite|re-write|make (this|my) .{0,30}(clearer|better|shorter|stronger)|"
                     r"thesis|essay|paragraph|persuasive|letter to|summari[sz]e|proofread|run-?on|comma|grammar|sentence|"
                     r"which is (right|correct))\b|\bit'?s\b.{0,40}\bits\b|\bits\b.{0,40}\bit'?s\b", re.I)
NUM = re.compile(r"\d+(?:[.,]\d+)?")
MATH_CUE = re.compile(r"how (many|much|long|far|old)|\b(total|each|per|percent|cost|price|average|twice|half|left|"
                      r"remaining|altogether|sum|difference|ratio|fraction|profit|earns?|times as)\b|%|\$", re.I)
CODE = re.compile(r"```|\b(script|lua|luau|roblox|minecraft|unity|c#|python|function|error|datapack|command block|"
                  r"studio|rojo|blender|code|bug)\b", re.I)


GENERAL_KINDS = ("factual", "writing", "safety", "math")
# Star is also a companion: messages about her, the two of them, the time or the conversation are not general
# questions (they need her status, memory and tools), so they never get the note or the GPU lane.
PERSONAL = re.compile(r"\b(?:are you|were you|have you|did you|will you|would you|do you (?:like|love|feel|remember|"
                      r"think|know|want|miss)|how(?:'s| is| are|'re| r) (?:you|u|it going|night school|your)|"
                      r"what(?:'re| are| r) (?:you|u)|your(?:self)?|you(?:'re| are) (?:doing|working|feeling|up)|star|"
                      r"remember|recall|last time|we (?:talked|said|did)|what time|what day is it|today'?s date|"
                      r"what(?:'s| is) the date|what date is it)\b|^\s*(?:and|but|what about|how about|also)\b", re.I)
# A general question is asked as one ("?", a question word, or explain/define); "tell me a joke" or "I had a rough
# day" is conversation.
QUESTION = re.compile(r"\?\s*$|^\W*(?:what|whats|what's|who|whom|whose|when|where|which|why|how|is|are|was|were|can|"
                      r"could|do|does|did|should|will|would|explain|define|tell me (?:about|how|why|what|when|where|who))\b",
                      re.I)


def kind(q: str) -> str:
    """'chat' | 'safety' | 'code' | 'writing' | 'math' | 'factual' (cheap, no model). The router's classifier plus
    two Star rules: messages about her or the conversation, and anything not asked as a question, are 'chat'."""
    if len(q.split()) < 4 and "?" not in q and not SAFETY.search(q):
        return "chat"
    if SAFETY.search(q):
        return "safety"
    if PERSONAL.search(q):
        return "chat"
    if CODE.search(q):
        return "code"
    if WRITING.search(q):
        return "writing"
    if not QUESTION.search(q.strip()):
        return "chat"
    if len(NUM.findall(q)) >= 2 and MATH_CUE.search(q):
        return "math"
    return "factual"


# --- hidden notes ----------------------------------------------------------------------------------------------------
HEADING = "GENERAL QUESTION (a note from the app, not from him)"
NOTE = ("This is a general-knowledge question, not a Roblox one: answer it directly and accurately with the key facts "
        "(names, numbers, dates) in a few sentences. Say only what you are sure of: if you are not sure of an exact "
        "number, date or name, say so plainly or leave it out; never guess. If the question contains a wrong idea, "
        "correct it first. Never say it is outside what you do.")
SAFETY_CARD = ("Safety facts from official sources you can use: in danger right now -> call 911 (US), 999 (UK) or 112 "
               "(Europe). Thinking about not wanting to live -> call or text 988 (US Suicide & Crisis Lifeline, free, "
               "24/7) or Samaritans 116 123 (UK). Swallowed something or found pills -> do not take them, call Poison "
               "Control 1-800-222-1222 (US) or emergency services. Never share passwords or login codes; anyone "
               "offering free money or items for a login is a scam. Bullying or a stranger asking for personal things "
               "-> do not reply, save proof, block and report.")
CALC_SYS = ("You solve math word problems by writing a tiny calculation program. Reply with ONLY one ```calc code block: "
            "one step per line, written as `name = expression` using numbers, + - * / ( ) and names defined on earlier "
            "lines (no units, no words, no functions). The last line must be `answer = ...`.")


def sections(question: str) -> list[tuple[str, str]]:
    """The synchronous part: (heading, text) pairs for the end of the user turn; [] for chat/code questions and for
    maths (maths gets `calc_section` instead)."""
    k = kind(question)
    if k in ("chat", "code", "math"):
        return []
    text = NOTE + ("\n" + SAFETY_CARD if k == "safety" else "")
    return [(HEADING, text)]


def render(secs: list[tuple[str, str]]) -> str:
    """Sections as plain text for a channel that appends one block (Discord's `live`)."""
    return "\n\n".join(f"{h}:\n{t}" for h, t in secs if t)


# --- the GPU lane: general questions answered by the mesh router's GPU nodes ----------------------------------------
# truth-20261029: STAR's quick model runs on the brain's CPU (4 tok/s, 10-45 s per answer while background work runs;
# 18/38 Discord answers timed out at 75 s on 10-29); the mesh router's GPU nodes answer the same Star prompt in a few
# seconds. Off when no router is configured (STAR_MESH_URL or ~/.star/mesh_url) or `general_gpu` is False; any failure
# before the first word falls back to the normal brain path.
GPU_MODEL = "litha"
# The router's own Litha helpers must stay off for Star: its kid-tutor note, its answer cache (Litha answers) and the
# Roblox grounding/loop; mesh_brain False = GPU nodes only (the brain's litha-26b is slower than her own path).
GPU_EXTRAS = {"mesh_general": False, "mesh_cache": False, "mesh_ground": False, "mesh_loop": False, "mesh_brain": False,
              "chat_template_kwargs": {"enable_thinking": False}}
# The GPU node queues requests on its slot; even a queued node (median 5-10 s, p90 15-23 s on 10-29) beats the brain's
# CPU path (median 38 s, p90 153 s on 10-29), so the lane waits up to 20 s for the first word before falling back.
GPU_FIRST_TOKEN_S = 20.0
GPU_TOTAL_S = 90.0


def gpu_endpoint(settings) -> str:
    """The mesh router's /v1 address for general answers, or '' (off / not configured / not a private address)."""
    if getattr(settings, "general_gpu", True) is not True:
        return ""
    from .providers import provider_kind, validate_lan_endpoint
    from .system_view import mesh_url
    if provider_kind(settings) != "lan":
        return ""
    base = mesh_url()
    if not base:
        return ""
    try:
        return validate_lan_endpoint(base + "/v1", label="Mesh router", allow_cgnat=getattr(settings, "allow_cgnat", False))
    except ValueError:
        return ""


async def gpu_answer(settings, endpoint: str, messages: list[dict], *, max_tokens: int, temperature: float,
                     on_delta=None, first_token_s: float = GPU_FIRST_TOKEN_S, total_s: float = GPU_TOTAL_S) -> str:
    """Stream one answer from the mesh router. Raises (nothing was shown) when no word came within `first_token_s`;
    after the first word, deltas go to `on_delta` and the whole text is returned."""
    import asyncio
    import httpx
    from openai import AsyncOpenAI
    from .providers import connection_for
    _, key = connection_for(settings)          # the same STAR Server key; the router accepts it
    async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(total_s, connect=3.0)) as transport:
        client = AsyncOpenAI(base_url=endpoint, api_key=key, http_client=transport, max_retries=0)
        pieces: list[str] = []
        async with asyncio.timeout(total_s):
            async with asyncio.timeout(first_token_s):
                stream = await client.chat.completions.create(
                    model=GPU_MODEL, messages=messages, max_tokens=max_tokens, temperature=temperature,
                    stream=True, extra_body=GPU_EXTRAS)
                it = stream.__aiter__()
                while True:
                    chunk = await it.__anext__()
                    text = _delta_text(chunk)
                    if text:
                        pieces.append(text)
                        break
            if on_delta is not None:
                await on_delta(pieces[0])
            async for chunk in it:
                text = _delta_text(chunk)
                if text:
                    pieces.append(text)
                    if on_delta is not None:
                        await on_delta(text)
        return "".join(pieces)


def desktop_messages(prompt: str, history, sections: list[tuple[str, str]], now: str) -> list[dict]:
    """The desktop chat's plain-chat request (FAST_RULES, the last turns, the user turn with its context block at
    the end), the same layout star.agent builds for the brain."""
    from .agent import FAST_RULES, volatile_context
    from .context_layout import final_user_text
    prior = [{"role": m["role"], "content": m["content"]} for m in list(history or [])[-6:]
             if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
    user = final_user_text(prompt, volatile_context(sections, now=now))
    return [{"role": "system", "content": FAST_RULES}, *prior, {"role": "user", "content": user}]


def _delta_text(chunk) -> str:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return ""
    text = getattr(getattr(choices[0], "delta", None), "content", None)
    return text if isinstance(text, str) else ""


async def gpu_calc(settings, endpoint: str, question: str, timeout: float = 6.0) -> tuple[str, str] | None:
    """The calculation program from the GPU lane (non-stream, bounded); None on any failure."""
    import asyncio
    import httpx
    from openai import AsyncOpenAI
    from .providers import connection_for
    try:
        _, key = connection_for(settings)
        async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(timeout, connect=3.0)) as transport:
            client = AsyncOpenAI(base_url=endpoint, api_key=key, http_client=transport, max_retries=0)
            async with asyncio.timeout(timeout):
                r = await client.chat.completions.create(model=GPU_MODEL, messages=calc_messages(question),
                                                         max_tokens=400, temperature=0.1, extra_body=GPU_EXTRAS)
        return calc_section(r.choices[0].message.content or "") if r.choices else None
    except Exception:
        return None


def calc_messages(question: str) -> list[dict]:
    """The one short model call that writes the calculation program (max_tokens ~400, temperature 0.1)."""
    return [{"role": "system", "content": CALC_SYS}, {"role": "user", "content": question}]


def calc_section(program_reply: str) -> tuple[str, str] | None:
    """(heading, text) with the exact steps and final number, or None when the program is not valid."""
    m = re.search(r"```(?:calc|python)?\s*\n(.*?)```", program_reply or "", re.S)
    try:
        value, steps = calc_run(m.group(1) if m else (program_reply or ""))
    except CalcError:
        return None
    lines = "\n".join(f"{n} = {e} = {calc_fmt(v)}" for n, e, v in steps)
    return (HEADING, f"Exact calculation from a calculator, already checked:\n{lines}\nFinal answer: {calc_fmt(value)}\n"
                     "Explain the steps briefly and give the final answer. Do not mention the calculator.")


# --- exact calculator (copy of server/mesh/general/calc.py) -----------------------------------------------------------
_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b, ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b}
_FUN = {"min": min, "max": max, "abs": abs,
        "round": lambda x, n=0: Fraction(round(x, int(n))) if n else Fraction(round(x))}
_MAX_LINES, _MAX_ABS = 40, 10 ** 15


class CalcError(Exception):
    pass


def _ev(n: ast.AST, env: dict) -> Fraction:
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        return Fraction(str(n.value))
    if isinstance(n, ast.Name):
        if n.id not in env:
            raise CalcError(f"unknown name {n.id}")
        return env[n.id]
    if isinstance(n, ast.BinOp):
        a, b = _ev(n.left, env), _ev(n.right, env)
        if isinstance(n.op, ast.Pow):
            if b.denominator != 1 or abs(b) > 12:
                raise CalcError("power too big")
            return a ** int(b)
        if type(n.op) not in _OPS:
            raise CalcError("operator not allowed")
        if isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
            raise CalcError("division by zero")
        return _OPS[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        v = _ev(n.operand, env)
        return -v if isinstance(n.op, ast.USub) else v
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUN and not n.keywords \
            and len(n.args) <= 3:
        return Fraction(_FUN[n.func.id](*[_ev(a, env) for a in n.args]))
    raise CalcError(f"not allowed: {type(n).__name__}")


def calc_run(src: str) -> tuple[Fraction, list[tuple[str, str, Fraction]]]:
    src = src.replace("×", "*").replace("÷", "/").replace("^", "**").replace("$", "")
    src = re.sub(r"(?<=\d),(?=\d{3}\b)", "", src)
    lines = [ln.split("#")[0].strip() for ln in src.strip().splitlines()]
    lines = [ln for ln in lines if ln][:_MAX_LINES]
    try:
        tree = ast.parse("\n".join(lines))
    except SyntaxError as e:
        raise CalcError(f"syntax: {e.msg}") from None
    env: dict[str, Fraction] = {}
    steps = []
    for st in tree.body:
        if not (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name)):
            raise CalcError("only `name = expression` lines")
        v = _ev(st.value, env)
        if abs(v) > _MAX_ABS:
            raise CalcError("number too big")
        env[st.targets[0].id] = v
        steps.append((st.targets[0].id, ast.unparse(st.value), v))
    if "answer" not in env:
        raise CalcError("no answer line")
    return env["answer"], steps


def calc_fmt(v: Fraction) -> str:
    if v.denominator == 1:
        return str(v.numerator)
    f = f"{float(v):.4f}".rstrip("0").rstrip(".")
    return f + (f" (= {v.numerator}/{v.denominator})" if v.denominator < 100 else "")
