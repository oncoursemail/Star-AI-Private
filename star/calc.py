"""Bounded, AST-only arithmetic, conversions and descriptive statistics."""
from __future__ import annotations

import ast
from fractions import Fraction
import math
import operator
import re
import statistics
import time

MAX_LENGTH = 512
MAX_DEPTH = 24
MAX_NODES = 160
MAX_EXPONENT = 100
MAX_FACTORIAL = 1000
MAX_BITS = 8192
MAX_SECONDS = 0.5      # wall-clock budget for one expression

_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FLOAT_FUNCS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "asin": math.asin, "acos": math.acos,
    "atan": math.atan, "atan2": math.atan2, "log": math.log,
    "log10": math.log10, "log2": math.log2, "exp": math.exp,
}
_INT_FUNCS = {
    "factorial": math.factorial, "gcd": math.gcd, "lcm": math.lcm,
    "comb": math.comb, "perm": math.perm,
}
_OTHER_FUNCS = {"abs": abs, "round": round, "floor": math.floor,
                "ceil": math.ceil, "min": min, "max": max, "sum": sum}
_ALLOWED = {**_FLOAT_FUNCS, **_INT_FUNCS, **_OTHER_FUNCS}
_CONSTANTS = {"pi": math.pi, "e": math.e}


def _checked(value):
    if type(value) not in (int, float, bool, Fraction):
        raise ValueError("Unsupported result type")
    if isinstance(value, Fraction):
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_BITS:
            raise ValueError("Result too large")
    elif isinstance(value, int) and value.bit_length() > MAX_BITS:
        raise ValueError("Result too large")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite result")
    return value


def _integer(value):
    if type(value) is not int or abs(value) > MAX_FACTORIAL:
        raise ValueError("Integer argument out of range")
    return value


def _evaluate(node, depth=0, deadline=None):
    if deadline is not None and time.monotonic() > deadline:
        raise ValueError("Calculation took too long")
    if depth > MAX_DEPTH:
        raise ValueError("Expression nesting too deep")
    if isinstance(node, ast.Constant):
        if type(node.value) is int:
            return _checked(node.value)
        if type(node.value) is float:
            return _checked(Fraction(str(node.value)))
        raise ValueError("Only numeric constants are allowed")
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.List) or isinstance(node, ast.Tuple):
        if len(node.elts) > 80:
            raise ValueError("List too long")
        return [_evaluate(item, depth + 1, deadline) for item in node.elts]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _checked(_UNARY[type(node.op)](_evaluate(node.operand, depth + 1, deadline)))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        left = _evaluate(node.left, depth + 1, deadline)
        right = _evaluate(node.right, depth + 1, deadline)
        if isinstance(left, list) or isinstance(right, list):
            raise ValueError("Lists are only permitted as function arguments")
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_EXPONENT or (isinstance(right, Fraction) and right.denominator != 1):
                raise ValueError("Exponent out of range")
            if abs(left) > 1 and right > MAX_BITS:
                raise ValueError("Power too large")
        if isinstance(node.op, ast.Div) and isinstance(left, (Fraction, int)) and isinstance(right, (Fraction, int)):
            return _checked(Fraction(left, right))
        if isinstance(node.op, ast.Pow) and right < 0 and isinstance(left, (Fraction, int)):
            return _checked(Fraction(left) ** int(right))
        return _checked(_OPERATORS[type(node.op)](left, right))
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, depth + 1, deadline)
        for op, comparator in zip(node.ops, node.comparators):
            if type(op) not in _OPERATORS or type(op) not in (
                ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE):
                raise ValueError("Comparison not allowed")
            right = _evaluate(comparator, depth + 1, deadline)
            if not _OPERATORS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED or node.keywords:
            raise ValueError("Function not allowed")
        name = node.func.id
        args = [_evaluate(arg, depth + 1, deadline) for arg in node.args]
        if name in _INT_FUNCS:
            args = [_integer(v) for v in args]
        if name in _FLOAT_FUNCS:
            args = [float(v) for v in args]
        if name == "sum" and (len(args) != 1 or not isinstance(args[0], list)):
            raise ValueError("sum requires a list")
        if name in ("min", "max") and len(args) == 1 and isinstance(args[0], list):
            args = args[0]
        if name == "round" and len(args) > 1:
            args[1] = _integer(args[1])
        if any(isinstance(v, list) for v in args) and name not in ("sum",):
            raise ValueError("Unexpected list")
        result = _ALLOWED[name](*args)
        return _checked(result)
    raise ValueError("Expression operation not allowed")


