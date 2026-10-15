"""
Source-level optimizer for C / C++.

It rewrites the program the way an optimizing compiler would, but at the source
level so the result can be read, copied and used:

  constant folding           60 * 60 * 24            -> 86400
  constant propagation       x (always 5)            -> 5
  algebraic simplification   x * 1, x + 0, x * 0      -> x, x, 0
  strength reduction         x * 2                    -> x + x
  common subexpressions      a = w * h; b = w * h;   -> b = a
  copy propagation           y = x; use(y)           -> use(x)
  dead stores                x = 10; x = 20;          -> x = 20
  dead code                  unused variables, unreachable code, always-false branches

Every rule only fires when it is provably safe (no side effects, no aliasing,
no reassignment, no shadowing). The caller then compiles and runs the original
and the optimized program and only offers the result if both print the same.
"""

import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

from autofix import split_code, find_functions, masked_lines, parse_params, apply_masked_sub

INT_MIN, INT_MAX = -2 ** 31, 2 ** 31 - 1
BIN_PREC = {"||": 4, "&&": 5, "|": 6, "^": 7, "&": 8, "==": 9, "!=": 9, "<": 10, "<=": 10, ">": 10, ">=": 10,
            "<<": 11, ">>": 11, "+": 12, "-": 12, "*": 13, "/": 13, "%": 13}
INT_TYPES = {"int", "long", "short", "long long", "unsigned", "unsigned int", "long int", "size_t"}
CONST_TYPES = {"int", "bool", "double"}  # types whose constant values are propagated
CAST_TYPES = {"int", "double", "float", "char", "long", "short", "unsigned", "bool", "signed", "size_t"}
STREAMS = {"cout", "cerr", "clog", "std::cout", "std::cerr", "std::clog"}
# Library functions that never modify a plain variable passed to them
PURE_FUNCS = {"printf", "puts", "sqrt", "pow", "abs", "fabs", "max", "min", "to_string", "ceil", "floor", "round",
              "exp", "log", "log10", "sin", "cos", "tan", "strlen", "toupper", "tolower", "isalpha", "isdigit",
              "isspace", "isupper", "islower", "isalnum", "putchar", "hypot", "cbrt", "fmod", "llabs", "labs",
              "std::max", "std::min", "std::abs", "std::sqrt", "std::pow", "std::to_string"}
KIND_NAMES = [("prop", "Constant propagation"), ("fold", "Constant folding"),
              ("algebra", "Algebraic simplification"), ("strength", "Strength reduction"),
              ("branch", "Dead branch removal")]

TYPE_RE = (r"(?:(?:const|constexpr|static|register|volatile)\s+)*(?:(?:unsigned|signed|long|short)\s+)*"
           r"(?:int|long|short|double|float|bool|char|auto|string|std::string|size_t|unsigned|signed)\b")
DECL_START = re.compile(rf"^(\s*)({TYPE_RE})\s*(?=[A-Za-z_&*])")


# ======================================================================= AST
class Node:
    span: Optional[Tuple[int, int]] = None


class Num(Node):
    def __init__(self, value, text=None, span=None):
        self.value, self.span = value, span
        self.is_int = isinstance(value, int)
        self.text = text if text is not None else str(value)


class Lit(Node):  # strings, chars, unfoldable numbers
    def __init__(self, text, span=None):
        self.text, self.span = text, span


class Id(Node):
    def __init__(self, name, span=None):
        self.name, self.span = name, span


class Paren(Node):
    def __init__(self, inner, span=None):
        self.inner, self.span = inner, span


class Unary(Node):
    def __init__(self, op, operand, span=None):
        self.op, self.operand, self.span = op, operand, span


class Postfix(Node):
    def __init__(self, op, operand, span=None):
        self.op, self.operand, self.span = op, operand, span


class Binary(Node):
    def __init__(self, op, left, right, span=None):
        self.op, self.left, self.right, self.span = op, left, right, span


class Ternary(Node):
    def __init__(self, cond, a, b, span=None):
        self.cond, self.a, self.b, self.span = cond, a, b, span


class Call(Node):
    def __init__(self, func, args, span=None):
        self.func, self.args, self.span = func, args, span


class Index(Node):
    def __init__(self, base, index, span=None):
        self.base, self.index, self.span = base, index, span


class Member(Node):
    def __init__(self, base, op, name, span=None):
        self.base, self.op, self.name, self.span = base, op, name, span


class Cast(Node):
    def __init__(self, type_text, operand, span=None):
        self.type_text, self.operand, self.span = type_text, operand, span


# ================================================================== parsing
TOKEN_RE = re.compile(r"""
 (?P<ws>\s+)
|(?P<num>(?:0[xX][0-9a-fA-F]+|\d+\.\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?|\d+(?:[eE][-+]?\d+)?)[uUlLfF]*)
|(?P<str>"(?:[^"\\]|\\.)*")
|(?P<chr>'(?:[^'\\]|\\.)*')
|(?P<id>[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*)
|(?P<op><<=|>>=|->|\+\+|--|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%<>=!~&|^?:.,()\[\]{}])
""", re.X)


class ParseError(Exception):
    pass


def tokenize(text: str) -> List[Tuple[str, str, int, int]]:
    out, pos = [], 0
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m:
            raise ParseError(text[pos])
        if m.lastgroup != "ws":
            out.append((m.lastgroup, m.group(), m.start(), m.end()))
        pos = m.end()
    return out


class Parser:
    def __init__(self, text: str):
        self.toks = tokenize(text)
        self.i = 0

    def peek(self, k=0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else ("eof", "", -1, -1)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, value):
        tok = self.take()
        if tok[1] != value:
            raise ParseError(value)
        return tok

    def parse(self) -> Node:
        node = self.expr(3)
        if self.peek()[0] != "eof":
            raise ParseError("trailing")
        return node

    def expr(self, min_prec: int) -> Node:
        left = self.unary()
        while True:
            kind, value, _, _ = self.peek()
            if kind == "op" and value == "?" and min_prec <= 3:
                self.take()
                a = self.expr(3)
                self.expect(":")
                b = self.expr(3)
                left = Ternary(left, a, b, (left.span[0], b.span[1]))
                continue
            prec = BIN_PREC.get(value) if kind == "op" else None
            if prec is None or prec < min_prec:
                return left
            self.take()
            right = self.expr(prec + 1)
            left = Binary(value, left, right, (left.span[0], right.span[1]))

    def unary(self) -> Node:
        kind, value, start, _ = self.peek()
        if kind == "op" and value in ("-", "+", "!", "~", "++", "--", "*", "&"):
            self.take()
            operand = self.unary()
            return Unary(value, operand, (start, operand.span[1]))
        if kind == "op" and value == "(":
            # (type) cast?
            j, words = 1, []
            while self.peek(j)[0] == "id" or self.peek(j)[1] in ("*", "&"):
                words.append(self.peek(j)[1])
                j += 1
            if words and self.peek(j)[1] == ")" and words[0] in CAST_TYPES | {"const", "unsigned", "long"}:
                self.i += j + 1
                operand = self.unary()
                return Cast(" ".join(words).replace(" *", "*"), operand, (start, operand.span[1]))
        if kind == "id" and value == "sizeof":
            raise ParseError("sizeof")
        return self.postfix(self.primary())

    def primary(self) -> Node:
        kind, value, start, end = self.take()
        if kind == "num":
            if re.fullmatch(r"\d+", value) and not (len(value) > 1 and value.startswith("0")):
                v = int(value)
                return Num(v, value, (start, end)) if v <= INT_MAX else Lit(value, (start, end))
            if re.fullmatch(r"(\d+\.\d*|\.\d+)([eE][-+]?\d+)?", value):
                return Num(float(value), value, (start, end))
            return Lit(value, (start, end))
        if kind in ("str", "chr"):
            return Lit(value, (start, end))
        if kind == "id":
            return Id(re.sub(r"\s+", "", value), (start, end))
        if kind == "op" and value == "(":
            inner = self.expr(3)
            close = self.expect(")")
            return Paren(inner, (start, close[3]))
        raise ParseError(value or "eof")

    def postfix(self, node: Node) -> Node:
        while True:
            kind, value, _, _ = self.peek()
            if kind != "op":
                return node
            if value == "(":
                self.take()
                args = []
                if self.peek()[1] != ")":
                    while True:
                        args.append(self.expr(3))
                        if self.peek()[1] == ",":
                            self.take()
                            continue
                        break
                close = self.expect(")")
                node = Call(node, args, (node.span[0], close[3]))
            elif value == "[":
                self.take()
                idx = self.expr(3)
                close = self.expect("]")
                node = Index(node, idx, (node.span[0], close[3]))
            elif value in (".", "->"):
                self.take()
                name = self.take()
                if name[0] != "id":
                    raise ParseError("member")
                node = Member(node, value, name[1], (node.span[0], name[3]))
            elif value in ("++", "--"):
                tok = self.take()
                node = Postfix(value, node, (node.span[0], tok[3]))
            else:
                return node


