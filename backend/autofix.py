"""
Standards-based auto-fixer for C / C++ source.

Two layers:

1. ``prepass``  - deterministic rules for the mistakes beginners make most
   (cout < instead of <<, missing ';', Cout/retrun typos, void main,
   iostream.h, conio.h/clrscr/getch, smart quotes, unbalanced quotes,
   parentheses and braces ...). Works even when no compiler is installed.

2. ``compiler_loop`` - the real compiler (g++/gcc) is the judge of the ISO
   standard. Compile with -fsyntax-only, take the first error, repair it
   (using the compiler's own fix-it hints when it gives them, otherwise a
   handler matched on the error message), and compile again until the
   program is clean or nothing more can be fixed safely.
"""

import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Dict, List, Optional, Tuple

# ------------------------------------------------- precompiled <iostream>
# Parsing <iostream> is ~90% of every compile. A precompiled copy makes each
# check ~7x faster. It is only used for code that includes <iostream> itself,
# so it can never hide a missing #include.
_PCH = {"header": None, "lock": threading.Lock(), "started": False}
IOSTREAM_LINE = re.compile(r"^\s*#\s*include\s*<\s*iostream\s*>", re.M)
CPP_FLAGS = ["-x", "c++", "-std=c++17", "-O1"]


def _build_pch(compiler: str):
    try:
        folder = tempfile.mkdtemp(prefix="smart_pch_")
        header = os.path.join(folder, "smart_iostream.hpp")
        with open(header, "w") as f:
            f.write("#include <iostream>\n")
        proc = subprocess.run([compiler, "-std=c++17", "-O1", "-x", "c++-header", header, "-o", header + ".gch"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if proc.returncode == 0:
            _PCH["header"] = header
    except (OSError, subprocess.TimeoutExpired):
        pass


def warm_up(compiler: Optional[str]):
    """Build the precompiled header once, in the background."""
    if not compiler:
        return
    with _PCH["lock"]:
        if _PCH["started"]:
            return
        _PCH["started"] = True
    threading.Thread(target=_build_pch, args=(compiler,), daemon=True).start()


def pch_flags(code: str, language: str) -> List[str]:
    if language != "c" and _PCH["header"] and IOSTREAM_LINE.search(code):
        return ["-include", _PCH["header"]]
    return []


# ---------------------------------------------------------------- vocabulary

CPP_KEYWORDS = {
    "int", "float", "double", "char", "bool", "void", "long", "short", "unsigned", "signed",
    "auto", "const", "static", "return", "if", "else", "while", "for", "do", "switch", "case",
    "default", "break", "continue", "struct", "class", "public", "private", "protected",
    "new", "delete", "true", "false", "nullptr", "namespace", "using", "include", "main",
    "sizeof", "typedef", "enum", "template", "typename", "this", "virtual", "goto", "try",
    "catch", "throw", "inline", "extern",
}
STD_NAMES = {
    "cout", "cin", "cerr", "clog", "endl", "string", "getline", "vector", "map", "set",
    "pair", "swap", "sort", "max", "min", "abs", "sqrt", "pow", "printf", "scanf", "puts",
    "gets", "fgets", "strlen", "strcpy", "strcmp", "strcat", "malloc", "free", "exit",
    "to_string", "stoi", "reverse", "find", "begin", "end", "size", "push_back",
}
VOCAB = CPP_KEYWORDS | STD_NAMES

# Spelling mistakes seen constantly in classrooms
MISSPELLINGS = {
    "retrun": "return", "reutrn": "return", "retun": "return", "retur": "return", "returnn": "return",
    "mian": "main", "mainn": "main", "maim": "main", "amin": "main",
    "cuot": "cout", "cot": "cout", "coutt": "cout", "cour": "cout", "cotu": "cout",
    "cni": "cin", "cinn": "cin",
    "pritnf": "printf", "prinf": "printf", "printff": "printf", "pirntf": "printf", "prinft": "printf", "printf_": "printf",
    "scnaf": "scanf", "sacnf": "scanf", "scanff": "scanf",
    "endll": "endl", "edl": "endl", "enld": "endl", "end1": "endl",
    "itn": "int", "nit": "int", "flaot": "float", "dobule": "double", "doubel": "double",
    "chr": "char", "viod": "void", "vodi": "void", "boool": "bool",
    "esle": "else", "whlie": "while", "wihle": "while", "fro": "for",
    "namspace": "namespace", "namesapce": "namespace", "namepace": "namespace", "nmaespace": "namespace",
    "usign": "using", "usng": "using", "uisng": "using",
    "stirng": "string", "strng": "string", "sting": "string",
}
# Words that are only ever written in lower case in C/C++
LOWERCASE_ONLY = {
    "cout", "cin", "cerr", "endl", "printf", "scanf", "return", "int", "main", "void", "char",
    "float", "double", "if", "else", "while", "for", "include", "using", "namespace", "std",
    "break", "continue", "bool", "true", "false", "string", "getline", "puts", "do", "switch",
    "case", "default", "long", "const",
}

KNOWN_HEADERS = [
    "iostream", "cstdio", "stdio.h", "string", "cstring", "string.h", "cmath", "math.h",
    "vector", "algorithm", "map", "set", "iomanip", "fstream", "sstream", "cstdlib",
    "stdlib.h", "climits", "queue", "stack", "deque", "list", "utility", "bits/stdc++.h",
    "ctime", "time.h", "cctype", "ctype.h", "numeric", "array", "unordered_map", "unordered_set",
]
# Turbo-C / pre-standard headers -> standard replacement (None = remove the line)
LEGACY_HEADERS = {
    "iostream.h": "iostream", "fstream.h": "fstream", "iomanip.h": "iomanip",
    "conio.h": None, "dos.h": None, "graphics.h": None, "process.h": None,
}

# ------------------------------------------------------------- line scanning

MASK = "\x07"  # placeholder for characters inside string/char literals (never matches \w)


def split_code(line: str, in_block: bool = False) -> Tuple[str, str, bool, Optional[str]]:
    """
    Split a line into (code, comment) and return a masked copy of code in which
    the contents of string/char literals are replaced by MASK (same length), so
    regexes never match inside literals.
    Returns (masked_code, comment_suffix, still_in_block_comment, open_quote_char).
    open_quote_char is set when a string literal is not terminated on this line.
    """
    masked = []
    i, n = 0, len(line)
    quote = None
    while i < n:
        ch = line[i]
        if in_block:
            if line.startswith("*/", i):
                in_block = False
                masked.append("  ")
                i += 2
            else:
                masked.append(" ")
                i += 1
            continue
        if quote:
            if ch == "\\" and i + 1 < n:
                masked.append(MASK * 2)
                i += 2
                continue
            if ch == quote:
                quote = None
                masked.append(ch)
            else:
                masked.append(MASK)
            i += 1
            continue
        if line.startswith("//", i):
            return "".join(masked), line[i:], False, None
        if line.startswith("/*", i):
            in_block = True
            masked.append("  ")
            i += 2
            continue
        if ch in "\"'":
            quote = ch
        masked.append(ch)
        i += 1
    return "".join(masked), "", in_block, quote


def code_and_comment(line: str) -> Tuple[str, str]:
    masked, comment, _, _ = split_code(line)
    return line[: len(masked)], comment


def apply_masked_sub(line: str, pattern: str, repl, flags=0) -> str:
    """re.sub on the masked line, splicing replacements into the real line."""
    masked, comment, _, _ = split_code(line)
    code = line[: len(masked)]
    out, last = [], 0
    for m in re.finditer(pattern, masked, flags):
        out.append(code[last:m.start()])
        if isinstance(repl, str):
            text = re.sub(r"\\(\d)", lambda g: code[m.start(int(g.group(1))):m.end(int(g.group(1)))]
                          if m.group(int(g.group(1))) is not None else "", repl)
        else:
            text = repl(m)
            if text == m.group(0):
                text = code[m.start():m.end()]
        out.append(text)
        last = m.end()
    out.append(code[last:])
    return "".join(out) + comment


# ------------------------------------------------------------ program model
# A light model of the program: its functions, their parameters and call sites.
# It lets the fixer understand *why* a name is unknown instead of guessing.

CONTROL_WORDS = {"if", "for", "while", "switch", "return", "else", "do", "sizeof", "catch", "new", "delete"}
HEADER_RE = re.compile(
    r"^\s*((?:(?:static|inline|const|unsigned|signed|long|short|struct|virtual)\s+)*[A-Za-z_][\w:<>,]*[\s\*&]+)"
    r"([A-Za-z_]\w*)\s*\((.*)\)\s*(?:const\s*)?(\{.*)?$")
NUMERIC_TYPES = {"int", "long", "short", "unsigned", "float", "double", "char", "size_t", "long long",
                 "unsigned int", "long int", "long double"}
HEADER_FOR = {  # standard name -> header that declares it (C++, C)
    **{n: ("cmath", "math.h") for n in ["sqrt", "pow", "fabs", "ceil", "floor", "round", "sin", "cos", "tan",
                                       "log", "log10", "exp", "hypot", "cbrt", "fmod"]},
    **{n: ("cstring", "string.h") for n in ["strlen", "strcpy", "strcmp", "strcat", "strncpy", "strncmp",
                                           "memset", "memcpy", "strchr", "strstr"]},
    **{n: ("cstdlib", "stdlib.h") for n in ["rand", "srand", "exit", "malloc", "calloc", "free", "atoi",
                                           "atof", "system", "abs"]},
    **{n: ("cctype", "ctype.h") for n in ["isalpha", "isdigit", "isspace", "isupper", "islower", "toupper",
                                         "tolower", "isalnum", "ispunct"]},
    **{n: ("climits", "limits.h") for n in ["INT_MAX", "INT_MIN", "LLONG_MAX", "LLONG_MIN", "UINT_MAX"]},
    **{n: ("iomanip", None) for n in ["setw", "setprecision", "setfill"]},
    **{n: ("algorithm", None) for n in ["sort", "reverse", "max_element", "min_element", "count", "fill",
                                       "next_permutation", "binary_search", "lower_bound", "upper_bound"]},
    **{n: ("ctime", "time.h") for n in ["time", "clock"]},
    "vector": ("vector", None), "map": ("map", None), "set": ("set", None), "queue": ("queue", None),
    "stack": ("stack", None), "pair": ("utility", None), "string": ("string", None),
    "getline": ("string", None), "to_string": ("string", None), "stoi": ("string", None),
    "printf": ("cstdio", "stdio.h"), "scanf": ("cstdio", "stdio.h"), "puts": ("cstdio", "stdio.h"),
    "bool": (None, "stdbool.h"), "true": (None, "stdbool.h"), "false": (None, "stdbool.h"),
}


def masked_lines(lines: List[str]) -> List[str]:
    out, in_block = [], False
    for line in lines:
        masked, _, in_block, _ = split_code(line, in_block)
        out.append(masked)
    return out


def split_top_level(text: str, sep: str = ",") -> List[str]:
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch in "([{<" and ch != "<":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return [p.strip() for p in parts]


def parse_params(params: str) -> List[Tuple[str, str]]:
    params = params.strip()
    if not params or params == "void":
        return []
    out = []
    for p in split_top_level(params):
        p = p.split("=", 1)[0].strip()
        m = re.match(r"^(.*?)([A-Za-z_]\w*)\s*(\[\s*\d*\s*\])?$", p)
        if m and m.group(1).strip():
            out.append((m.group(1).strip() + (" " + m.group(3) if m.group(3) else ""), m.group(2)))
        else:
            out.append((p, ""))
    return out


def find_functions(lines: List[str]) -> List[Dict]:
    """Function definitions at file scope: name, return type, params and line span (0-based)."""
    masked = masked_lines(lines)
    funcs, depth, i = [], 0, 0
    while i < len(lines):
        m_line = masked[i]
        if depth == 0:
            m = HEADER_RE.match(m_line)
            if m and m.group(2) not in CONTROL_WORDS and not m.group(1).strip() in CONTROL_WORDS \
                    and not re.match(r"\s*(return|else|new|delete)\b", m_line):
                nxt = next((k for k in range(i + 1, len(lines)) if masked[k].strip()), None)
                open_idx = i if (m.group(4) or "").startswith("{") else (
                    nxt if nxt is not None and masked[nxt].strip().startswith("{") else None)
                if open_idx is not None:
                    d, end = 0, None
                    for k in range(open_idx, len(lines)):
                        segment = masked[k] if k != i else masked[k][masked[k].find("("):]
                        for ch in segment:
                            if ch == "{":
                                d += 1
                            elif ch == "}":
                                d -= 1
                                if d == 0:
                                    end = k
                                    break
                        if end is not None:
                            break
                    funcs.append({"name": m.group(2), "ret": m.group(1).strip(), "params_text": m.group(3),
                                  "params": parse_params(m.group(3)), "header": i, "open": open_idx,
                                  "end": end if end is not None else len(lines) - 1})
                    i = (end if end is not None else len(lines) - 1) + 1
                    continue
        depth = max(0, depth + m_line.count("{") - m_line.count("}"))
        i += 1
    return funcs


def enclosing_function(funcs: List[Dict], row: int) -> Optional[Dict]:
    for f in funcs:
        if f["header"] <= row <= f["end"]:
            return f
    return None


def find_calls(lines: List[str], name: str, funcs: List[Dict]) -> List[Tuple[int, List[str]]]:
    """Call sites of `name` (not its definition or prototype) with their argument lists."""
    masked = masked_lines(lines)
    headers = {f["header"] for f in funcs if f["name"] == name}
    calls = []
    for row, m_line in enumerate(masked):
        if row in headers:
            continue
        for m in re.finditer(rf"(?<![\w.>:])({re.escape(name)})\s*\(", m_line):
            before = m_line[:m.start()].strip()
            if re.search(r"(?:^|[\s(,])(?:int|void|float|double|char|bool|string|long|auto|unsigned)\s*[\*&]*$", before):
                continue  # a declaration / prototype, not a call
            start = m.end() - 1
            depth, end = 0, None
            for k in range(start, len(m_line)):
                if m_line[k] == "(":
                    depth += 1
                elif m_line[k] == ")":
                    depth -= 1
                    if depth == 0:
                        end = k
                        break
            if end is None:
                continue
            real = lines[row][start + 1:end]
            calls.append((row, split_top_level(real) if real.strip() else []))
    return calls


def infer_type(expr: str, lines: List[str], funcs: List[Dict], language: str = "cpp") -> str:
    e = (expr or "").strip()
    if not e:
        return "int"
    if e.startswith('"'):
        return "string" if language == "cpp" else "const char*"
    if e.startswith("'"):
        return "char"
    if e in ("true", "false"):
        return "bool"
    if re.fullmatch(r"-?\d+\.\d*(?:[eE][-+]?\d+)?[fF]?|-?\d*\.\d+(?:[eE][-+]?\d+)?[fF]?", e):
        return "double"
    if re.fullmatch(r"-?\d+[lLuU]*", e):
        return "int"
    m = re.fullmatch(r"([A-Za-z_]\w*)\s*\(.*\)", e)
    if m:
        for f in funcs:
            if f["name"] == m.group(1) and f["ret"] != "void":
                return f["ret"]
        return "int"
    if re.fullmatch(r"[A-Za-z_]\w*", e):
        pattern = rf"\b((?:unsigned\s+|long\s+|const\s+)*(?:int|long|short|float|double|char|bool|string|std::string|size_t|auto))\s*[\*&]?\s*\b{re.escape(e)}\b"
        for line in lines:
            mm = re.search(pattern, split_code(line)[0])
            if mm:
                t = mm.group(1).replace("const ", "")
                return "int" if t == "auto" else t
        for f in funcs:
            for t, n in f["params"]:
                if n == e:
                    return t.replace("&", "").replace("const ", "").strip()
        return "int"
    if '"' in e and language == "cpp":
        return "string"
    if re.search(r"\d\.\d", e):
        return "double"
    return "int"


def default_value(type_name: str) -> Optional[str]:
    t = type_name.replace("const", "").strip()
    if t in ("string", "std::string"):
        return '""'
    if t == "bool":
        return "false"
    if t in ("float", "double", "long double"):
        return "0.0"
    if t.endswith("*"):
        return "nullptr"
    if any(t.startswith(n) for n in ("int", "long", "short", "unsigned", "char", "size_t", "signed")):
        return "0"
    return None


# ------------------------------------------------------------------ prepass

STATEMENT_END_OPERATORS = ("&&", "||", "<<", ">>", "=", "+", "-", "*", "/", "%", "?", "<", ">",
                           "!", "&", "|", "^", ".", "->", "::", "\\", "[")
CONTINUATION_STARTS = ("<<", ">>", "+", "-", "*", "/", "&&", "||", "?", ":", ".", "->", ",", ")", "=", "{")


class AutoFixer:
    def __init__(self, source: str, language: str = "cpp"):
        self.source = source
        self.language = language
        self.fixes: List[str] = []
        self.compiler = self.find_compiler()
        warm_up(self.compiler)

    # ---------------------------------------------------------- utilities
    def note(self, line_no: int, message: str):
        entry = f"Line {line_no}: {message}" if line_no else message
        if entry not in self.fixes:
            self.fixes.append(entry)

    @staticmethod
    def find_compiler() -> Optional[str]:
        path = shutil.which("g++")
        if path:
            return path
        for candidate in [r"C:\msys64\ucrt64\bin\g++.exe", r"C:\MinGW\bin\g++.exe",
                          r"C:\msys64\mingw64\bin\g++.exe", "/usr/bin/g++"]:
            if os.path.exists(candidate):
                return candidate
        return None

    # ------------------------------------------------------------ prepass
    def prepass(self, code: str) -> str:
        code = self._fix_unicode(code)
        lines = code.split("\n")
        declared = self._declared_names(lines)
        if "main" not in declared:
            declared -= {w for w, t in MISSPELLINGS.items() if t == "main"}
        out: List[str] = []
        in_block = False
        for no, line in enumerate(lines, 1):
            if in_block:
                _, _, in_block, _ = split_code(line, True)
                out.append(line)
                continue
            stripped = line.strip()
            if re.match(r"^\s*include\s*[<\"]", line):
                line = re.sub(r"^(\s*)include", r"\1#include", line)
                stripped = line.strip()
                self.note(no, "Preprocessor directives start with '#': include -> #include.")
            if stripped.startswith("#"):
                fixed = self._fix_directive(line, no)
                if fixed is not None:
                    out.append(fixed)
                continue
            new = self._fix_using(line, no)
            new = self._fix_words(new, no, declared)
            new = self._fix_main_signature(new, no)
            new = self._fix_turbo_c(new, no)
            if new is None:
                continue
            new = self._fix_misc(new, no)
            if self.language == "cpp":
                new = self._fix_stream_operators(new, no)
            new = self._fix_unterminated_string(new, no)
            new = self._fix_parentheses(new, no)
            _, _, in_block, _ = split_code(new)
            out.append(new)
        out = self._fix_stray_semicolons(out)
        out = self._fix_semicolons(out)
        out = self._fix_braces(out)
        return "\n".join(out)

    def _fix_unicode(self, code: str) -> str:
        table = {"\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2033": '"', "\u2018": "'", "\u2019": "'",
                 "\u00a0": " ", "\u2003": " ", "\u2002": " ", "\uff1b": ";", "\u226a": "<<", "\u226b": ">>",
                 "\u2013": "-", "\u2014": "-", "\u2212": "-", "\uff08": "(", "\uff09": ")", "\u200b": "",
                 "\u2264": "<=", "\u2265": ">=", "\u2260": "!="}
        fixed = "".join(table.get(c, c) for c in code)
        if fixed != code:
            self.note(0, "Replaced smart quotes / non-ASCII symbols (copied from a document) with standard characters.")
        return fixed

    @staticmethod
    def _declared_names(lines: List[str]) -> set:
        names = set()
        for line in lines:
            masked, _, _, _ = split_code(line)
            for m in re.finditer(r"\b(?:int|float|double|char|bool|string|long|auto|void|struct|class)\s+\*?\s*([A-Za-z_]\w*)", masked):
                names.add(m.group(1))
        return names

    def _fix_directive(self, line: str, no: int) -> Optional[str]:
        m = re.match(r"^(\s*)#\s*([A-Za-z]+)\s*(.*?)\s*$", line)
        if not m:
            return line
        indent, word, rest = m.groups()
        known = {"if", "ifdef", "ifndef", "endif", "else", "elif", "pragma", "undef", "define", "include", "error", "line"}
        if word.lower() in known:
            word = word.lower()
        else:
            match = difflib.get_close_matches(word.lower(), ["include", "define"], n=1, cutoff=0.7)
            if not match:
                return line
            self.note(no, f"Fixed directive '#{word}' -> '#{match[0]}'.")
            word = match[0]
        if word not in ("include", "define"):
            return line
        if word == "define" and re.search(r";\s*$", rest.split("//")[0]):
            self.note(no, "A #define is not a statement: removed the trailing ';' (it would be pasted into the code).")
            rest = re.sub(r";\s*$", "", rest.split("//")[0]).rstrip()
            return f"{indent}#define {rest}"
        if word != "include":
            return f"{indent}#{word} {rest}".rstrip()
        rest = rest.split("//", 1)[0].strip().rstrip(";").strip()
        name = rest.strip("<>\" ")
        if not name:
            return line
        local = rest.startswith('"') and name not in KNOWN_HEADERS and name not in LEGACY_HEADERS
        if local:
            return f'{indent}#include "{name}"'
        key = name.lower()
        if key in LEGACY_HEADERS:
            repl = LEGACY_HEADERS[key]
            if repl is None:
                self.note(no, f"Removed non-standard header <{name}> (Turbo C only, not part of ISO C/C++).")
                return None
            self.note(no, f"Replaced pre-standard header <{name}> with <{repl}>.")
            return f"{indent}#include <{repl}>"
        if key in {"stdio", "cstdio.h"}:
            repl = "stdio.h" if self.language == "c" else "cstdio"
            self.note(no, f"Fixed header name <{name}> -> <{repl}>.")
            return f"{indent}#include <{repl}>"
        if key not in KNOWN_HEADERS:
            match = difflib.get_close_matches(key, KNOWN_HEADERS, n=1, cutoff=0.75)
            if match:
                self.note(no, f"Fixed misspelled header <{name}> -> <{match[0]}>.")
                key = match[0]
        if not (rest.startswith("<") and rest.endswith(">")) or key != name:
            if not (rest.startswith("<") and rest.endswith(">")):
                self.note(no, f"Header names must be written as #include <{key}>.")
            return f"{indent}#include <{key}>"
        return line

    def _fix_using(self, line: str, no: int) -> str:
        m = re.match(r"^(\s*)(\w+)\s+(\w+)\s+(\w+)\s*;?\s*$", line)
        if m and self.language == "cpp":
            indent, a, b, c = m.groups()
            if (difflib.get_close_matches(a.lower(), ["using"], cutoff=0.6)
                    and difflib.get_close_matches(b.lower(), ["namespace"], cutoff=0.7)
                    and c.lower() in {"std", "sdt", "stdd", "st"}):
                fixed = f"{indent}using namespace std;"
                if fixed != line.rstrip():
                    self.note(no, "Fixed 'using namespace std;'.")
                return fixed
        return line

    def _fix_words(self, line: str, no: int, declared: set) -> str:
        def repl(m):
            word = m.group(0)
            if word in declared:
                return word
            low = word.lower()
            if low in MISSPELLINGS and word not in VOCAB:
                self.note(no, f"Fixed misspelling '{word}' -> '{MISSPELLINGS[low]}'.")
                return MISSPELLINGS[low]
            if word != low and low in LOWERCASE_ONLY:
                self.note(no, f"C/C++ is case-sensitive: '{word}' -> '{low}'.")
                return low
            return word
        return apply_masked_sub(line, r"(?<![\w.])[A-Za-z_]\w*\b", repl)

    def _fix_main_signature(self, line: str, no: int) -> str:
        masked, _, _, _ = split_code(line)
        if re.match(r"^\s*void\s+main\s*\(", masked):
            self.note(no, "'void main()' is not standard: main must return int -> 'int main()'.")
            return re.sub(r"\bvoid(\s+main\s*\()", r"int\1", line, count=1)
        if re.match(r"^\s*main\s*\(\s*(void)?\s*\)", masked):
            self.note(no, "main() needs a return type -> 'int main()'.")
            return re.sub(r"^(\s*)main", r"\1int main", line, count=1)
        return line

    def _fix_turbo_c(self, line: str, no: int) -> Optional[str]:
        masked, _, _, _ = split_code(line)
        stripped = masked.strip()
        if re.fullmatch(r"(clrscr|getch|getche)\s*\(\s*\)\s*;?", stripped):
            self.note(no, f"Removed non-standard '{stripped.split('(')[0]}()' (from conio.h).")
            return None
        return line

    def _fix_stream_operators(self, line: str, no: int) -> str:
        masked, _, _, _ = split_code(line)
        original = line
        if re.search(r"\b(cout|cerr|clog)\b", masked):
            # cout < x / cout > x / cout >> x  ->  cout << x
            line = apply_masked_sub(line, r"\b(cout|cerr|clog)\s*(?:<(?!<)|>>|>(?!>))", r"\1 <<")
            # a < "text" / a < endl / a >> "text" inside an output statement
            line = apply_masked_sub(line, r"(?<![<>])(?:<|>>|>)(?![<>=])(\s*)(?=[\"']|endl\b)", r"<<\1")
            # cout << x endl   ->  cout << x << endl
            line = apply_masked_sub(line, r"([\w\"')\]])(\s+)endl\b", r"\1 << endl")
            line = self._insert_missing_insertions(line)
        if re.search(r"\bcin\b", masked):
            line = apply_masked_sub(line, r"\bcin\s*(?:>(?!>)|<<|<(?!<))", "cin >>")
        if line != original:
            line = apply_masked_sub(line, r"(?<=\S)(<<|>>)(?=\S)", r" \1 ")
            line = apply_masked_sub(line, r"(<<|>>)(?=[^\s<>])", r"\1 ")
            self.note(no, "Fixed stream operator: output uses '<<' (cout << x), input uses '>>' (cin >> x).")
        return line

    @staticmethod
    def _insert_missing_insertions(line: str) -> str:
        """cout << "a" x;  ->  cout << "a" << x;"""
        masked, comment, _, _ = split_code(line)
        code = line[: len(masked)]
        tokens = list(re.finditer(r"\"[^\"]*\"|'[^']*'|\d+(?:\.\d+)?|[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*|<<|>>|\S", masked))
        inserts = []
        operand = lambda t: (t[0] in "\"'" or t[0].isdigit() or (t[0].isalpha() or t[0] == "_")) and t not in CPP_KEYWORDS
        start = next((i for i, t in enumerate(tokens) if t.group(0) in {"cout", "cerr", "std::cout"} or t.group(0).endswith("cout")), None)
        if start is None:
            return line
        depth = 0
        for a, b in zip(tokens[start + 1:], tokens[start + 2:]):
            depth += (a.group(0) in "([") - (a.group(0) in ")]")
            if depth == 0 and operand(a.group(0)) and operand(b.group(0)):
                inserts.append(b.start())
        for pos in reversed(inserts):
            code = code[:pos] + "<< " + code[pos:]
        return code + comment

    def _fix_unterminated_string(self, line: str, no: int) -> str:
        masked, comment, _, quote = split_code(line)
        if not quote or comment:
            return line
        opening = line.rfind(quote, 0, len(line)) if line.count(quote) == 1 else None
        if opening is not None and quote == '"':
            tail = line[opening + 1:]
            m = re.search(r"\s*<<\s*[A-Za-z_(]", tail)
            if m:  # cout << "Value: << x;  ->  cout << "Value: " << x;
                cut = opening + 1 + m.start()
                self.note(no, "Closed the unterminated string before '<<'.")
                return line[:cut].rstrip() + ' "' + line[cut:]
        body = line.rstrip()
        tail = ""
        m = re.search(r"(\)?\s*;)\s*$", body)
        if m and body.count(quote) % 2 == 1:
            tail = m.group(1)
            body = body[: m.start()]
        self.note(no, f"Closed the unterminated {'string' if quote == chr(34) else 'character'} literal.")
        return body + quote + tail

    def _fix_misc(self, line: str, no: int) -> str:
        original = line
        masked = split_code(line)[0]
        # int main {  ->  int main() {
        if re.match(r"^\s*int\s+main\s*\{", masked):
            line = re.sub(r"main\s*\{", "main() {", line, count=1)
        # =< and => are not operators
        line = apply_masked_sub(line, r"=<(?!=)", "<=")
        line = apply_masked_sub(line, r"(?<![=!<>])=>", ">=")
        # elseif / elif
        line = apply_masked_sub(line, r"\belse\s*if\b|\belseif\b|\belif\b", "else if")
        # if (x =! 5)  ->  if (x != 5)
        if re.search(r"\b(if|while)\s*\(", masked):
            line = apply_masked_sub(line, r"=!(?!=)", "!=")
        # 'hello' (several chars in single quotes) -> "hello"
        line = re.sub(r"'((?:[^'\\\n]|\\.){2,})'", lambda m: m.group(0) if re.fullmatch(r"\\.", m.group(1)) else f'"{m.group(1)}"', line) \
            if re.search(r"'(?:[^'\\\n]|\\.){2,}'", line) and '"' not in line else line
        # cin >> a, b;  ->  cin >> a >> b;     cout << a, b;  ->  cout << a << b;
        for stream, op in (("cin", ">>"), ("cout", "<<")):
            m = re.match(rf"^(\s*(?:std::)?{stream}\s*{op}\s*)(.*?)(;?\s*)$", split_code(line)[0])
            if m and self.language == "cpp":
                body, mbody = line[m.start(2):m.end(2)], m.group(2)
                cuts, depth = [], 0
                for k, ch in enumerate(mbody):  # commas outside (), [] and string literals
                    depth += (ch in "([{") - (ch in ")]}")
                    if ch == "," and depth == 0:
                        cuts.append(k)
                if cuts:
                    parts = [body[a + 1 if a >= 0 else 0:b].strip() for a, b in zip([-1] + cuts, cuts + [len(body)])]
                    if all(parts):
                        line = line[:m.start(2)] + f" {op} ".join(parts) + line[m.end(2):]
        # if (x > 0)) {  ->  one ')' too many
        masked = split_code(line)[0]
        if masked.count(")") > masked.count("(") and re.match(r"^\s*(if|while|for|switch)\b", masked):
            extra = masked.count(")") - masked.count("(")
            for _ in range(extra):
                idx = split_code(line)[0].rfind(")")
                line = line[:idx] + line[idx + 1:]
        if line != original:
            self.note(no, "Fixed operator/quote typo on this line.")
        return line

    def _fix_stray_semicolons(self, lines: List[str]) -> List[str]:
        """for (...); { ... }  /  int f(int a); { ... }  ->  the ';' cuts the body off."""
        masked = masked_lines(lines)
        out = list(lines)
        for i, m_line in enumerate(masked):
            nxt = next((masked[k].strip() for k in range(i + 1, len(lines)) if masked[k].strip()), "")
            m = re.search(r"\)\s*(;)\s*(\{)?\s*$", m_line)
            if not m:
                continue
            control = re.match(r"^\s*(\}\s*)?(else\s+)?(if|for|while)\s*\(", m_line)
            header = HEADER_RE.match(m_line[:m.start(1)]) and not control
            if control and control.group(3) == "while" and control.group(1):
                continue  # } while (x);  is a do-while
            if (control or header) and (m.group(2) or nxt.startswith("{")):
                out[i] = lines[i][:m.start(1)] + lines[i][m.end(1):]
                self.note(i + 1, "Removed the stray ';' that cut the statement off from its { body }.")
        return out

    def _fix_parentheses(self, line: str, no: int) -> str:
        masked, comment, _, _ = split_code(line)
        stripped = masked.strip()
        opens, closes = masked.count("("), masked.count(")")
        if opens <= closes or not stripped or stripped.startswith("#"):
            return line
        if stripped.endswith(tuple(STATEMENT_END_OPERATORS) + (",", "(")):
            return line  # expression continues on the next line
        code = line[: len(masked)].rstrip()
        missing = ")" * (opens - closes)
        m = re.search(r"\s*(\{|;)\s*$", code)
        if m:
            code = code[: m.start()] + missing + code[m.start():]
        else:
            code = code + missing
        self.note(no, f"Added missing ')'.")
        return code + (" " + comment if comment else "")

    def _fix_semicolons(self, lines: List[str]) -> List[str]:
        info = []
        in_block = False
        for line in lines:
            masked, comment, in_block_after, _ = split_code(line, in_block)
            info.append((masked.strip(), comment, in_block))
            in_block = in_block_after
        # Brace kinds: inside enum / initializer lists, element lines don't take ';'
        kinds: List[str] = []
        paren_depth = 0
        result = list(lines)
        for i, (s, comment, was_block) in enumerate(info):
            kind_here = kinds[-1] if kinds else "file"
            nxt = next((info[j][0] for j in range(i + 1, len(info)) if info[j][0]), "")
            needs = self._needs_semicolon(s, nxt, kind_here) and paren_depth == 0 and not was_block
            for ch in s:
                if ch == "{":
                    kinds.append("init" if re.search(r"\benum\b|=\s*$|=\s*\{|\]\s*\{|^\{", s.split("{")[0] + "{") else "code")
                elif ch == "}" and kinds:
                    kinds.pop()
            paren_depth = max(0, paren_depth + s.count("(") - s.count(")"))
            if needs:
                raw = lines[i]
                code_part = raw[: len(raw) - len(comment)] if comment else raw
                result[i] = code_part.rstrip() + ";" + ((" " + comment) if comment else "")
                self.note(i + 1, "Added missing ';' at the end of the statement.")
        return result

    @staticmethod
    def _needs_semicolon(s: str, nxt: str, kind: str) -> bool:
        if not s or s.startswith("#") or kind == "init":
            return False
        if s[-1] in ";{},:(":
            return False
        if s.endswith(("++", "--")):
            return True
        if s.endswith(STATEMENT_END_OPERATORS):
            return False
        if re.fullmatch(r"(\}\s*)?(else|do|try)", s):
            return False
        if re.fullmatch(r"(\}\s*)?(else\s+)?(if|for|while|switch)\s*\(.*\)", s):
            return s.startswith("}") and s.lstrip("} ").startswith("while")  # } while (x);
        if re.fullmatch(r"(template\s*<.*>|(public|private|protected)\s*)", s):
            return False
        if nxt.startswith(CONTINUATION_STARTS):
            return False
        # function / class / struct header followed by a '{' on the next line
        if re.fullmatch(r"[\w:<>,\s\*&~\[\]]+\(.*\)\s*(const)?", s) and nxt.startswith("{"):
            return False
        if re.fullmatch(r"(struct|class|enum|union|namespace)\b.*", s):
            return False
        if s.startswith("using ") and s.endswith("std"):
            return True
        return True

    def _fix_braces(self, lines: List[str]) -> List[str]:
        depth = 0
        for line in lines:
            masked, _, _, _ = split_code(line)
            depth += masked.count("{") - masked.count("}")
        if depth <= 0:
            return lines
        # Use indentation to find where an unclosed block really ends:
        # a block whose body is indented ends where the code dedents back.
        indent = lambda l: len(l.expandtabs(4)) - len(l.expandtabs(4).lstrip())
        out: List[str] = []
        stack: List[Tuple[int, bool]] = []  # (opener indent, body is indented)
        masked_lines = [split_code(l)[0] for l in lines]
        for i, line in enumerate(lines):
            m = masked_lines[i].strip()
            if m and depth > 0:
                while stack and stack[-1][1] and indent(line) <= stack[-1][0] and not m.startswith("}") \
                        and not re.match(r"(else\b|while\b.*\)\s*;?$)", m):
                    opener_indent = stack.pop()[0]
                    out.append(" " * opener_indent + "}")
                    self.note(i + 1, "Added missing closing brace '}' where the block ends.")
                    depth -= 1
            out.append(line)
            for ch in m:
                if ch == "{":
                    nxt = next((lines[j] for j in range(i + 1, len(lines)) if masked_lines[j].strip()), "")
                    stack.append((indent(line), bool(nxt) and indent(nxt) > indent(line)))
                elif ch == "}" and stack:
                    stack.pop()
        lines = out
        if depth > 0:
            self.note(0, f"Added {depth} missing closing brace(s) '}}'.")
            lines = lines + ["}"] * depth
        return lines

    # ------------------------------------------------------ compiler pass
    def compile_diagnostics(self, code: str) -> Optional[List[Dict]]:
        """Run the compiler in syntax-only mode and return its JSON diagnostics."""
        if not self.compiler:
            return None
        tmp = tempfile.mkdtemp(prefix="smart_fix_")
        try:
            ext = "c" if self.language == "c" else "cpp"
            src = os.path.join(tmp, f"program.{ext}")
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            lang_flags = ["-x", "c", "-std=c11", "-O1"] if self.language == "c" else CPP_FLAGS
            proc = subprocess.run(
                [self.compiler, *pch_flags(code, self.language), *lang_flags, "-c", "-o", os.path.join(tmp, "p.o"),
                 "-Wall", "-Wextra",
                 "-fdiagnostics-format=json", "-fmax-errors=30", src],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10,
                env={**os.environ, "LC_ALL": "C", "LANG": "C"})
            raw = proc.stderr.strip()
            if not raw:
                return []
            data = []
            for chunk in raw.splitlines():
                chunk = chunk.strip()
                if chunk.startswith("["):
                    try:
                        data.extend(json.loads(chunk))
                    except json.JSONDecodeError:
                        pass
            out = []
            for d in data:
                loc = (d.get("locations") or [{}])[0].get("caret", {})
                if loc.get("file") and os.path.basename(loc["file"]) != os.path.basename(src):
                    continue  # error reported inside a system header
                out.append({
                    "kind": d.get("kind", ""),
                    "line": loc.get("line", 0),
                    "column": loc.get("byte-column", loc.get("column", 1)),
                    "message": d.get("message", ""),
                    "fixits": d.get("fixits", []) + [f for c in d.get("children", []) for f in c.get("fixits", [])],
                    "notes": [c.get("message", "") for c in d.get("children", [])],
                })
            return out
        except (subprocess.TimeoutExpired, OSError):
            return None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def compiler_loop(self, code: str, max_rounds: int = 30) -> str:
        if not self.compiler:
            return code
        seen = {code}
        for _ in range(max_rounds):
            diags = self.compile_diagnostics(code)
            if not diags:
                break
            errors = [d for d in diags if d["kind"] in {"error", "fatal error"}]
            if not errors:
                # Compiles - now fix the warnings that are almost always real bugs
                new_code = None
                for warn in diags:
                    candidate = self._repair_warning(code, warn)
                    if candidate is not None and candidate != code and candidate not in seen:
                        new_code = candidate
                        break
                if new_code is None:
                    break
                seen.add(new_code)
                code = new_code
                continue
            batched = self._batch_semicolons(code, errors)
            if batched is not None and batched not in seen:
                seen.add(batched)
                code = batched
                continue
            new_code = None
            for err in errors:
                candidate = self._repair(code, err)
                if candidate is not None and candidate != code and candidate not in seen:
                    new_code = candidate
                    break
            if new_code is None:
                break
            seen.add(new_code)
            code = new_code
        return code

    # ---------------------------------------------------- repair handlers
    def _repair(self, code: str, err: Dict) -> Optional[str]:
        lines = code.split("\n")
        msg, ln, col = err["message"], err["line"], max(1, err["column"])
        if not (1 <= ln <= len(lines)):
            if "at end of input" in msg and "}" in msg:
                self.note(0, "Added missing closing brace '}'.")
                return code + "\n}"
            return None
        line = lines[ln - 1]

        # add(1 2): the compiler suggests ')', but the call clearly continues -> ','
        if msg.startswith("expected ')' before"):
            ch = ")"
            masked = split_code(line)[0]
            rest, before = masked[col - 1:], masked[:col - 1].rstrip()
            # add(a b)  ->  add(a, b): the call continues and closes later on this line
            if rest.count(")") > rest.count("(") and before and (before[-1].isalnum() or before[-1] in "_\"')]") \
                    and re.match(r"[\w\"'(]", rest.lstrip()):
                lines[ln - 1] = line[:len(before)] + "," + line[len(before):]
                self.note(ln, "Inserted a missing ',' between arguments.")
                return "\n".join(lines)

        # 1. The compiler told us exactly what to change
        #    (but its "did you mean" for unknown names often points into system headers:
        #     name -> tzname, Hello -> ftello. Those are decided by the undeclared-name logic below.)
        guess = re.search(r"was not declared in this scope; did you mean '([\w:]+)'", msg)
        if err["fixits"] and not guess:
            fixed = self._apply_fixits(lines, err["fixits"])
            if fixed is not None:
                self.note(ln, f"Applied compiler fix-it for: {msg}")
                return fixed

        # 2. Missing punctuation
        if re.search(r"expected ',' or '\.\.\.' before", msg):
            fixed = self._insert_before_token(lines, ln, col, ",")
            if fixed is not None:
                self.note(ln, "Inserted a missing ',' between parameters.")
                return fixed
        m = re.search(r"expected '(;|\)|\]|,)'(?: or '(;|,)')?", msg)
        if m and ("before" in msg or "at end" in msg or "after" in msg):
            ch = ";" if ";" in (m.group(1), m.group(2)) else m.group(1)

            fixed = self._insert_before_token(lines, ln, col, ch, after=("after" in msg))
            if fixed is not None:
                self.note(ln, f"Inserted missing '{ch}' ({msg}).")
                return fixed
        if "expected '}' at end of input" in msg:
            self.note(0, "Added missing closing brace '}'.")
            return code + "\n}"

        # 3. Undeclared / misspelled names
        m = re.search(r"'([A-Za-z_]\w*)' was not declared in this scope|'([A-Za-z_]\w*)' undeclared|'([A-Za-z_]\w*)' is not a member of 'std'|'([A-Za-z_]\w*)' does not name a type|unknown type name '([A-Za-z_]\w*)'", msg)
        if m:
            name = next(g for g in m.groups() if g)
            header = self._suggested_header(err)
            if not header and name in HEADER_FOR:
                header = HEADER_FOR[name][1 if self.language == "c" else 0]
                if header and any(re.match(rf"\s*#\s*include\s*<{re.escape(header)}>", l) for l in lines):
                    header = None
            if header:
                self.note(ln, f"Added '#include <{header}>' (required for '{name}').")
                return self._add_include(lines, header)
            smart = self._smart_undeclared(lines, ln, name, msg)
            if smart is not None:
                return smart
            suggestion = re.search(r"did you mean '([A-Za-z_][\w:]*)'", msg)
            target = suggestion.group(1) if suggestion else None
            own = self._declared_names(lines) | {f["name"] for f in find_functions(lines)}
            if target and target not in own and target not in VOCAB:
                target = None  # a system-header name the user never meant
            if not target:
                vocab = VOCAB | own
                close = difflib.get_close_matches(name, vocab - {name}, n=1, cutoff=0.75) if len(name) > 2 else []
                target = close[0] if close else MISSPELLINGS.get(name.lower())
            if target:
                fixed_line = re.sub(rf"\b{re.escape(name)}\b", target, line, count=1)
                if fixed_line != line:
                    lines[ln - 1] = fixed_line
                    self.note(ln, f"Fixed unknown name '{name}' -> '{target}'.")
                    return "\n".join(lines)
            if name in {"cout", "cin", "endl", "cerr", "string"} and self.language == "cpp":
                return self._add_using_std(lines, ln)
            # A plain variable that was never declared: declare it properly
            declared = self._declare_variable(lines, ln, name, msg)
            if declared is not None:
                return declared

        # 4. Literals and stray characters
        if "missing terminating" in msg:
            quote = '"' if '"' in msg else "'"
            masked, comment, _, _ = split_code(line)
            fixed = self._fix_unterminated_string(line, ln)
            if fixed == line:
                fixed = line.rstrip() + quote
            lines[ln - 1] = fixed
            return "\n".join(lines)
        if msg.startswith("stray "):
            idx = col - 1
            if 0 <= idx < len(line.encode("utf-8")):
                raw = line.encode("utf-8")
                # drop the whole UTF-8 sequence that starts at idx
                end = idx + 1
                while end < len(raw) and (raw[end] & 0xC0) == 0x80:
                    end += 1
                lines[ln - 1] = (raw[:idx] + raw[end:]).decode("utf-8", "ignore")
                self.note(ln, "Removed a stray (non-ASCII) character.")
                return "\n".join(lines)

        # 5. Headers that do not exist
        m = re.search(r"([\w./+]+): No such file or directory", msg)
        if m:
            name = m.group(1)
            repl = LEGACY_HEADERS.get(name.lower(), "")
            if repl == "":
                close = difflib.get_close_matches(name.lower(), KNOWN_HEADERS, n=1, cutoff=0.6)
                repl = close[0] if close else None
            if repl:
                lines[ln - 1] = f"#include <{repl}>"
                self.note(ln, f"Replaced unknown header <{name}> with <{repl}>.")
            else:
                del lines[ln - 1]
                self.note(ln, f"Removed header <{name}>, which is not part of standard C/C++.")
            return "\n".join(lines)

        # 6. main() rules
        if "must return 'int'" in msg or "return type of 'main' is not 'int'" in msg:
            lines[ln - 1] = re.sub(r"\bvoid(\s+main\b)", r"int\1", line)
            self.note(ln, "main must return int -> 'int main()'.")
            return "\n".join(lines)
        if "declaration of 'main' with no type" in msg:
            lines[ln - 1] = re.sub(r"^(\s*)main\b", r"\1int main", line)
            self.note(ln, "main() needs a return type -> 'int main()'.")
            return "\n".join(lines)

        # 7. Wrong stream operator (cout < x, cin << x ...)
        if re.search(r"no match for 'operator(<|>|>>|<<)'", msg) and re.search(r"\b(cout|cin|cerr)\b", line):
            fixed = self._fix_stream_operators(line, ln)
            if fixed != line:
                lines[ln - 1] = fixed
                return "\n".join(lines)

        # 8. Extra closing brace at file scope
        if re.search(r"expected (declaration|unqualified-id) before '}' token", msg):
            idx = line.find("}", col - 1) if line.find("}", col - 1) >= 0 else line.find("}")
            if idx >= 0:
                lines[ln - 1] = line[:idx] + line[idx + 1:]
                if not lines[ln - 1].strip():
                    del lines[ln - 1]
                self.note(ln, "Removed an extra closing brace '}'.")
                return "\n".join(lines)

        # 9. Same variable declared twice in one scope -> second one becomes an assignment
        m = re.search(r"redeclaration of '(?:[\w:<>\s\*&]+?)\s*\b([A-Za-z_]\w*)'|conflicting declaration '(?:[\w:<>\s\*&]+?)\s*\b([A-Za-z_]\w*)'", msg)
        if m:
            name = m.group(1) or m.group(2)
            fixed_line = re.sub(rf"^(\s*)(?:const\s+|static\s+|unsigned\s+|long\s+)*[\w:<>]+\s*\*?\s*(?={re.escape(name)}\b\s*=)", r"\1", line, count=1)
            if fixed_line != line:
                lines[ln - 1] = fixed_line
                self.note(ln, f"'{name}' was already declared: changed the second declaration into an assignment.")
                return "\n".join(lines)

        funcs = None

        # 11. Wrong number of arguments: the callers show what the function needs
        m = re.search(r"too many arguments to function '[^']*?\b([A-Za-z_]\w*)\s*\(", msg)
        if m:
            funcs = find_functions(lines)
            func = next((f for f in funcs if f["name"] == m.group(1)), None)
            call = next((args for r, args in find_calls(lines, m.group(1), funcs) if r == ln - 1), None)
            if func and call and len(call) > len(func["params"]):
                taken = {n for _, n in func["params"]}
                for i in range(len(func["params"]), len(call)):
                    arg = call[i]
                    pname = arg if re.fullmatch(r"[A-Za-z_]\w*", arg) and arg not in taken else f"arg{i + 1}"
                    ptype = infer_type(arg, lines, funcs, self.language)
                    self._add_parameter(lines, funcs, func, ptype, pname)
                    funcs = find_functions(lines)
                    func = next(f for f in funcs if f["name"] == m.group(1))
                    taken.add(pname)
                self.note(func["header"] + 1, f"{func['name']}() is called with {len(call)} argument(s): added the missing parameter(s).")
                return "\n".join(lines)

        # 12. A function written inside another function -> move it above
        if "function-definition is not allowed here" in msg:
            funcs = find_functions(lines)
            outer = enclosing_function(funcs, ln - 1)
            masked = masked_lines(lines)
            head = ln - 1
            if "{" not in masked[head].split(")")[-1] and head > 0:
                head = max(0, head - 1)
            while head > 0 and not HEADER_RE.match(masked[head]) and not masked[head].strip():
                head -= 1
            depth, end = 0, None
            for k in range(ln - 1, len(lines)):
                for ch in masked[k]:
                    depth += (ch == "{") - (ch == "}")
                if depth <= 0 and "{" in "".join(masked[ln - 1:k + 1]):
                    end = k
                    break
            if outer and end is not None and outer["header"] < head:
                block = lines[head:end + 1]
                indent = min((len(b) - len(b.lstrip()) for b in block if b.strip()), default=0)
                block = [b[indent:] for b in block]
                del lines[head:end + 1]
                lines[outer["header"]:outer["header"]] = block + [""]
                self.note(ln, f"A function cannot be defined inside {outer['name']}(): moved it above {outer['name']}().")
                return "\n".join(lines)

        # 13. Return type problems
        m = re.search(r"declaration of '([A-Za-z_]\w*)' with no type", msg)
        if m:
            lines[ln - 1] = re.sub(rf"^(\s*)(?={re.escape(m.group(1))}\b)", r"\1int ", line, count=1)
            self.note(ln, f"{m.group(1)}() needs a return type -> int {m.group(1)}().")
            return "\n".join(lines)
        if "return-statement with a value, in function returning 'void'" in msg:
            funcs = find_functions(lines)
            func = enclosing_function(funcs, ln - 1)
            if func and func["name"] != "main":
                value = re.search(r"\breturn\s+(.+?);", split_code(line)[0])
                t = infer_type(line[value.start(1):value.end(1)] if value else "", lines, funcs, self.language)
                h = func["header"]
                lines[h] = re.sub(rf"\bvoid(\s+[\*&]*{re.escape(func['name'])}\b)", rf"{t}\1", lines[h], count=1)
                self.note(h + 1, f"{func['name']}() returns a value, so it cannot be void -> {t} {func['name']}().")
                return "\n".join(lines)

        # 14. 'else' without 'if' -> usually a stray ';' right after the if (...)
        if "'else' without a previous 'if'" in msg:
            masked = masked_lines(lines)
            for r in range(ln - 2, max(-1, ln - 15), -1):
                mm = re.search(r"\bif\s*\(.*\)\s*(;)\s*(\{)?\s*$", masked[r])
                if mm:
                    lines[r] = lines[r][:mm.start(1)] + lines[r][mm.end(1):]
                    self.note(r + 1, "Removed the stray ';' after if (...) that cut the if off from its body.")
                    return "\n".join(lines)

        # 15. A ';' between a function header and its body:  int f(); {
        if re.search(r"expected unqualified-id before '\{' token", msg):
            masked = masked_lines(lines)
            for r in range(ln - 1, max(-1, ln - 3), -1):
                mm = re.search(r"\)\s*(;)\s*(\{.*)?$", masked[r])
                if mm:
                    lines[r] = lines[r][:mm.start(1)] + lines[r][mm.end(1):]
                    self.note(r + 1, "Removed the ';' between the function header and its body.")
                    return "\n".join(lines)

        # 16. Values that do not fit their type
        m = re.search(r"too many initializers for '\w+ \[(\d+)\]'", msg)
        if m:
            mm = re.search(r"\[\s*\d+\s*\]\s*=\s*\{(.*)\}", line)
            if mm:
                count = len(split_top_level(mm.group(1)))
                lines[ln - 1] = re.sub(r"\[\s*\d+\s*\]", f"[{count}]", line, count=1)
                self.note(ln, f"The array has {count} values: changed its size to [{count}].")
                return "\n".join(lines)
        if "invalid conversion from 'const char*' to 'char'" in msg:
            fixed = re.sub(r'"(\\?.)"', r"'\1'", line, count=1)
            if fixed != line:
                lines[ln - 1] = fixed
                self.note(ln, "A char holds one character in single quotes: \"a\" -> 'a'.")
                return "\n".join(lines)
            if self.language == "cpp":
                lines[ln - 1] = re.sub(r"\bchar(\s+\w+\s*=)", r"string\1", line, count=1)
                self.note(ln, "Text in double quotes needs a string, not a char.")
                return "\n".join(lines)
        if "base operand of '->' has non-pointer type" in msg:
            lines[ln - 1] = line[:col - 1] + line[col - 1:].replace("->", ".", 1) if "->" in line[col - 1:] else line.replace("->", ".", 1)
            self.note(ln, "Use '.' to access a member of an object ('->' is only for pointers).")
            return "\n".join(lines)

        # 10. return with no value in int function
        if "return-statement with no value" in msg:
            lines[ln - 1] = re.sub(r"\breturn\s*;", "return 0;", line)
            self.note(ln, "Functions returning int must return a value -> 'return 0;'.")
            return "\n".join(lines)
        return None

    # ------------------------------------------- understanding undeclared names
    def _smart_undeclared(self, lines: List[str], ln: int, name: str, msg: str) -> Optional[str]:
        """Reasons a name can be unknown that a guess would get wrong."""
        funcs = find_functions(lines)
        row = ln - 1
        masked = split_code(lines[row])[0]
        used_as_call = re.search(rf"(?<![\w.]){re.escape(name)}\s*\(", masked)

        # (a) A function used before it is defined -> add a prototype above the caller
        target = next((f for f in funcs if f["name"] == name), None)
        if used_as_call and target and target["header"] > row:
            caller = enclosing_function(funcs, row)
            insert_at = caller["header"] if caller else row
            proto = f"{target['ret']} {name}({target['params_text'].strip()});"
            lines.insert(insert_at, proto)
            self.note(ln, f"'{name}' is called before it is defined: added the declaration '{proto}' above.")
            return "\n".join(lines)

        # (b) Used inside a function whose callers pass more arguments than it takes
        #     -> it was meant to be a parameter:  int prime() + prime(6)  =>  int prime(int n)
        func = enclosing_function(funcs, row)
        if func and not used_as_call and func["name"] != "main" and row > func["header"]:
            calls = find_calls(lines, func["name"], funcs)
            wanted = max((len(args) for _, args in calls), default=0)
            have = len(func["params"])
            if wanted > have:
                arg = next((args[have] for _, args in calls if len(args) > have), "")
                ptype = infer_type(arg, lines, funcs, self.language)
                if self._add_parameter(lines, funcs, func, ptype, name):
                    self.note(func["header"] + 1,
                              f"'{name}' is used in {func['name']}() and {func['name']}() is called with "
                              f"{wanted} argument(s): made it a parameter -> {ptype} {name}.")
                    return "\n".join(lines)
        return None

    def _add_parameter(self, lines: List[str], funcs: List[Dict], func: Dict, ptype: str, pname: str) -> bool:
        """Add a parameter to a function definition and to every prototype of it."""
        old = func["params_text"].strip()
        new_params = (old + ", " if func["params"] else "") + f"{ptype} {pname}"
        name = re.escape(func["name"])
        changed = False
        for row, text in enumerate(lines):
            masked = split_code(text)[0]
            is_header = row == func["header"]
            is_proto = bool(re.match(rf"^\s*[\w:<>\*&\s]+?[\s\*&]{name}\s*\([^()]*\)\s*;", masked))
            if not (is_header or is_proto):
                continue
            m = re.search(rf"\b{name}\s*\(([^()]*)\)", masked)
            if not m or parse_params(m.group(1)) != func["params"]:
                continue
            lines[row] = text[:m.start(1)] + new_params + text[m.end(1):]
            changed = True
        return changed

    def _declare_variable(self, lines: List[str], ln: int, name: str, msg: str) -> Optional[str]:
        """Declare a never-declared variable where it belongs, with the type its use implies."""
        if not ("was not declared" in msg or "undeclared" in msg) or name in VOCAB:
            return None
        row = ln - 1
        line = lines[row]
        masked = split_code(line)[0]
        if re.search(rf"(?<![\w.]){re.escape(name)}\s*\(", masked):
            return None  # an unknown function, not a variable
        funcs = find_functions(lines)
        func = enclosing_function(funcs, row)

        # cout << Hello;  ->  the author meant text
        if self.language == "cpp" and re.search(r"\b(cout|cerr)\b", masked) and \
                re.search(rf"<<\s*{re.escape(name)}\s*(<<|;|$)", masked) and \
                not any(re.search(rf"\b{re.escape(name)}\s*=[^=]", split_code(l)[0]) for l in lines) and \
                not difflib.get_close_matches(name, list(self._declared_names(lines)), n=1, cutoff=0.75):
            lines[row] = apply_masked_sub(line, rf"(<<\s*){re.escape(name)}(?=\s*(<<|;|$))", rf'\1"{name}"')
            self.note(ln, f"'{name}' is not a variable: printed it as the text \"{name}\".")
            return "\n".join(lines)

        # for (i = 0; ...)  ->  for (int i = 0; ...)
        m = re.search(rf"\bfor\s*\(\s*{re.escape(name)}\s*=\s*([^;]*);", masked)
        if m:
            t = infer_type(line[m.start(1):m.end(1)], lines, funcs, self.language)
            lines[row] = apply_masked_sub(line, rf"(\bfor\s*\(\s*)(?={re.escape(name)}\s*=)", rf"\1{t} ")
            self.note(ln, f"Declared the loop variable: for ({t} {name} = ...).")
            return "\n".join(lines)

        # Type from the first value assigned to it anywhere in the function
        scope = range(func["open"] + 1, func["end"]) if func else range(len(lines))
        assigned = None
        for r in scope:
            mm = re.search(rf"(?<![\w.]){re.escape(name)}\s*=(?!=)\s*([^;]+);", split_code(lines[r])[0])
            if mm:
                assigned = (r, lines[r][mm.start(1):mm.end(1)])
                break
        t = infer_type(assigned[1], lines, funcs, self.language) if assigned else "int"

        # x = 5;  as a plain statement in the function body  ->  int x = 5;
        body_depth = 0
        if func:
            for r in range(func["open"], row):
                mm = split_code(lines[r])[0]
                body_depth += mm.count("{") - mm.count("}")
        if assigned and assigned[0] == row and body_depth <= 1 and \
                re.match(rf"^\s*{re.escape(name)}\s*=(?!=)", masked):
            lines[row] = re.sub(rf"^(\s*)({re.escape(name)}\s*=)", rf"\1{t} \2", line, count=1)
            self.note(ln, f"'{name}' was never declared: declared it here as {t} {name}.")
            return "\n".join(lines)

        # Otherwise declare it once at the top of the function (never inside a loop)
        value = default_value(t)
        decl = f"{t} {name}" + (f" = {value}" if value is not None else "") + ";"
        if func:
            body = next((r for r in range(func["open"] + 1, func["end"] + 1) if lines[r].strip()), func["open"] + 1)
            indent = re.match(r"\s*", lines[body]).group(0) if body <= func["end"] and lines[body].strip() != "}" else "    "
            lines.insert(func["open"] + 1, indent + decl)
            where = f"at the start of {func['name']}()"
        else:
            lines.insert(row, re.match(r"\s*", line).group(0) + decl)
            where = "before its first use"
        self.note(ln, f"'{name}' was never declared: added '{decl}' {where}.")
        return "\n".join(lines)

    def _batch_semicolons(self, code: str, errors: List[Dict]) -> Optional[str]:
        """Insert every missing ';' the compiler reported, in one round (saves a compile per ';')."""
        if not errors or not re.match(r"expected '(;|,)'(?: or '(;|,)')? before", errors[0]["message"]):
            return None
        lines = code.split("\n")
        targets = set()
        for err in errors:
            if not re.match(r"expected '(;|,)'(?: or '(;|,)')? before", err["message"]):
                continue
            probe = list(lines)
            row_col = self._semicolon_target(probe, err["line"], max(1, err["column"]))
            if row_col:
                targets.add(row_col)
        if len(targets) < 2:
            return None
        for row, idx in sorted(targets, reverse=True):
            lines[row] = lines[row][:idx] + ";" + lines[row][idx:]
            self.note(row + 1, "Added missing ';' at the end of the statement.")
        return "\n".join(lines)

    @staticmethod
    def _semicolon_target(lines: List[str], ln: int, col: int) -> Optional[Tuple[int, int]]:
        row = ln - 1
        if not (0 <= row < len(lines)):
            return None
        masked = split_code(lines[row][: col - 1])[0]
        if masked.strip():
            return row, len(masked.rstrip())
        for r in range(row - 1, -1, -1):
            masked = split_code(lines[r])[0]
            if masked.strip():
                return r, len(masked.rstrip())
        return None

    def _repair_warning(self, code: str, warn: Dict) -> Optional[str]:
        """Code that compiles but is almost certainly wrong."""
        if warn["kind"] != "warning":
            return None
        lines = code.split("\n")
        msg, ln, col = warn["message"], warn["line"], max(1, warn["column"])
        if not (1 <= ln <= len(lines)):
            return None
        line = lines[ln - 1]
        masked = split_code(line)[0]

        # cin >> a, b;  /  cout << a, b;   (comma instead of >> / <<)
        if "right operand of comma operator has no effect" in msg or "left operand of comma operator has no effect" in msg:
            if re.search(r"\b(cin|cout)\b", masked):
                fixed = self._fix_misc(line, ln)
                if fixed != line:
                    lines[ln - 1] = fixed
                    return "\n".join(lines)

        # if (x = 5)  ->  if (x == 5)
        if "suggest parentheses around assignment used as truth value" in msg:
            m = re.search(r"\b(if|while)\s*\(", masked)
            if m:
                start = m.end()
                depth, end = 1, None
                for k in range(start, len(masked)):
                    depth += (masked[k] == "(") - (masked[k] == ")")
                    if depth == 0:
                        end = k
                        break
                cond = masked[start:end] if end else masked[start:]
                eq = re.search(r"(?<![=!<>+\-*/%&|^])=(?!=)", cond)
                if eq:
                    pos = start + eq.start()
                    lines[ln - 1] = line[:pos] + "==" + line[pos + 1:]
                    self.note(ln, "'=' assigns, '==' compares: changed the condition to use '=='.")
                    return "\n".join(lines)

        # if (x > 3);  ->  the ';' is the whole body
        if re.search(r"suggest braces around empty body in an? '(if|else|while|for)' statement|does not guard", msg):
            m = re.search(r"\b(if|while|for)\s*\(.*\)\s*(;)", masked)
            if m:
                lines[ln - 1] = line[:m.start(2)] + line[m.end(2):]
                self.note(ln, f"Removed the stray ';' after {m.group(1)} (...) - it made the {m.group(1)} do nothing.")
                return "\n".join(lines)

        # int sum;  sum += i;  ->  int sum = 0;
        m = re.search(r"'([A-Za-z_]\w*)' (?:is|may be) used uninitialized", msg)
        if m:
            name = m.group(1)
            pattern = rf"\b((?:unsigned\s+|long\s+|short\s+)*(?:int|long|short|float|double|char|bool|size_t))\b([^;=()]*?)\b{re.escape(name)}\b(?!\s*[=\[(])"
            for r in range(ln - 1, -1, -1):
                mm = re.search(pattern, split_code(lines[r])[0])
                if mm:
                    value = default_value(mm.group(1)) or "0"
                    end = mm.end()
                    lines[r] = lines[r][:end] + f" = {value}" + lines[r][end:]
                    self.note(r + 1, f"'{name}' was used before it had a value: initialised it to {value}.")
                    return "\n".join(lines)

        # int f() { ... }  with no return at the end
        if "control reaches end of non-void function" in msg or "no return statement in function returning non-void" in msg:
            funcs = find_functions(lines)
            func = enclosing_function(funcs, ln - 1)
            if func:
                value = default_value(func["ret"])
                if value is not None:
                    end = func["end"]
                    body = [lines[r] for r in range(func["open"] + 1, end) if lines[r].strip()]
                    indent = re.match(r"\s*", body[0]).group(0) if body else "    "
                    closing = lines[end]
                    if closing.strip() == "}":
                        lines.insert(end, f"{indent}return {value};")
                    else:
                        idx = split_code(closing)[0].rfind("}")
                        lines[end] = closing[:idx] + f" return {value}; " + closing[idx:]
                    self.note(end + 1, f"{func['name']}() must return a {func['ret']} on every path: added 'return {value};'.")
                    return "\n".join(lines)

        # scanf("%d", x)  ->  scanf("%d", &x)
        m = re.search(r"format '%\w+' expects argument of type '[^']*\*', but argument (\d+) has type '([^']*)'", msg)
        if m and "*" not in m.group(2) and "[" not in m.group(2) and re.search(r"\bscanf\s*\(", masked):
            call = re.search(r"\bscanf\s*\((.*)\)", masked)
            args = split_top_level(line[call.start(1):call.end(1)])
            idx = int(m.group(1)) - 1
            if 0 < idx < len(args) and not args[idx].startswith("&"):
                args[idx] = "&" + args[idx]
                lines[ln - 1] = line[:call.start(1)] + ", ".join(args) + line[call.end(1):]
                self.note(ln, "scanf needs the address of the variable: added '&'.")
                return "\n".join(lines)
        return None

    @staticmethod
    def _suggested_header(err: Dict) -> Optional[str]:
        for text in [err["message"]] + err["notes"]:
            m = re.search(r"#include <([\w./+]+)>", text)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def _add_include(lines: List[str], header: str) -> str:
        last = max((i for i, l in enumerate(lines) if l.strip().startswith("#include")), default=-1)
        lines.insert(last + 1, f"#include <{header}>")
        return "\n".join(lines)

    def _add_using_std(self, lines: List[str], ln: int) -> Optional[str]:
        if any(re.match(r"\s*using\s+namespace\s+std\s*;", l) for l in lines):
            return None
        last = max((i for i, l in enumerate(lines) if l.strip().startswith("#")), default=-1)
        lines.insert(last + 1, "using namespace std;")
        self.note(ln, "Added 'using namespace std;'.")
        return "\n".join(lines)

    @staticmethod
    def _apply_fixits(lines: List[str], fixits: List[Dict]) -> Optional[str]:
        text = "\n".join(lines)
        offsets = [0]
        for l in lines:
            offsets.append(offsets[-1] + len(l.encode("utf-8")) + 1)
        raw = text.encode("utf-8")

        def pos(loc):
            line, col = loc.get("line", 0), loc.get("byte-column", loc.get("column", 1))
            if not (1 <= line <= len(lines)):
                return None
            return offsets[line - 1] + col - 1

        edits = []
        for f in fixits:
            start, end = pos(f.get("start", {})), pos(f.get("next", {}))
            if start is None or end is None:
                return None
            edits.append((start, end, f.get("string", "").encode("utf-8")))
        for start, end, string in sorted(edits, reverse=True):
            raw = raw[:start] + string + raw[end:]
        return raw.decode("utf-8", "ignore")

    @staticmethod
    def _insert_before_token(lines: List[str], ln: int, col: int, ch: str, after: bool = False) -> Optional[str]:
        """Insert ch right after the last code character that precedes the error caret."""
        row = ln - 1
        if after:
            target = lines[row]
            masked, comment, _, _ = split_code(target)
            idx = min(len(target), col)  # caret is on the token we insert after
            lines[row] = target[:idx] + ch + target[idx:]
            return "\n".join(lines)
        masked, _, _, _ = split_code(lines[row][: col - 1])
        if masked.strip():
            idx = len(masked.rstrip())
            lines[row] = lines[row][:idx] + ch + lines[row][idx:]
            return "\n".join(lines)
        for r in range(row - 1, -1, -1):
            masked, comment, _, _ = split_code(lines[r])
            if masked.strip():
                idx = len(masked.rstrip())
                lines[r] = lines[r][:idx] + ch + lines[r][idx:]
                return "\n".join(lines)
        return None

    # ------------------------------------------------------------ driver
    def fix(self, code: str) -> str:
        code = self.prepass(code)
        code = self.compiler_loop(code)
        return code