def evaluate(expression: str):
    """Evaluate an expression without eval, Python object access or imports."""
    if not isinstance(expression, str) or not expression.strip() or len(expression) > MAX_LENGTH:
        raise ValueError("Invalid expression length")
    depth = 0
    for char in expression:
        if char in "([{":
            depth += 1
            if depth > MAX_DEPTH:
                raise ValueError("Expression nesting too deep")
        elif char in ")]}":
            depth -= 1
    try:
        root = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(root)) > MAX_NODES:
            raise ValueError("Expression too complex")
        return _evaluate(root.body, 0, time.monotonic() + MAX_SECONDS)
    except (SyntaxError, TypeError, OverflowError, ZeroDivisionError, RecursionError) as exc:
        raise ValueError("Invalid arithmetic expression") from exc


# Each multiplier converts the unit to the category's base unit.
_UNITS = {
    "length": {"m": 1, "metre": 1, "meter": 1, "km": 1000, "cm": Fraction(1, 100),
               "mm": Fraction(1, 1000), "in": Fraction(254, 10000),
               "ft": Fraction(3048, 10000), "yd": Fraction(9144, 10000),
               "mi": Fraction(1609344, 1000), "stud": Fraction(28, 100),
               "studs": Fraction(28, 100)},
    "mass": {"kg": 1, "g": Fraction(1, 1000), "mg": Fraction(1, 1000000),
             "lb": Fraction(45359237, 100000000), "oz": Fraction(28349523125, 1000000000000)},
    "time": {"s": 1, "sec": 1, "min": 60, "h": 3600, "hr": 3600, "day": 86400, "week": 604800},
    "angle": {"rad": 1, "deg": math.pi / 180, "degree": math.pi / 180},
    "data": {"bit": Fraction(1, 8), "byte": 1, "b": 1, "kb": 1000, "mb": 1000000,
             "gb": 1000000000, "kib": 1024, "mib": 1048576, "gib": 1073741824},
}
_TEMP = {"c", "f", "k", "celsius", "fahrenheit", "kelvin"}


def convert(value, from_unit: str, to_unit: str):
    if type(value) not in (int, float, Fraction) or not math.isfinite(float(value)):
        raise ValueError("Invalid quantity")
    if not isinstance(from_unit, str) or not isinstance(to_unit, str):
        raise ValueError("Invalid units")
    source, target = from_unit.strip().lower(), to_unit.strip().lower()
    if source in _TEMP and target in _TEMP:
        source, target = {"celsius": "c", "fahrenheit": "f", "kelvin": "k"}.get(source, source), {"celsius": "c", "fahrenheit": "f", "kelvin": "k"}.get(target, target)
        celsius = (value - 32) * Fraction(5, 9) if source == "f" else value - Fraction(27315, 100) if source == "k" else value
        kelvin = celsius + Fraction(27315, 100)
        if kelvin < 0:
            raise ValueError("Temperature below absolute zero")
        return _checked(celsius * Fraction(9, 5) + 32 if target == "f" else kelvin if target == "k" else celsius)
    for units in _UNITS.values():
        if source in units and target in units:
            return _checked(Fraction(value) * units[source] / units[target] if
                            not any(isinstance(units[u], float) for u in (source, target))
                            else float(value) * units[source] / units[target])
    raise ValueError("Unknown or incompatible units")


