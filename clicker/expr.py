"""Small, safe expressions for variables: math, text and a few handy functions.

    = {count} * 2 + 1                 Set Variable value starting with =
    Total: {= round({price} * 1.05, 2)}   inline, anywhere text is typed

{name} inside an expression is the variable itself (a number when it looks like one, else text), so
text values work too: = upper({name}) + "!". Only the operators and functions below exist; nothing
else in Python can be reached (the expression is parsed, never passed to eval).
"""

import ast
import math
import operator
import random
import re


class ExprError(ValueError):
    pass


def _num(v, fn="this"):
    from .runner import to_number
    n = to_number(v)
    if n is None:
        raise ExprError(f"{fn} needs a number, not \"{v}\"")
    return n


def _text(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else f"{v:.10g}"
    return str(v)


def _round(x, n=0):
    return round(_num(x, "round"), int(_num(n, "round")))


def _mid(s, start, n=None):
    s, i = _text(s), max(0, int(_num(start, "mid")) - 1)
    return s[i:] if n is None else s[i:i + max(0, int(_num(n, "mid")))]


FUNCTIONS = {
    "round": _round,
    "int": lambda x: int(_num(x, "int")),
    "number": lambda x: _num(x, "number"),
    "abs": lambda x: abs(_num(x, "abs")),
    "min": lambda *a: min(_num(x, "min") for x in a),
    "max": lambda *a: max(_num(x, "max") for x in a),
    "sqrt": lambda x: math.sqrt(_num(x, "sqrt")),
    "floor": lambda x: math.floor(_num(x, "floor")),
    "ceil": lambda x: math.ceil(_num(x, "ceil")),
    "random": lambda a, b: random.randint(int(_num(a, "random")), int(_num(b, "random"))),
    "len": lambda s: len(_text(s)),
    "upper": lambda s: _text(s).upper(),
    "lower": lambda s: _text(s).lower(),
    "trim": lambda s: _text(s).strip(),
    "text": _text,
    "replace": lambda s, a, b: _text(s).replace(_text(a), _text(b)),
    "contains": lambda s, part: _text(part).lower() in _text(s).lower(),
    "left": lambda s, n: _text(s)[:max(0, int(_num(n, "left")))],
    "right": lambda s, n: _text(s)[-int(_num(n, "right")):] if int(_num(n, "right")) > 0 else "",
    "mid": _mid,
    "pad": lambda x, n: _text(x).zfill(int(_num(n, "pad"))),
}
HELP = ("round(x, places)  int  abs  min  max  sqrt  floor  ceil  random(a, b)  len  upper  lower  trim  "
        "replace(text, old, new)  contains(text, part)  left(text, n)  right(text, n)  mid(text, start, n)  "
        "pad(number, width)")

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.Gt: operator.gt, ast.GtE: operator.ge}
_VARREF = re.compile(r"\{(\w+)\}")
_PREFIX = "v__"


def _value(raw):
    """A variable's value: a number when it looks like one."""
    from .runner import to_number
    n = to_number(raw)
    return raw if n is None else n


def parse(src):
    """Check an expression's grammar (for the step editor). Returns the tree or raises ExprError."""
    code = _VARREF.sub(lambda m: _PREFIX + m.group(1), str(src).strip())
    if not code:
        raise ExprError("the expression is empty")
    if len(code) > 1000:
        raise ExprError("the expression is too long")
    try:
        tree = ast.parse(code, mode="eval")
    except SyntaxError:
        raise ExprError(f"can't read \"{src}\" (check brackets, quotes and operators)")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
            raise ExprError(f"\"{src}\" uses something expressions can't do (write upper(x), not x.upper())")
        if isinstance(node, ast.Call) and node.func.id not in FUNCTIONS:
            raise ExprError(f"unknown function: {node.func.id}. These exist: {HELP}")
        if not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
                                 ast.Call, ast.Name, ast.Constant, ast.Load, ast.operator, ast.unaryop,
                                 ast.boolop, ast.cmpop)):
            raise ExprError(f"\"{src}\" uses something expressions can't do")
    return tree


def evaluate(src, values):
    """Work out an expression with these variables. Returns a number, text or true/false."""
    tree = parse(src)

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            if isinstance(n.value, (int, float, str, bool)):
                return n.value
            raise ExprError("only numbers and \"text\" can be typed in an expression")
        if isinstance(n, ast.Name):
            name = n.id[len(_PREFIX):] if n.id.startswith(_PREFIX) else n.id
            if name in values:
                return _value(values[name])
            if name in ("true", "false"):
                return name == "true"
            raise ExprError(f"there is no variable called {name}")
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            if isinstance(n.op, ast.Not):
                return not v
            v = _num(v, "-" if isinstance(n.op, ast.USub) else "+")
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add) and (isinstance(a, str) or isinstance(b, str)):
                from .runner import to_number
                if to_number(a) is None or to_number(b) is None:
                    return _text(a) + _text(b)   # "Hello " + {name}: joins text
            if isinstance(n.op, ast.Mult) and isinstance(a, str) and not isinstance(b, str):
                from .runner import to_number
                if to_number(a) is None:
                    raise ExprError(f"can't multiply the text \"{a}\"")
            x, y = _num(a, "math"), _num(b, "math")
            if isinstance(n.op, ast.Pow) and abs(y) > 100:
                raise ExprError("that power is too big")
            try:
                return _BIN[type(n.op)](x, y)
            except ZeroDivisionError:
                raise ExprError("division by zero")
        if isinstance(n, ast.BoolOp):
            vals = [ev(v) for v in n.values]
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        if isinstance(n, ast.Compare):
            from .runner import compare
            left = ev(n.left)
            for op, right in zip(n.ops, n.comparators):
                r = ev(right)
                sym = {ast.Eq: "=", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}
                if type(op) not in sym or not compare(left, sym[type(op)], r):
                    return False
                left = r
            return True
        if isinstance(n, ast.IfExp):
            return ev(n.body) if ev(n.test) else ev(n.orelse)
        if isinstance(n, ast.Call):
            args = [ev(a) for a in n.args]
            try:
                return FUNCTIONS[n.func.id](*args)
            except TypeError:
                raise ExprError(f"{n.func.id}() was given the wrong number of values")
            except (ValueError, OverflowError) as e:
                if isinstance(e, ExprError):
                    raise
                raise ExprError(f"{n.func.id}(): {e}")
        raise ExprError("unsupported expression")
    out = ev(tree)
    if isinstance(out, str) and len(out) > 100_000:
        raise ExprError("the result is too long")
    return out


def as_text(value):
    """How a result is stored in a variable: 3.0 -> "3", 0.1+0.2 -> "0.3", True -> "true"."""
    if isinstance(value, float):
        value = round(value, 10)
    return _text(value)


def inline_spans(text):
    """[(start, end, expression)] for every {= ...} in text (braces inside may nest: {= max({a}, 2)})."""
    out, i = [], 0
    while True:
        j = text.find("{=", i)
        if j < 0:
            return out
        depth, k = 0, j
        while k < len(text):
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if k >= len(text):
            return out  # unclosed: left as typed
        out.append((j, k + 1, text[j + 2:k]))
        i = k + 1


def expand_inline(text, values):
    """Replace every {= expression} in text with its result."""
    spans = inline_spans(text)
    if not spans:
        return text
    parts, last = [], 0
    for a, b, src in spans:
        parts.append(text[last:a])
        parts.append(as_text(evaluate(src, values)))
        last = b
    parts.append(text[last:])
    return "".join(parts)