def parse_expr(text: str) -> Optional[Node]:
    # template arguments (static_cast<int>, vector<int>) are not expressions: leave those alone
    if re.search(r"_cast\s*<|<\s*(?:int|double|float|char|long|bool|string|unsigned|auto)\b\s*[*&]?\s*>", text):
        return None
    try:
        return Parser(text).parse()
    except (ParseError, IndexError, TypeError):
        return None


# ================================================================ rendering
def prec(n: Node) -> int:
    if isinstance(n, Binary):
        return BIN_PREC[n.op]
    if isinstance(n, Ternary):
        return 3
    if isinstance(n, (Unary, Cast)):
        return 14
    if isinstance(n, Num) and n.is_int and n.value < 0:
        return 14
    if isinstance(n, (Postfix, Call, Index, Member)):
        return 15
    return 16


def render(n: Node, src: str) -> str:
    if n.span is not None:
        return src[n.span[0]:n.span[1]]

    def wrap(child: Node, need: int) -> str:
        text = render(child, src)
        return f"({text})" if prec(child) < need else text

    if isinstance(n, Num):
        return n.text
    if isinstance(n, Lit):
        return n.text
    if isinstance(n, Id):
        return n.name
    if isinstance(n, Paren):
        return "(" + render(n.inner, src) + ")"
    if isinstance(n, Unary):
        inner = wrap(n.operand, 14)
        if n.op in ("-", "+") and inner.startswith(n.op):
            inner = f"({inner})"
        return n.op + inner
    if isinstance(n, Postfix):
        return wrap(n.operand, 15) + n.op
    if isinstance(n, Binary):
        p = BIN_PREC[n.op]
        return f"{wrap(n.left, p)} {n.op} {wrap(n.right, p + 1)}"
    if isinstance(n, Ternary):
        return f"{wrap(n.cond, 4)} ? {render(n.a, src)} : {wrap(n.b, 3)}"
    if isinstance(n, Call):
        return wrap(n.func, 15) + "(" + ", ".join(render(a, src) for a in n.args) + ")"
    if isinstance(n, Index):
        return wrap(n.base, 15) + "[" + render(n.index, src) + "]"
    if isinstance(n, Member):
        return wrap(n.base, 15) + n.op + n.name
    if isinstance(n, Cast):
        return f"({n.type_text})" + wrap(n.operand, 14)
    raise TypeError(n)


def clone_value(n: Node) -> Node:
    if isinstance(n, Num):
        return Num(n.value, n.text)
    if isinstance(n, Id):
        return Id(n.name)
    return Lit(n.text)


def int_value(n: Node) -> Optional[int]:
    if isinstance(n, Num) and n.is_int:
        return n.value
    if isinstance(n, Paren):
        return int_value(n.inner)
    if isinstance(n, Unary) and n.op in ("-", "+"):
        v = int_value(n.operand)
        if v is not None:
            return -v if n.op == "-" else v
    return None


def truth_value(n: Node) -> Optional[bool]:
    v = int_value(n)
    if v is not None:
        return bool(v)
    if isinstance(n, Id) and n.name in ("true", "false"):
        return n.name == "true"
    if isinstance(n, Paren):
        return truth_value(n.inner)
    return None


def is_pure(n: Node) -> bool:
    if isinstance(n, (Num, Lit, Id)):
        return True
    if isinstance(n, Paren):
        return is_pure(n.inner)
    if isinstance(n, Unary):
        return n.op not in ("++", "--", "&") and is_pure(n.operand)
    if isinstance(n, Binary):
        return is_pure(n.left) and is_pure(n.right)
    if isinstance(n, Ternary):
        return is_pure(n.cond) and is_pure(n.a) and is_pure(n.b)
    if isinstance(n, Index):
        return is_pure(n.base) and is_pure(n.index)
    if isinstance(n, Member):
        return is_pure(n.base)
    if isinstance(n, Cast):
        return is_pure(n.operand)
    return False  # calls, ++/--


def identifiers(n: Node) -> List[str]:
    out = []

    def walk(x):
        if isinstance(x, Id):
            out.append(x.name)
        for attr in ("inner", "operand", "left", "right", "cond", "a", "b", "base", "index"):
            child = getattr(x, attr, None)
            if isinstance(child, Node):
                walk(child)
        if isinstance(x, Call):
            walk(x.func)
            for arg in x.args:
                walk(arg)
    walk(n)
    return out


