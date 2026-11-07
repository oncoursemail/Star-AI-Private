"""Exact calculator for word problems. The model writes a tiny program (`name = expression` lines, numbers, + - * / //
% ** and earlier names, min/max/abs/round); it is parsed with `ast` and evaluated with Fractions, never with eval/exec.

    value, steps = run("eggs = 16\\nanswer = eggs - 3 - 4")      # Fraction(9), [("eggs", "16", 16), ...]
"""
from __future__ import annotations

import ast
import re
from fractions import Fraction

OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
       ast.Div: lambda a, b: a / b, ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b}
FUN = {"min": min, "max": max, "abs": abs,
       "round": lambda x, n=0: Fraction(round(x, int(n))) if n else Fraction(round(x))}
MAX_LINES, MAX_ABS = 40, 10 ** 15


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
        if type(n.op) not in OPS:
            raise CalcError("operator not allowed")
        if isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
            raise CalcError("division by zero")
        return OPS[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        v = _ev(n.operand, env)
        return -v if isinstance(n.op, ast.USub) else v
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUN and not n.keywords \
            and len(n.args) <= 3:
        return Fraction(FUN[n.func.id](*[_ev(a, env) for a in n.args]))
    raise CalcError(f"not allowed: {type(n).__name__}")


def run(src: str) -> tuple[Fraction, list[tuple[str, str, Fraction]]]:
    src = src.replace("×", "*").replace("÷", "/").replace("^", "**").replace("$", "")
    src = re.sub(r"(?<=\d),(?=\d{3}\b)", "", src)
    lines = [ln.split("#")[0].strip() for ln in src.strip().splitlines()]
    lines = [ln for ln in lines if ln][:MAX_LINES]
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
        if abs(v) > MAX_ABS:
            raise CalcError("number too big")
        env[st.targets[0].id] = v
        steps.append((st.targets[0].id, ast.unparse(st.value), v))
    if "answer" not in env:
        raise CalcError("no answer line")
    return env["answer"], steps


def fmt(v: Fraction) -> str:
    if v.denominator == 1:
        return str(v.numerator)
    f = f"{float(v):.4f}".rstrip("0").rstrip(".")
    return f + (f" (= {v.numerator}/{v.denominator})" if v.denominator < 100 else "")