def describe(values: list, operation: str):
    if not isinstance(values, list) or not 1 <= len(values) <= 1000:
        raise ValueError("Statistics require 1-1000 observations")
    if operation not in ("mean", "median", "mode", "stdev", "variance"):
        raise ValueError("Unknown statistic")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("Observations must be finite numbers")
    if operation in ("variance", "stdev") and len(values) < 2:
        raise ValueError("Sample statistics require two observations")
    numbers = [Fraction(str(v)) for v in values]
    return _checked(getattr(statistics, operation)(numbers))


_OP = r"(?:\*\*|[+*/%^]|\s-\s|\s[x×]\s)"
_TRIGGERS = (
    # An explicit request to calculate something that contains a number.
    re.compile(r"\b(?:calculate|compute)\b[^.?!\n]{0,80}\d", re.I),
    # "convert 14 studs to metres"
    re.compile(r"\bconvert\s+-?\d[\d.,]*\s*[a-z]+\s+(?:to|into|in)\s+[a-z]+", re.I),
    # "average of 2, 3 and 7" (not "the average user", not "what do you mean")
    re.compile(r"\b(?:average|mean|median|variance|standard deviation|stdev)\s+of\b[^.?!\n]{0,80}\d", re.I),
    re.compile(r"\bfactorial\s+of\s+\d", re.I),
    # "what is 4 + 8" / "what's 3*7"; a bare date such as 2026-10-12 has no spaces around the minus and never matches.
    re.compile(r"\bwhat(?:'s|\s+is)\s+\(*-?\d[\d.]*\s*" + _OP + r"\s*\(*-?\d", re.I),
    re.compile(r"\bhow\s+many\s+(?:metres|meters|feet|studs|seconds|bytes)\b[^.?!\n]{0,60}\d", re.I),
    # A bare sum such as "9 + 10 / 23123 x 100": a number, an operator, a number. No dates (2026-10-12), no "2-3".
    re.compile(r"\d\s*(?:\*\*|[+*^×])\s*\(*-?\d|\d\s+[/x×-]\s+\(*-?\d"),
)


def numerical_request(text: str) -> bool:
    """Conservative trigger: only a clear request to calculate attaches the tool.

    Version numbers, dates, ranges and ordinary words such as "mean" or "average" do not.
    """
    if not isinstance(text, str):
        return False
    return any(pattern.search(text) for pattern in _TRIGGERS)


TOOL = {"name": "star_calculate",
        "description": "Calculate bounded arithmetic, convert compatible units, or compute statistics exactly where rational. For any sum or conversion, call this instead of working it out in text. If the expression is ambiguous or malformed, ask the owner one short clarifying question instead of guessing.",
        "inputSchema": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "Arithmetic expression"},
            "operation": {"type": "string", "enum": ["evaluate", "convert", "mean", "median", "mode", "stdev", "variance"]},
            "value": {"type": "number"}, "from_unit": {"type": "string"}, "to_unit": {"type": "string"},
            "values": {"type": "array", "items": {"type": "number"}, "maxItems": 1000}},
            "additionalProperties": False}}


def calculate(args: dict) -> dict:
    if not isinstance(args, dict) or set(args) - set(TOOL["inputSchema"]["properties"]):
        raise ValueError("Invalid calculator arguments")
    op = args.get("operation", "evaluate")
    if op == "evaluate":
        if set(args) - {"operation", "expression"} or "expression" not in args:
            raise ValueError("Expression required")
        result = evaluate(args["expression"])
    elif op == "convert":
        if set(args) - {"operation", "value", "from_unit", "to_unit"}:
            raise ValueError("Invalid conversion arguments")
        result = convert(args["value"], args["from_unit"], args["to_unit"])
    else:
        if set(args) != {"operation", "values"}:
            raise ValueError("Values required")
        result = describe(args["values"], op)
    return {"result": str(result) if isinstance(result, Fraction) else result}