def c_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def fold_int(op: str, a: int, b: int) -> Optional[int]:
    if op == "+":
        r = a + b
    elif op == "-":
        r = a - b
    elif op == "*":
        r = a * b
    elif op == "/":
        if b == 0:
            return None
        r = c_div(a, b)
    elif op == "%":
        if b == 0:
            return None
        r = a - b * c_div(a, b)
    elif op == "<<":
        if a < 0 or not 0 <= b < 31:
            return None
        r = a << b
    elif op == ">>":
        if a < 0 or not 0 <= b < 32:
            return None
        r = a >> b
    elif op in ("<", "<=", ">", ">=", "==", "!="):
        r = int({"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "==": a == b, "!=": a != b}[op])
    elif op == "&&":
        r = int(bool(a) and bool(b))
    elif op == "||":
        r = int(bool(a) or bool(b))
    elif op == "&":
        r = a & b
    elif op == "|":
        r = a | b
    elif op == "^":
        r = a ^ b
    else:
        return None
    return r if INT_MIN <= r <= INT_MAX else None


# ======================================================= expression rewrite
class ExprCtx:
    def __init__(self, consts: Dict[str, Node], types: Dict[str, str], propagate: bool, aggressive: bool):
        self.consts, self.types = consts, types
        self.propagate, self.aggressive = propagate, aggressive
        self.kinds = set()
        self.props: List[Tuple[str, str]] = []

    def type_of(self, n: Node) -> Optional[str]:
        if isinstance(n, Num):
            return "int" if n.is_int else "double"
        if isinstance(n, Id):
            return self.types.get(n.name)
        if isinstance(n, Paren):
            return self.type_of(n.inner)
        if isinstance(n, Unary) and n.op in ("-", "+"):
            return self.type_of(n.operand)
        if isinstance(n, Binary) and n.op in ("+", "-", "*", "/", "%"):
            lt, rt = self.type_of(n.left), self.type_of(n.right)
            return "int" if lt == "int" and rt == "int" else None
        return None

    def is_int(self, n: Node) -> bool:
        return self.type_of(n) in INT_TYPES


def rewrite(n: Node, ctx: ExprCtx) -> Node:
    """Bottom-up rewrite. Returns the same object when nothing changed."""
    if isinstance(n, Id):
        if ctx.propagate and n.name in ctx.consts:
            value = ctx.consts[n.name]
            ctx.kinds.add("prop")
            ctx.props.append((n.name, render(value, "")))
            return clone_value(value)
        return n
    if isinstance(n, (Num, Lit)):
        return n
    if isinstance(n, Paren):
        inner = rewrite(n.inner, ctx)
        if inner is n.inner:
            return n
        return inner if prec(inner) >= 15 or isinstance(inner, (Num, Lit, Id)) and not (
            isinstance(inner, Num) and inner.is_int and inner.value < 0) else Paren(inner)
    if isinstance(n, Unary):
        if n.op in ("++", "--", "&"):
            return n  # lvalue use: never substitute
        operand = rewrite(n.operand, ctx)
        v = int_value(operand)
        if v is not None and operand is not n.operand:
            r = {"-": -v, "+": v, "!": int(not v), "~": ~v}[n.op]
            if INT_MIN <= r <= INT_MAX:
                ctx.kinds.add("fold")
                return Num(r)
        return n if operand is n.operand else Unary(n.op, operand)
    if isinstance(n, Postfix):
        return n
    if isinstance(n, Binary):
        left, right = rewrite(n.left, ctx), rewrite(n.right, ctx)
        lv, rv, op = int_value(left), int_value(right), n.op
        # algebraic identities
        if op == "*":
            if rv == 1 and ctx.is_int(left):
                ctx.kinds.add("algebra")
                return left
            if lv == 1 and ctx.is_int(right):
                ctx.kinds.add("algebra")
                return right
            if (rv == 0 and is_pure(left) and ctx.type_of(left) == "int") or \
                    (lv == 0 and is_pure(right) and ctx.type_of(right) == "int"):
                if not (lv is not None and rv is not None):
                    ctx.kinds.add("algebra")
                else:
                    ctx.kinds.add("algebra")
                return Num(0)
        if op == "+":
            if rv == 0 and ctx.is_int(left):
                ctx.kinds.add("algebra")
                return left
            if lv == 0 and ctx.is_int(right):
                ctx.kinds.add("algebra")
                return right
        if op == "-" and rv == 0 and ctx.is_int(left):
            ctx.kinds.add("algebra")
            return left
        if op == "/" and rv == 1 and ctx.is_int(left):
            ctx.kinds.add("algebra")
            return left
        if lv is not None and rv is not None:
            r = fold_int(op, lv, rv)
            if r is not None:
                ctx.kinds.add("fold")
                return Num(r)
        # strength reduction: x * 2 -> x + x
        if op == "*" and ctx.aggressive:
            if rv == 2 and isinstance(left, Id) and ctx.is_int(left):
                ctx.kinds.add("strength")
                return Binary("+", left, Id(left.name))
            if lv == 2 and isinstance(right, Id) and ctx.is_int(right):
                ctx.kinds.add("strength")
                return Binary("+", right, Id(right.name))
        if left is n.left and right is n.right:
            return n
        return Binary(op, left, right)
    if isinstance(n, Ternary):
        cond = rewrite(n.cond, ctx)
        tv = truth_value(cond)
        if tv is not None:
            ctx.kinds.add("branch")
            chosen = rewrite(n.a if tv else n.b, ctx)
            return chosen if prec(chosen) >= 15 or isinstance(chosen, (Num, Lit, Id)) else Paren(chosen)
        a, b = rewrite(n.a, ctx), rewrite(n.b, ctx)
        if cond is n.cond and a is n.a and b is n.b:
            return n
        return Ternary(cond, a, b)
    if isinstance(n, Call):
        args = [rewrite(a, ctx) for a in n.args]
        if all(x is y for x, y in zip(args, n.args)):
            return n
        return Call(n.func, args)
    if isinstance(n, Index):
        index = rewrite(n.index, ctx)
        return n if index is n.index else Index(n.base, index)
    if isinstance(n, Member):
        return n
    if isinstance(n, Cast):
        operand = rewrite(n.operand, ctx)
        v = int_value(operand)
        if v is not None and n.type_text in ("int", "long", "short") and operand is not n.operand:
            ctx.kinds.add("fold")
            return Num(v)
        return n if operand is n.operand else Cast(n.type_text, operand)
    return n


# =========================================================== line helpers
def code_end(masked: str) -> int:
    return len(masked.rstrip())


def top_level_cuts(masked: str, sep: str = ",") -> List[int]:
    cuts, depth = [], 0
    for i, ch in enumerate(masked):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == sep and depth == 0:
            cuts.append(i)
    return cuts


def matching_paren(masked: str, open_idx: int) -> Optional[int]:
    depth = 0
    for i in range(open_idx, len(masked)):
        if masked[i] == "(":
            depth += 1
        elif masked[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return None


def norm_type(t: str) -> str:
    t = re.sub(r"\b(const|constexpr|register|volatile)\b", "", t)
    t = re.sub(r"\s+", " ", t).strip().replace("std::string", "string")
    return t


def parse_decl(masked: str) -> Optional[Dict]:
    """int a = 1, b = a + 2;  ->  type and declarators with initializer spans (columns in the line)."""
    m = DECL_START.match(masked)
    if not m or m.group(2).strip() in ("return",):
        return None
    end = code_end(masked)
    if end == 0 or masked[end - 1] != ";":
        return None
    seg_start, seg_end = m.end(), end - 1
    seg = masked[seg_start:seg_end]
    if ";" in seg:
        return None
    bounds = [-1] + top_level_cuts(seg) + [len(seg)]
    decls, opaque = [], False
    for a, b in zip(bounds, bounds[1:]):
        piece = seg[a + 1:b]
        mm = re.match(r"^\s*([A-Za-z_]\w*)\s*", piece)
        if not mm:
            opaque = True
            name_m = re.search(r"[A-Za-z_]\w*", piece)
            decls.append({"name": name_m.group(0) if name_m else "", "init": None, "start": seg_start + a + 1,
                          "end": seg_start + b, "opaque": True})
            continue
        rest = piece[mm.end():]
        entry = {"name": mm.group(1), "init": None, "start": seg_start + a + 1, "end": seg_start + b,
                 "opaque": False}
        if rest.startswith("="):
            init_start = seg_start + a + 1 + mm.end() + 1
            while init_start < seg_start + b and masked[init_start] == " ":
                init_start += 1
            init_end = seg_start + b
            while init_end > init_start and masked[init_end - 1] == " ":
                init_end -= 1
            entry["init"] = (init_start, init_end)
        elif rest.strip():
            entry["opaque"] = True  # array, constructor call, bit field ...
            opaque = True
        decls.append(entry)
    raw_type = m.group(2)
    return {"indent": m.group(1), "raw_type": raw_type, "type": norm_type(raw_type),
            "static": "static" in raw_type, "decls": decls, "opaque": opaque,
            "type_end": m.end()}


def declared_names(masked: str) -> List[str]:
    """Names declared on a line (loose: also arrays, pointers, references, for-init, range-for)."""
    names = []
    target = masked
    fm = re.match(r"^\s*for\s*\(", masked)
    if fm:
        close = matching_paren(masked, masked.index("(", fm.start()))
        inner = masked[masked.index("(") + 1:close if close else len(masked)]
        target = inner.split(";")[0]
        if ":" in target and ";" not in inner:
            target = target.split(":")[0]
        target = target.strip() + ";"
    m = DECL_START.match(target.strip() and (" " * 0 + target.lstrip()))
    if not m:
        return names
    seg = target.lstrip()[m.end():]
    seg = seg.split(";")[0]
    if "(" in seg.split("=")[0] and "=" not in seg:
        return names  # function prototype
    for a, b in zip([-1] + top_level_cuts(seg), top_level_cuts(seg) + [len(seg)]):
        mm = re.match(r"^\s*[&*\s]*([A-Za-z_]\w*)", seg[a + 1:b])
        if mm:
            names.append(mm.group(1))
    return names


def remove_declarator(line: str, decl: Dict, index: int) -> Optional[str]:
    """Remove one declarator from a declaration line. Returns None if the line becomes empty."""
    entries = decl["decls"]
    if len(entries) == 1:
        return None
    e = entries[index]
    if index == len(entries) - 1:
        prev = entries[index - 1]
        return line[:prev["end"]] + line[e["end"]:]
    nxt = entries[index + 1]
    start = e["start"]
    return line[:start] + line[nxt["start"]:].lstrip() if line[start - 1:start] == " " else \
        line[:start] + " " + line[nxt["start"]:].lstrip()


def word_regex(name: str) -> str:
    return rf"(?<![\w.])(?<!->)(?<!::){re.escape(name)}\b"


# ========================================================== function model
class Func:
    """Analysis of one function body inside the current text."""

    def __init__(self, lines: List[str], f: Dict, all_funcs: List[Dict], globals_: set, macros: set):
        self.lines, self.f = lines, f
        self.header, self.open, self.end = f["header"], f["open"], f["end"]
        self.body = range(self.open + 1, self.end) if self.end > self.open else range(0)
        self.masked = masked_lines(lines)
        self.params = [(norm_type(t.replace("&", "").replace("*", "")), n, t) for t, n in f["params"] if n]
        self.globals, self.macros = globals_, macros
        self.user_funcs = {g["name"]: g for g in all_funcs}
        self.ret = norm_type(f["ret"])
        self.depth: Dict[int, int] = {}
        d = 1
        for k in self.body:
            self.depth[k] = d
            m = self.masked[k]
            d += m.count("{") - m.count("}")
        self.decls: Dict[int, Dict] = {}
        self.count = Counter(n for _, n, _ in self.params)
        for k in self.body:
            parsed = parse_decl(self.masked[k])
            if parsed:
                self.decls[k] = parsed
            for name in declared_names(self.masked[k]):
                self.count[name] += 1
        self.types: Dict[str, str] = {}
        for k in self.body:
            fm = re.match(rf"^\s*for\s*\(\s*({TYPE_RE})\s+([A-Za-z_]\w*)\s*=", self.masked[k])
            if fm and self.count[fm.group(2)] == 1:
                self.types[fm.group(2)] = norm_type(fm.group(1))
        for t, n, raw in self.params:
            if "[" not in raw and "*" not in raw:
                self.types[n] = t
        for k, d_ in self.decls.items():
            for e in d_["decls"]:
                if not e["opaque"] and self.count[e["name"]] == 1:
                    self.types[e["name"]] = d_["type"]
        self.assigned = self.find_assigned()
        text = "\n".join(self.masked[k] for k in range(self.header, self.end + 1))
        self.bail = bool(re.search(r"\bgoto\b|\basm\b|\[\s*&|\[\s*=", text)) or \
            any(re.search(rf"\b{re.escape(mac)}\b", text) for mac in macros)

    def safe_name(self, name: str) -> bool:
        return self.count[name] == 1 and name not in self.globals

    def find_assigned(self) -> set:
        out = set()
        for k in range(self.header, self.end + 1):
            m = self.masked[k]
            segments = [m]
            if k in self.decls:
                d = self.decls[k]
                if d["opaque"] and "&" in m:
                    out.update(re.findall(r"[A-Za-z_]\w*", m))
                segments = [m[e["init"][0]:e["init"][1]] for e in d["decls"] if e["init"]]
            for seg in segments:
                for g in re.finditer(r"(?<![\w.>:])([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)*(?:<<|>>|[-+*/%&|^])?=(?!=)",
                                     seg):
                    out.add(g.group(1))
                out.update(re.findall(r"(?:\+\+|--)\s*([A-Za-z_]\w*)", seg))
                out.update(re.findall(r"([A-Za-z_]\w*)\s*(?:\+\+|--)", seg))
                for g in re.finditer(r"&\s*([A-Za-z_]\w*)", seg):
                    before = seg[:g.start()].rstrip()
                    if not before or before[-1] in "(,=!?:{;<>+-*/%|^" or before.endswith("return"):
                        if not before.endswith("&"):
                            out.add(g.group(1))
                if re.search(r"\bcin\b", seg):
                    out.update(re.findall(r">>\s*([A-Za-z_]\w*)", seg))
                for call in re.finditer(r"(?<![\w.>])([A-Za-z_][\w:]*)\s*\(", seg):
                    fname = call.group(1)
                    if fname in ("if", "while", "for", "switch", "return", "sizeof"):
                        continue
                    close = matching_paren(seg, call.end() - 1)
                    if close is None:
                        continue
                    args_text = seg[call.end():close]
                    bounds = [-1] + top_level_cuts(args_text) + [len(args_text)]
                    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
                        arg = args_text[a + 1:b].strip()
                        if not re.fullmatch(r"[A-Za-z_]\w*", arg):
                            continue
                        target = self.user_funcs.get(fname)
                        if target:
                            params = target["params"]
                            if i < len(params) and "&" in params[i][0] and "const" not in params[i][0]:
                                out.add(arg)
                        elif fname not in PURE_FUNCS:
                            out.add(arg)
                # member calls obj.f(x) may take references
                for call in re.finditer(r"[.>]\s*[A-Za-z_]\w*\s*\(([^()]*)\)", seg):
                    out.update(re.findall(r"(?<![\w.])([A-Za-z_]\w*)(?![\w(])", call.group(1)))
        return out

    def same_block(self, a: int, b: int) -> bool:
        """Lines a < b at the same depth with no closing of that block in between."""
        if self.depth.get(a) != self.depth.get(b):
            return False
        return all(self.depth[k] >= self.depth[a] for k in range(a, b + 1)) and \
            not any(self.masked[k].strip().startswith("}") and self.depth[k] == self.depth[a] for k in range(a + 1, b + 1))

    def occurrences(self, name: str) -> List[int]:
        rx = re.compile(word_regex(name))
        return [k for k in range(self.header, self.end + 1) for _ in rx.finditer(self.masked[k])]

    def prev_code_line(self, k: int) -> Optional[int]:
        for j in range(k - 1, self.open, -1):
            if self.masked[j].strip():
                return j
        return None

    def next_code_line(self, k: int) -> Optional[int]:
        for j in range(k + 1, self.end):
            if self.masked[j].strip():
                return j
        return None

    def is_braceless_body(self, k: int) -> bool:
        """Is line k the single-statement body of an if/for/while/else without braces?"""
        p = self.prev_code_line(k)
        if p is None:
            return False
        s = self.masked[p].strip()
        return bool(re.search(r"^(?:\}\s*)?(?:else\s+)?(?:if|for|while)\s*\(.*\)$", s) or re.fullmatch(r"(?:\}\s*)?else|do", s))


# ================================================================ optimizer
class Optimizer:
    def __init__(self, source: str, language: str = "cpp", aggressive: bool = True):
        self.source, self.language, self.aggressive = source, language, aggressive
        self.lines = source.split("\n")
        self.original_lines = list(self.lines)
        self.origin = list(range(1, len(self.lines) + 1))  # original line number of each current line
        self.events: List[str] = []
        self.snippet = False

    # ------------------------------------------------------------ plumbing
    def note(self, k: int, message: str):
        line = self.origin[k] if 0 <= k < len(self.origin) else None
        entry = f"Line {line}: {message}" if line else message
        if entry not in self.events:
            self.events.append(entry)

    def delete(self, ks: List[int]):
        for k in sorted(set(ks), reverse=True):
            del self.lines[k]
            del self.origin[k]

    def functions(self) -> List[Dict]:
        funcs = [f for f in find_functions(self.lines) if f["end"] > f["open"]]
        if not funcs and not any(re.search(r"\bmain\s*\(", l) for l in self.lines):
            # snippet without main(): the whole file is one body
            self.snippet = True
            return [{"name": "main", "ret": "int", "params_text": "", "params": [], "header": -1, "open": -1,
                     "end": len(self.lines)}]
        return funcs

    def model(self, index: int) -> Optional[Func]:
        funcs = self.functions()
        if index >= len(funcs):
            return None
        masked = masked_lines(self.lines)
        inside = set()
        for g in funcs:
            inside.update(range(max(g["header"], 0), g["end"] + 1))
        globals_ = set()
        if not self.snippet:
            for k, m in enumerate(masked):
                if k not in inside:
                    globals_.update(declared_names(m))
        macros = set()
        for line in self.lines:
            mm = re.match(r"\s*#\s*define\s+([A-Za-z_]\w*)", line)
            if mm:
                macros.add(mm.group(1))
        f = dict(funcs[index])
        if self.snippet:
            # pseudo function: header/open are virtual lines before the file
            lines = ["int main() {"] + self.lines + ["}"]
            g = dict(f, header=0, open=0, end=len(lines) - 1)
            model = Func(lines, g, funcs, globals_, macros)
            model.offset = -1
            return model
        model = Func(self.lines, f, funcs, globals_, macros)
        model.offset = 0
        return model

    def for_each_function(self, fn):
        changed = False
        i = 0
        while True:
            model = self.model(i)
            if model is None:
                return changed
            if not model.bail:
                changed |= bool(fn(model))
            i += 1

    def set_line(self, model: Func, k: int, text: str):
        self.lines[k + model.offset] = text

    def kill_lines(self, model: Func, ks: List[int]):
        self.delete([k + model.offset for k in ks])

    def note_m(self, model: Func, k: int, message: str):
        self.note(k + model.offset, message)

    # ----------------------------------------------------- expression pass
    def pass_expressions(self, model: Func, propagate: bool) -> bool:
        consts: Dict[str, Node] = {}
        changed = False
        candidates = {name for name, t in model.types.items()
                      if t in CONST_TYPES and model.safe_name(name) and name not in model.assigned
                      and name not in {n for _, n, _ in model.params}}
        static_names = set()
        for d in model.decls.values():
            if d["static"]:
                static_names.update(e["name"] for e in d["decls"])
        candidates -= static_names
        for k in model.body:
            line = model.lines[k]
            masked = model.masked[k]
            if not masked.strip():
                continue
            units = self.units(model, k, masked)
            if not units:
                continue
            replacements, messages = [], []
            for unit in units:
                start, end = unit["span"]
                text = line[start:end]
                tree = parse_expr(text)
                if tree is None:
                    continue
                ctx = ExprCtx(consts, model.types, propagate, self.aggressive)
                new = rewrite(tree, ctx)
                if new is not tree:
                    new_text = render(new, text)
                    if unit.get("operand_of_stream") and prec(new) < 12:
                        new_text = f"({new_text})"
                    replacements.append((start, end, new_text))
                    messages.append(self.describe(ctx, text.strip(), new_text))
                    final = new
                else:
                    final = tree
                if unit.get("declares") and unit["declares"] in candidates:
                    name = unit["declares"]
                    t = model.types[name]
                    if t == "int" and isinstance(final, Num) and final.is_int:
                        consts[name] = Num(final.value)
                    elif t == "int" and int_value(final) is not None:
                        consts[name] = Num(int_value(final))
                    elif t == "bool" and (truth_value(final) is not None):
                        v = int_value(final)
                        consts[name] = Id("true" if truth_value(final) else "false") if v is None else Num(v)
                    elif t == "double" and isinstance(final, Num):
                        txt = final.text if not final.is_int else f"{final.value}.0"
                        if final.is_int or re.fullmatch(r"\d+\.\d*|\d*\.\d+", txt):
                            consts[name] = Num(float(txt), txt if "." in txt else txt + ".0")
            if replacements:
                for start, end, new_text in sorted(replacements, reverse=True):
                    line = line[:start] + new_text + line[end:]
                self.set_line(model, k, line)
                model.lines[k] = line
                props = [m_[len("Constant propagation: "):] for m_ in messages if m_.startswith("Constant propagation: ")]
                others = [m_ for m_ in messages if not m_.startswith("Constant propagation: ")]
                if props:
                    self.note_m(model, k, "Constant propagation: " + ", ".join(dict.fromkeys(", ".join(props).split(", "))))
                for msg in others:
                    self.note_m(model, k, msg)
                changed = True
        return changed

    @staticmethod
    def describe(ctx: ExprCtx, old: str, new: str) -> str:
        kinds = [label for key, label in KIND_NAMES if key in ctx.kinds]
        if ctx.kinds == {"prop"}:
            seen = []
            for name, value in ctx.props:
                if (name, value) not in seen:
                    seen.append((name, value))
            return "Constant propagation: " + ", ".join(f"{n} → {v}" for n, v in seen)
        label = kinds[0] + "".join(" + " + kd[0].lower() + kd[1:] for kd in kinds[1:])
        return f"{label}: {old} → {new}"

    def units(self, model: Func, k: int, masked: str) -> List[Dict]:
        """Expression parts of a statement line that may be rewritten."""
        end = code_end(masked)
        stmt = masked[:end]
        if not stmt.strip():
            return []
        lead = len(stmt) - len(stmt.lstrip())
        # declarations
        if k in model.decls:
            d = model.decls[k]
            if d["static"]:
                return []
            out = []
            for e in d["decls"]:
                if e["init"] and not e["opaque"]:
                    out.append({"span": e["init"], "declares": e["name"]})
            return out
        # control headers: if / while / switch / for
        cm = re.match(r"^(\s*)(\}\s*)?(else\s+)?(if|while|switch|for)\s*\(", stmt)
        if cm:
            open_idx = cm.end() - 1
            close = matching_paren(stmt, open_idx)
            if close is None:
                return []
            tail = stmt[close + 1:].strip()
            out = []
            if cm.group(4) == "for":
                inner = stmt[open_idx + 1:close]
                cuts = top_level_cuts(inner, ";")
                if len(cuts) == 2 and ":" not in inner:
                    a, b = open_idx + 1 + cuts[0] + 1, open_idx + 1 + cuts[1]
                    if stmt[a:b].strip():
                        out.append({"span": self.trim(stmt, a, b)})
            else:
                out.append({"span": self.trim(stmt, open_idx + 1, close)})
            if tail and tail not in ("{", ";") and cm.group(4) != "for":
                tail_start = close + 1 + (len(stmt[close + 1:]) - len(stmt[close + 1:].lstrip()))
                out.extend(self.statement_units(stmt, tail_start))
            return out
        if re.match(r"^\s*(else|do|case|default|break|continue|goto|delete|throw|using|typedef|struct|class|enum|"
                    r"namespace|template|public|private|protected)\b", stmt) or stmt.strip() in ("{", "}"):
            return []
        if stmt.count(";") != 1 or not stmt.endswith(";"):
            return []
        return self.statement_units(stmt, lead)

    def statement_units(self, stmt: str, start: int) -> List[Dict]:
        body_end = len(stmt.rstrip())
        if not stmt[:body_end].endswith(";"):
            return []
        body_end -= 1
        text = stmt[start:body_end]
        rm = re.match(r"^return\b\s*", text)
        if rm:
            if not text[rm.end():].strip():
                return []
            return [{"span": self.trim(stmt, start + rm.end(), body_end)}]
        am = re.match(r"^([A-Za-z_]\w*)\s*(=|\+=|-=|\*=|/=|%=)(?!=)\s*", text)
        if am:
            return [{"span": self.trim(stmt, start + am.end(), body_end)}]
        # stream chains: rewrite each operand on its own
        tree = parse_expr(text)
        if tree is None:
            return []
        operands = []
        node = tree
        while isinstance(node, Binary) and node.op in ("<<", ">>"):
            operands.append(node.right)
            node = node.left
        if isinstance(node, Id) and node.name in STREAMS | {"cin", "std::cin"} and operands:
            if node.name in ("cin", "std::cin"):
                return []
            return [{"span": (start + o.span[0], start + o.span[1]), "operand_of_stream": True}
                    for o in reversed(operands)]
        if isinstance(tree, (Postfix,)) or (isinstance(tree, Unary) and tree.op in ("++", "--")):
            return []
        return [{"span": self.trim(stmt, start, body_end)}]

    @staticmethod
    def trim(text: str, a: int, b: int) -> Tuple[int, int]:
        while a < b and text[a] == " ":
            a += 1
        while b > a and text[b - 1] == " ":
            b -= 1
        return a, b

    # ------------------------------------------------------ dead branches
    def pass_branches(self, model: Func) -> bool:
        for k in model.body:
            m = model.masked[k]
            hm = re.match(r"^(\s*)(if|while)\s*\(", m)
            if not hm:
                continue
            close = matching_paren(m, hm.end() - 1)
            if close is None:
                continue
            cond_text = model.lines[k][hm.end():close]
            tv = truth_value(parse_expr(cond_text)) if parse_expr(cond_text) is not None else None
            if tv is None:
                continue
            p = model.prev_code_line(k)
            if p is not None and re.search(r"\belse\s*$", model.masked[p].strip()):
                continue
            tail = m[close + 1:].strip()
            kw = hm.group(2)
            if kw == "while":
                if tv or tail != "{":
                    continue
                end = self.block_end(model, k)
                if end is None or model.masked[end].strip() != "}":
                    continue
                self.note_m(model, k, f"Dead code elimination: 'while ({self.original_cond(model, k, cond_text)})' "
                                      f"never runs → removed the loop.")
                self.kill_lines(model, list(range(k, end + 1)))
                return True
            if tail == "{":
                if self.resolve_chain(model, k, cond_text):
                    return True
                continue
            if tail.endswith(";") and tail.count(";") == 1 and not re.search(r"\belse\b", tail):
                nxt = model.next_code_line(k)
                if nxt is not None and re.match(r"^\s*else\b", model.masked[nxt]):
                    em = re.match(r"^(\s*)else\s+(?!if\b)([^{};]+;)\s*$", model.masked[nxt][:code_end(model.masked[nxt])])
                    if not em:
                        continue
                    indent = model.lines[k][:len(model.lines[k]) - len(model.lines[k].lstrip())]
                    shown = self.original_cond(model, k, cond_text)
                    if tv:
                        stmt_start = close + 1 + (len(model.lines[k][close + 1:]) - len(model.lines[k][close + 1:].lstrip()))
                        kept = indent + model.lines[k][stmt_start:]
                    else:
                        kept = indent + model.lines[nxt][em.start(2):]
                    self.note_m(model, k, f"Dead branch removal: 'if ({shown})' is always {'true' if tv else 'false'} → "
                                          f"kept only the {'if' if tv else 'else'} statement.")
                    self.set_line(model, k, kept)
                    self.kill_lines(model, [nxt])
                    return True
                if tv:
                    indent = model.lines[k][:len(model.lines[k]) - len(model.lines[k].lstrip())]
                    stmt_start = close + 1 + (len(model.lines[k][close + 1:]) - len(model.lines[k][close + 1:].lstrip()))
                    self.set_line(model, k, indent + model.lines[k][stmt_start:])
                    self.note_m(model, k, f"Dead branch removal: 'if ({self.original_cond(model, k, cond_text)})' is always true → kept the statement.")
                else:
                    self.note_m(model, k, f"Dead branch removal: 'if ({self.original_cond(model, k, cond_text)})' is always false → removed it.")
                    self.kill_lines(model, [k])
                return True
        return False

    def resolve_chain(self, model: Func, k: int, first_cond: str) -> bool:
        """
        if (A) { .. } else if (B) { .. } else { .. }  with constant conditions:
        keep the one branch that runs, or drop the leading branches that never run.
        """
        branches = []  # (condition text or None for else, header line, closing line)
        cur, cond = k, first_cond
        while True:
            end = self.block_end(model, cur)
            if end is None:
                return False
            branches.append((cond, cur, end))
            closing = model.masked[end].strip()
            if closing == "}":
                nxt = model.next_code_line(end)
                if nxt is None or not re.match(r"^\s*else\b", model.masked[nxt]):
                    break
                header, text = nxt, model.masked[nxt].strip()
            else:
                header, text = end, closing[1:].strip()
            if re.fullmatch(r"else\s*\{", text):
                cond, cur = None, header
                continue
            em = re.match(r"else\s+if\s*\(", text)
            if not em:
                return False
            line = model.lines[header]
            masked = model.masked[header]
            open_idx = masked.index("(", masked.index("if"))
            close = matching_paren(masked, open_idx)
            if close is None or masked[close + 1:].strip() != "{":
                return False
            cond, cur = line[open_idx + 1:close], header
        values = [None if c is None else truth_value(parse_expr(c)) if parse_expr(c) is not None else "?"
                  for c, _, _ in branches]
        values = [True if c is None else v for (c, _, _), v in zip(branches, values)]
        chosen, dropped = None, 0
        for i, v in enumerate(values):
            if v is True:
                chosen = i
                break
            if v is False:
                dropped += 1
                continue
            break  # unknown condition: cannot decide further
        last = branches[-1][2]
        if chosen is None and dropped == len(branches):
            chosen = -1  # every branch is false: the whole chain disappears
        indent = len(model.lines[k]) - len(model.lines[k].lstrip())
        shown = self.original_cond(model, k, first_cond)
        chosen_cond = ""
        if chosen is not None and chosen > 0 and branches[chosen][0] is not None:
            chosen_cond = self.original_cond(model, branches[chosen][1], branches[chosen][0])
        if chosen is not None:
            if chosen >= 0:
                _, header, end = branches[chosen]
                keep = list(range(header + 1, end))
            else:
                keep = []
            kept_names = [n for j in keep for n in declared_names(model.masked[j])]
            if any(model.count[n] > 1 or n in model.globals for n in kept_names):
                return False
            body_indents = [len(model.lines[j]) - len(model.lines[j].lstrip()) for j in keep if model.lines[j].strip()]
            shift = max(0, min(body_indents) - indent) if body_indents else 0
            new_body = [model.lines[j][shift:] if model.lines[j][:shift].strip() == "" else model.lines[j].lstrip()
                        for j in keep]
            first = k + model.offset
            line_no = self.origin[first]
            origins = [self.origin[j + model.offset] for j in keep]
            del self.lines[first:last + model.offset + 1]
            del self.origin[first:last + model.offset + 1]
            self.lines[first:first] = new_body
            self.origin[first:first] = origins
            if chosen < 0:
                what = "no branch of this if can run → removed it"
            elif branches[chosen][0] is None:
                what = "only the else branch can run → kept just that code"
            elif chosen == 0:
                what = "the condition is always true → kept just its body"
            else:
                what = f"only the branch 'else if ({chosen_cond})' can run → kept just that code"
            self.events.append(f"Line {line_no}: Dead branch removal: 'if ({shown})': {what}.")
            return True
        if dropped == 0:
            return False
        # drop leading branches that can never run; the next 'else if' becomes the 'if'
        _, header, _ = branches[dropped]
        text = model.lines[header]
        new_header = model.lines[k][:indent] + re.sub(r"^\s*\}?\s*else\s+", "", text)
        first = k + model.offset
        line_no = self.origin[first]
        new_origin = self.origin[header + model.offset]
        del self.lines[first:header + model.offset + 1]
        del self.origin[first:header + model.offset + 1]
        self.lines.insert(first, new_header)
        self.origin.insert(first, new_origin)
        self.events.append(f"Line {line_no}: Dead branch removal: 'if ({shown})' is always false → "
                           f"removed {'that branch' if dropped == 1 else f'{dropped} branches that can never run'}.")
        return True

    def original_cond(self, model: Func, k: int, fallback: str) -> str:
        """The condition as the user wrote it (before propagation turned it into a constant)."""
        idx = k + model.offset
        if 0 <= idx < len(self.origin):
            line = self.original_lines[self.origin[idx] - 1]
            masked = split_code(line)[0]
            hm = re.search(r"\b(?:if|while)\s*\(", masked)
            if hm:
                close = matching_paren(masked, hm.end() - 1)
                if close:
                    return line[hm.end():close].strip()
        return fallback.strip()

    @staticmethod
    def block_end(model: Func, k: int) -> Optional[int]:
        """Line that closes the block opened on line k (a leading '}' on line k belongs to the block before)."""
        depth = 0
        for j in range(k, model.end):
            text = model.masked[j]
            if j == k:
                text = text[text.find("{"):] if "{" in text else ""
            for ch in text:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return j
        return None

    # ----------------------------------------- common subexpressions & copies
    def pass_cse(self, model: Func) -> bool:
        seen: Dict[Tuple[str, str], Tuple[str, int]] = {}
        for k in model.body:
            d = model.decls.get(k)
            if not d or d["static"] or d["opaque"] or len(d["decls"]) != 1:
                continue
            e = d["decls"][0]
            if not e["init"]:
                continue
            name = e["name"]
            text = model.lines[k][e["init"][0]:e["init"][1]]
            tree = parse_expr(text)
            if tree is None or not isinstance(tree, (Binary, Paren)) or not is_pure(tree):
                continue
            ids = identifiers(tree)
            if any(i in model.assigned or not (i in model.types) or not (model.safe_name(i) or
                   i in {n for _, n, _ in model.params}) for i in ids):
                continue
            key = (d["type"], re.sub(r"\s+", "", text))
            if key in seen:
                first_name, first_k = seen[key]
                if first_name not in model.assigned and model.safe_name(first_name) and \
                        (model.depth[first_k] == 1 or model.same_block(first_k, k)):
                    line = model.lines[k]
                    self.set_line(model, k, line[:e["init"][0]] + first_name + line[e["init"][1]:])
                    self.note_m(model, k, f"Common subexpression elimination: '{text.strip()}' was already computed "
                                          f"into '{first_name}' (line {self.origin[first_k + model.offset]}) → reuse '{first_name}'.")
                    return True
            elif name not in model.assigned and model.safe_name(name):
                seen[key] = (name, k)
        return False

    def pass_copies(self, model: Func) -> bool:
        params = {n for _, n, _ in model.params}
        for k in model.body:
            d = model.decls.get(k)
            if not d or d["static"] or d["opaque"]:
                continue
            for idx, e in enumerate(d["decls"]):
                if not e["init"]:
                    continue
                src = model.lines[k][e["init"][0]:e["init"][1]].strip()
                y = e["name"]
                if not re.fullmatch(r"[A-Za-z_]\w*", src) or src == y:
                    continue
                x = src
                if y in model.assigned or x in model.assigned or not model.safe_name(y):
                    continue
                if model.types.get(y) is None or model.types.get(y) != model.types.get(x):
                    continue
                if x in params:
                    ok = True
                else:
                    if not model.safe_name(x):
                        continue
                    xk = next((j for j, dd in model.decls.items() if any(ee["name"] == x for ee in dd["decls"])), None)
                    ok = xk is not None and xk < k and (model.depth[xk] == 1 or model.same_block(xk, k))
                if not ok:
                    continue
                rx = word_regex(y)
                for j in range(k + 1, model.end):
                    if re.search(rx, model.masked[j]):
                        self.set_line(model, j, apply_masked_sub(model.lines[j], rx, x))
                        model.lines[j] = self.lines[j + model.offset]
                self.note_m(model, k, f"Copy propagation: '{y}' was only a copy of '{x}' → use '{x}' directly and remove '{y}'.")
                new_line = remove_declarator(model.lines[k], d, idx)
                if new_line is None:
                    self.kill_lines(model, [k])
                else:
                    self.set_line(model, k, new_line)
                return True
        return False

    def pass_return_temps(self, model: Func) -> bool:
        """int r = expr; return r;  ->  return expr;"""
        for k in model.body:
            d = model.decls.get(k)
            if not d or d["static"] or d["opaque"] or len(d["decls"]) != 1:
                continue
            e = d["decls"][0]
            if not e["init"] or d["type"] != model.ret:
                continue
            name = e["name"]
            nxt = model.next_code_line(k)
            if nxt is None or not re.fullmatch(rf"\s*return\s+{re.escape(name)}\s*;", model.masked[nxt][:code_end(model.masked[nxt])]):
                continue
            if name in model.assigned or not model.safe_name(name) or len(model.occurrences(name)) != 2:
                continue
            if model.is_braceless_body(k):
                continue
            expr = model.lines[k][e["init"][0]:e["init"][1]].strip()
            ret_line = model.lines[nxt]
            rm = re.search(rf"\breturn\s+{re.escape(name)}\b", ret_line)
            self.note_m(model, k, f"Copy propagation: '{name}' only carried the value to return → return {expr};")
            self.set_line(model, nxt, ret_line[:rm.start()] + "return " + expr + ret_line[rm.end():])
            self.kill_lines(model, [k])
            return True
        return False

    # ------------------------------------------------------------ dead code
    def pass_dead_stores(self, model: Func) -> bool:
        for k in model.body:
            d = model.decls.get(k)
            if not d or d["static"] or d["opaque"] or len(d["decls"]) != 1:
                continue
            e = d["decls"][0]
            name = e["name"]
            if not e["init"] or not model.safe_name(name) or model.is_braceless_body(k):
                continue
            init = parse_expr(model.lines[k][e["init"][0]:e["init"][1]])
            if init is None or not is_pure(init):
                continue
            rx = re.compile(word_regex(name))
            for j in range(k + 1, model.end):
                m = model.masked[j]
                if not m.strip():
                    continue
                sm = re.match(rf"^(\s*){re.escape(name)}\s*=(?!=)\s*(.*?)\s*;\s*$", m)
                if sm and model.same_block(k, j) and not rx.search(m[sm.end(1) + len(name):]) and \
                        not model.is_braceless_body(j):
                    value = model.lines[j][sm.start(2):sm.end(2)]
                    old_value = model.lines[k][e["init"][0]:e["init"][1]].strip()
                    store_line = self.origin[j + model.offset]
                    line = model.lines[j]
                    self.set_line(model, j, line[:sm.start(1) + len(sm.group(1))] + d["raw_type"] + " " +
                                  line[sm.start(1) + len(sm.group(1)):])
                    self.note_m(model, k, f"Dead store elimination: the value {old_value} given to '{name}' is "
                                          f"overwritten on line {store_line} before it is read → "
                                          f"declare it there as {name} = {value}.")
                    self.kill_lines(model, [k])
                    return True
                if rx.search(m) or model.depth.get(j, 0) != model.depth[k] or "{" in m or "}" in m:
                    break
        return False

    def pass_unused(self, model: Func) -> bool:
        removed, kill, edits = [], [], {}
        params = {n for _, n, _ in model.params}
        for k in sorted(model.decls):
            d = model.decls[k]
            if d["opaque"] or model.is_braceless_body(k):
                continue
            for idx, e in reversed(list(enumerate(d["decls"]))):
                name = e["name"]
                if not model.safe_name(name) or name in params:
                    continue
                if e["init"]:
                    tree = parse_expr(model.lines[k][e["init"][0]:e["init"][1]])
                    if tree is None or not is_pure(tree):
                        continue
                occ = model.occurrences(name)
                stores = []
                for j in set(occ):
                    if j == k:
                        continue
                    m = model.masked[j][:code_end(model.masked[j])]
                    sm = re.fullmatch(rf"\s*(?:{re.escape(name)}\s*(?:[-+*/%]?=)(?!=)\s*(.*)|"
                                      rf"(?:\+\+|--){re.escape(name)}|{re.escape(name)}(?:\+\+|--))\s*;", m)
                    if not sm or model.is_braceless_body(j):
                        stores = None
                        break
                    rhs = sm.group(1)
                    if rhs is not None:
                        rtree = parse_expr(model.lines[j][sm.start(1):sm.end(1)])
                        if rtree is None or not is_pure(rtree):
                            stores = None
                            break
                    stores.append(j)
                if stores is None or occ.count(k) != 1:
                    continue
                current = edits.get(k, model.lines[k])
                d_now = parse_decl(masked_lines([current])[0]) if k in edits else d
                if d_now is None:
                    continue
                pos = next((i for i, ee in enumerate(d_now["decls"]) if ee["name"] == name), None)
                if pos is None:
                    continue
                new_line = remove_declarator(current, d_now, pos)
                if new_line is None:
                    kill.append(k)
                    edits.pop(k, None)
                else:
                    edits[k] = new_line
                kill.extend(stores)
                removed.insert(0, (name, self.origin[k + model.offset], len(stores)))
        if not removed:
            return False
        for k, text in edits.items():
            if k not in kill:
                self.set_line(model, k, text)
        self.kill_lines(model, kill)
        parts = []
        for name, line_no, n_stores in sorted(removed, key=lambda r: r[1]):
            extra = f" and {n_stores} assignment(s) to it" if n_stores else ""
            parts.append(f"{name} (line {line_no}){extra}")
        self.events.append("Dead code elimination: removed variables whose values are never used: " + ", ".join(parts) + ".")
        return True

    def pass_unreachable(self, model: Func) -> bool:
        for k in model.body:
            m = model.masked[k]
            code = m[:code_end(m)].strip()
            if not re.match(r"^(return\b.*|break|continue);$", code) or model.is_braceless_body(k):
                continue
            depth = model.depth[k]
            span = []
            for j in range(k + 1, model.end):
                s = model.masked[j].strip()
                if s.startswith("}") and model.depth[j] == depth:
                    break
                if re.match(r"^(case\b|default\s*:|[A-Za-z_]\w*\s*:(?!:))", s) and model.depth[j] == depth:
                    break
                span.append(j)
            code_lines = [j for j in span if model.masked[j].strip()]
            if not code_lines:
                continue
            idx = k + model.offset
            original = split_code(self.original_lines[self.origin[idx] - 1])[0].strip() if 0 <= idx < len(self.origin) else code
            shown = original.rstrip(";") if re.match(r"^(return\b.*|break|continue);$", original) else code.rstrip(";")
            self.note_m(model, k, f"Dead code elimination: removed {len(code_lines)} unreachable line(s) after "
                                  f"'{shown}'.")
            self.kill_lines(model, span)
            return True
        return False

    # -------------------------------------------------------------- driver
    def run(self, max_rounds: int = 12) -> Tuple[str, List[str]]:
        passes = [lambda m: self.pass_expressions(m, propagate=self.aggressive), self.pass_branches,
                  self.pass_unreachable, self.pass_unused]
        if self.aggressive:
            passes[2:2] = [self.pass_cse, self.pass_copies, self.pass_return_temps, self.pass_dead_stores]
        for _ in range(max_rounds):
            before = "\n".join(self.lines)
            for p in passes:
                # each structural pass changes one thing at a time: repeat until it settles
                for _ in range(50):
                    if not self.for_each_function(p):
                        break
            if "\n".join(self.lines) == before:
                break
        self.tidy()
        return "\n".join(self.lines), self.events

    def tidy(self):
        """Remove the blank gaps that deleted lines leave behind (only in functions that changed)."""
        funcs = find_functions(self.lines) if not self.snippet else []
        spans = [(f["open"] + 1, f["end"]) for f in funcs if f["end"] > f["open"]] or \
            ([(0, len(self.lines))] if self.snippet else [])
        drop = []
        for a, b in spans:
            body = list(range(a, b))
            origins = [self.origin[k] for k in body]
            changed = any(self.lines[k] != self.original_lines[self.origin[k] - 1] for k in body) or \
                (origins and origins != list(range(origins[0], origins[0] + len(origins))))
            if not changed:
                continue
            prev_blank = True  # no blank line right after the opening brace
            for k in body:
                blank = not self.lines[k].strip()
                if blank and prev_blank:
                    drop.append(k)
                prev_blank = blank
            for k in reversed(body):  # none right before the closing brace
                if self.lines[k].strip():
                    break
                drop.append(k)
        self.delete(drop)


# ================================================================== metrics
def metrics(code: str) -> Dict[str, int]:
    lines = code.split("\n")
    masked = masked_lines(lines)
    code_lines = sum(1 for m in masked if m.strip() and m.strip() not in ("{", "}"))
    variables = 0
    funcs = find_functions(lines)
    inside = set()
    for f in funcs:
        inside.update(range(f["open"] + 1, f["end"]))
    for k, m in enumerate(masked):
        if (k in inside or not funcs) and parse_decl(m):
            variables += len(parse_decl(m)["decls"])
        elif k in inside and re.match(r"^\s*for\s*\(", m):
            variables += len(declared_names(m))
    ops = 0
    for m in masked:
        stripped = re.sub(r"\+\+|--|<<|>>|->|[+\-*/%]=", " ", m)
        stripped = re.sub(r"#.*", "", stripped)
        ops += len(re.findall(r"(?<![eE])[+\-*/%]", stripped))
    return {"code_lines": code_lines, "variables": variables, "operations": ops}


def optimize(source: str, language: str = "cpp", aggressive: bool = True) -> Tuple[str, List[str]]:
    opt = Optimizer(source, language, aggressive)
    code, events = opt.run()
    return code, [e for e in events if e]
