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
from typing import Dict, List, Optional, Tuple

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
            if self.language == "cpp":
                new = self._fix_stream_operators(new, no)
            new = self._fix_unterminated_string(new, no)
            new = self._fix_parentheses(new, no)
            _, _, in_block, _ = split_code(new)
            out.append(new)
        out = self._fix_semicolons(out)
        out = self._fix_braces(out)
        return "\n".join(out)

    def _fix_unicode(self, code: str) -> str:
        table = {"\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2033": '"', "\u2018": "'", "\u2019": "'",
                 "\u00a0": " ", "\u2003": " ", "\u2002": " ", "\uff1b": ";", "\u226a": "<<", "\u226b": ">>",
                 "\u2013": "-", "\u2014": "-", "\u2212": "-", "\uff08": "(", "\uff09": ")", "\u200b": ""}
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
        if word.lower() != "include":
            match = difflib.get_close_matches(word.lower(), ["include", "define"], n=1, cutoff=0.7)
            if match and word.lower() not in {"if", "ifdef", "ifndef", "endif", "else", "elif", "pragma", "undef", "define", "include", "error"}:
                self.note(no, f"Fixed directive '#{word}' -> '#{match[0]}'.")
                word = match[0]
            else:
                return line
        else:
            word = "include"
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
        for a, b in zip(tokens[start + 1:], tokens[start + 2:]):
            if operand(a.group(0)) and operand(b.group(0)):
                inserts.append(b.start())
        for pos in reversed(inserts):
            code = code[:pos] + "<< " + code[pos:]
        return code + comment

    def _fix_unterminated_string(self, line: str, no: int) -> str:
        masked, comment, _, quote = split_code(line)
        if not quote or comment:
            return line
        body = line.rstrip()
        tail = ""
        m = re.search(r"(\)?\s*;)\s*$", body)
        if m and body.count(quote) % 2 == 1:
            tail = m.group(1)
            body = body[: m.start()]
        self.note(no, f"Closed the unterminated {'string' if quote == chr(34) else 'character'} literal.")
        return body + quote + tail

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
            lang_flags = ["-x", "c", "-std=c11"] if self.language == "c" else ["-x", "c++", "-std=c++17"]
            proc = subprocess.run(
                [self.compiler, *lang_flags, "-fsyntax-only", "-fdiagnostics-format=json", "-fmax-errors=30", src],
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
                break
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

        # 1. The compiler told us exactly what to change
        if err["fixits"]:
            fixed = self._apply_fixits(lines, err["fixits"])
            if fixed is not None:
                self.note(ln, f"Applied compiler fix-it for: {msg}")
                return fixed

        # 2. Missing punctuation
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
            if header:
                self.note(ln, f"Added '#include <{header}>' (required for '{name}').")
                return self._add_include(lines, header)
            suggestion = re.search(r"did you mean '([A-Za-z_][\w:]*)'", msg)
            target = suggestion.group(1) if suggestion else None
            if not target:
                vocab = VOCAB | self._declared_names(lines)
                close = difflib.get_close_matches(name, vocab - {name}, n=1, cutoff=0.75)
                target = close[0] if close else MISSPELLINGS.get(name.lower())
            if target:
                fixed_line = re.sub(rf"\b{re.escape(name)}\b", target, line, count=1)
                if fixed_line != line:
                    lines[ln - 1] = fixed_line
                    self.note(ln, f"Fixed unknown name '{name}' -> '{target}'.")
                    return "\n".join(lines)
            if name in {"cout", "cin", "endl", "cerr", "string"} and self.language == "cpp":
                return self._add_using_std(lines, ln)
            # A plain variable that was never declared: declare it just before first use
            masked = split_code(line)[0]
            used_as_call = re.search(rf"\b{re.escape(name)}\s*\(", masked)
            if ("was not declared" in msg or "undeclared" in msg) and not used_as_call and name not in VOCAB:
                if True:
                    indent = line[: len(line) - len(line.lstrip())]
                    lines.insert(ln - 1, f"{indent}int {name} = 0; // Auto-declared fix")
                    self.note(ln, f"'{name}' was never declared: added 'int {name} = 0;'.")
                    return "\n".join(lines)

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

        # 10. return with no value in int function
        if "return-statement with no value" in msg:
            lines[ln - 1] = re.sub(r"\breturn\s*;", "return 0;", line)
            self.note(ln, "Functions returning int must return a value -> 'return 0;'.")
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
