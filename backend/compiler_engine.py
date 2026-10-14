import difflib
import re
import os
import subprocess
import tempfile
import shutil
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple, Any

from autofix import AutoFixer, split_code

KEYWORDS = {
    "int", "float", "char", "double", "void", "return", "if", "else", "while", "for",
    "using", "namespace", "cout", "cin", "endl", "std", "include", "string", "bool", "true", "false",
    "printf", "scanf", "puts"
}

TOKEN_PATTERN = re.compile(
    r"(?P<SPACE>[ \t]+)|(?P<PREPROCESSOR>\#[^\n]*)|(?P<COMMENT>//[^\n]*)|"
    r"(?P<FLOAT>\d+\.\d+)|(?P<NUMBER>\d+)|"
    r"(?P<STRING>\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')|"
    r"(?P<ID>[A-Za-z_]\w*)|(?P<OP>::|->|<<|>>|<=|>=|==|!=|&&|\|\||\+\+|--|[+\-*/%=<>.&|!?:~^\[\]])|"
    r"(?P<DELIM>[(){};,])|(?P<INVALID>.)"
)

DECLARATION = re.compile(
    r"^(int|float|double|char|string|bool)\s+([A-Za-z_]\w*)(?:\s*=\s*(.+))?$"
)
ASSIGNMENT = re.compile(r"^([A-Za-z_]\w*)\s*=\s*(.+)$")
PRINT = re.compile(r"^print\s*\(\s*(.*?)\s*\)$")
PRINTF = re.compile(r"^printf\s*\(\s*(.*?)\s*\)$")
FUNCTION_DEF = re.compile(r"^(int|float|double|char|void|bool|string)\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*(\{)?$")
CONTROL = re.compile(r"^(if|while)\s*\((.*?)\)$")
FOR_LOOP = re.compile(r"^for\s*\((.*?);(.*?);(.*?)\)$")
RETURN = re.compile(r"^return(?:\s+(.+))?$")
COUT = re.compile(r"^(?:std\s*::\s*)?cout\s*<<\s*(.+)$")
IDENTIFIER = re.compile(r"\b[A-Za-z_]\w*\b")
STRING_LITERAL = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'")
MAIN_DEF = re.compile(r"\b(?:int|void)\s+main\s*\(")
IOSTREAM_INCLUDE = re.compile(r"^\s*#\s*include\s*<\s*(?:iostream(?:\.h)?|bits/stdc\+\+\.h)\s*>")
STDIO_INCLUDE = re.compile(r"^\s*#\s*include\s*<\s*(?:cstdio|stdio\.h|bits/stdc\+\+\.h)\s*>")
USING_STD = re.compile(r"^\s*using\s+namespace\s+std\s*;")
# Names from namespace std used without a 'std::' qualifier
UNQUALIFIED_STD = re.compile(r"(?<!::)(?<!::\s)\b(cout|cin|cerr|endl|string)\b")
IOSTREAM_NAMES = re.compile(r"\b(cout|cin|cerr|endl)\b")
PRINTF_CALL = re.compile(r"\b(printf|scanf|puts)\s*\(")


@dataclass
class Diagnostic:
    level: str  # ERROR | WARNING | INFO
    line: int
    column: int
    message: str
    suggestion: str = ""
    replacement: Optional[str] = None
    source: str = "analyzer"  # analyzer | structure | compiler

    def to_dict(self):
        return asdict(self)


@dataclass
class Token:
    line: int
    column: int
    type: str
    lexeme: str

    def to_dict(self):
        return asdict(self)


class CompilerAnalyzer:
    def __init__(self, source: str, language: str = "cpp"):
        self.source = source
        self.language = language
        self.tokens: List[Token] = []
        self.symbols: Dict[str, Dict[str, Any]] = {}
        self.diagnostics: List[Diagnostic] = []
        self.optimizations: List[str] = []
        self.corrected_lines: List[str] = []
        self.assignments: Dict[str, List[int]] = {}
        self.usages: Dict[str, List[int]] = {}
        self.functions: Dict[str, Dict[str, Any]] = {}
        self.known_constants: Dict[str, str] = {}
        self.allow_guess_fixes = True  # rename typos / auto-declare variables in Corrected Code
        self.compiles_clean: Optional[bool] = None  # set by compiler_check() when g++/gcc is available
        self.expression_cache: Dict[str, Tuple[str, int]] = {}
        self.auto_declarations: Dict[str, int] = {}
        self.toplevel_statements: List[Tuple[int, str]] = []

    def add(self, level: str, line: int, column: int, message: str, suggestion: str = "", replacement: Optional[str] = None):
        self.diagnostics.append(Diagnostic(level, line, column, message, suggestion, replacement))

    def lex(self):
        for line_no, line in enumerate(self.source.splitlines(), 1):
            position = 0
            while position < len(line):
                match = TOKEN_PATTERN.match(line, position)
                if not match:
                    break
                kind, value = match.lastgroup, match.group()
                start_col = position + 1
                position = match.end()

                if kind in {"SPACE", "COMMENT", "PREPROCESSOR"}:
                    if kind in {"COMMENT", "PREPROCESSOR"}:
                        break
                    continue

                if kind == "ID":
                    kind = "KEYWORD" if value in KEYWORDS else "IDENTIFIER"
                elif kind == "DELIM":
                    kind = "DELIMITER"
                elif kind == "OP":
                    kind = "OPERATOR"
                elif kind == "INVALID":
                    self.add("ERROR", line_no, start_col, f"Invalid character '{value}'.", f"Remove invalid character '{value}'")

                self.tokens.append(Token(line=line_no, column=start_col, type=kind, lexeme=value))

    @staticmethod
    def identifiers(expression: str) -> List[str]:
        # Strip string and character literals
        cleaned = re.sub(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'", "", expression)
        return [x for x in IDENTIFIER.findall(cleaned) if x not in KEYWORDS]

    def check_expression(self, expression: str, line_no: int, col_offset: int = 1):
        called_functions = re.findall(r"\b([A-Za-z_]\w*)\s*\(", expression)
        for function_name in called_functions:
            if function_name in {"print", "printf", "scanf", "cin", "cout"}:
                continue
            if function_name not in self.functions:
                choices = difflib.get_close_matches(function_name, self.functions.keys(), n=1, cutoff=0.60)
                suggestion = f"Did you mean function '{choices[0]}'?" if choices else "Declare the function before calling it."
                replacement = f"{choices[0]}(" if choices else None
                self.add("ERROR", line_no, col_offset, f"Function '{function_name}' is not declared.", suggestion, replacement)

        for name in self.identifiers(expression):
            if name in called_functions:
                continue
            if name not in self.symbols:
                choices = difflib.get_close_matches(name, self.symbols.keys(), n=1, cutoff=0.60)
                suggestion = ""
                replacement = None
                if choices:
                    candidate = choices[0]
                    corrected = re.sub(rf"\b{re.escape(name)}\b", candidate, expression)
                    suggestion = f"Did you mean '{candidate}'? Suggested correction: {corrected}"
                    replacement = candidate
                    self.usages.setdefault(candidate, []).append(line_no)
                else:
                    self.auto_declarations.setdefault(name, line_no)
                    suggestion = f"Corrected Code adds: int {name} = 0; before this statement."
                self.add("ERROR", line_no, col_offset, f"'{name}' is not declared.", suggestion, replacement)
            else:
                self.usages.setdefault(name, []).append(line_no)

    def register_function(self, line_no: int, return_type: str, name: str, parameters: str):
        if name in self.functions:
            self.add("ERROR", line_no, 1, f"Duplicate definition of function '{name}'.", f"Rename or remove duplicate function '{name}'")
            return
        self.functions[name] = {"line": line_no, "return_type": return_type, "params": parameters}
        if not parameters.strip() or parameters.strip() == "void":
            return
        for parameter in parameters.split(","):
            match = re.fullmatch(r"\s*(int|float|char|string|bool)\s+([A-Za-z_]\w*)\s*", parameter)
            if not match:
                self.add("ERROR", line_no, 1, f"Invalid parameter declaration '{parameter.strip()}'.", "Provide a valid type and identifier.")
                continue
            data_type, parameter_name = match.groups()
            if parameter_name not in self.symbols:
                self.symbols[parameter_name] = {"type": data_type, "value": "parameter", "line": line_no}
                self.assignments.setdefault(parameter_name, []).append(line_no)

    def fold_constants(self, expression: str, line_no: int) -> str:
        if not re.fullmatch(r"[\d.\s+\-*/%()]+", expression):
            return expression
        try:
            value = eval(expression, {"__builtins__": {}}, {})
        except (ArithmeticError, SyntaxError, TypeError, ZeroDivisionError):
            return expression
        if isinstance(value, (int, float)):
            folded = str(value)
            if folded != re.sub(r"\s+", "", expression):
                self.optimizations.append(
                    f"Line {line_no}: Constant folding: {expression.strip()} -> {folded}"
                )
                return folded
        return expression

    def optimize_expression(self, expression: str, line_no: int, target: Optional[str] = None) -> str:
        original = expression.strip()
        propagated = original
        for name, value in self.known_constants.items():
            propagated = re.sub(rf"\b{re.escape(name)}\b", value, propagated)
        if propagated != original:
            self.optimizations.append(
                f"Line {line_no}: Constant propagation: {original} -> {propagated}"
            )

        simplified = propagated
        rules = (
            (r"^0\s*\+\s*(.+)$", r"\1"), (r"^(.+?)\s*\+\s*0$", r"\1"),
            (r"^(.+?)\s*-\s*0$", r"\1"), (r"^1\s*\*\s*(.+)$", r"\1"),
            (r"^(.+?)\s*\*\s*1$", r"\1"), (r"^(.+?)\s*/\s*1$", r"\1"),
            (r"^(.+?)\s*\*\s*0$", "0"), (r"^0\s*\*\s*(.+)$", "0"),
        )
        for pattern, replacement in rules:
            match = re.fullmatch(pattern, simplified)
            if match:
                simplified = match.expand(replacement)
                break
        if simplified != propagated:
            self.optimizations.append(
                f"Line {line_no}: Algebraic simplification: {propagated} -> {simplified}"
            )

        strength = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*\*\s*2\s*", simplified)
        if strength:
            operand = strength.group(1)
            simplified = f"{operand} + {operand}"
            self.optimizations.append(
                f"Line {line_no}: Strength reduction suggestion: {operand} * 2 -> {simplified}"
            )

        optimized = self.fold_constants(simplified, line_no)
        normalized = re.sub(r"\s+", "", original)
        if target and normalized and not re.fullmatch(r"[\d.]+", normalized):
            previous = self.expression_cache.get(normalized)
            if previous and previous[0] != target:
                self.optimizations.append(
                    f"Line {line_no}: Common subexpression: {original} was already computed in "
                    f"'{previous[0]}' on line {previous[1]}; reuse it where safe."
                )
            self.expression_cache[normalized] = (target, line_no)

        if target and re.fullmatch(r"-?\d+(?:\.\d+)?", optimized.strip()):
            self.known_constants[target] = optimized.strip()
        elif target:
            self.known_constants.pop(target, None)
            direct_copy = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*", optimized)
            if direct_copy and direct_copy.group(1) in self.symbols:
                self.optimizations.append(
                    f"Line {line_no}: Copy propagation opportunity: '{target}' receives '{direct_copy.group(1)}'; "
                    "the extra copy can be removed where safe."
                )
        return optimized

    def parse(self):
        depth = 0
        in_block = False
        source_lines = self.source.splitlines()
        for line_no, raw in enumerate(source_lines, 1):
            masked, _comment, in_block_after, _ = split_code(raw, in_block)
            # real code with comments removed (block-comment text blanked out)
            no_comment = "".join(c if m != " " or c in " \t" else " " for c, m in zip(raw, masked)) if in_block or "/*" in raw else raw[: len(masked)]
            in_block = in_block_after
            text = no_comment.strip()

            # Brace depth tells us whether this line sits inside a function body
            depth_before = depth
            code_only = STRING_LITERAL.sub("", no_comment)
            depth = max(0, depth + code_only.count("{") - code_only.count("}"))
            if depth_before == 0 and self._is_executable_statement(text):
                self.toplevel_statements.append((line_no, text))

            if not text:
                self.corrected_lines.append(raw)
                continue
            if text.startswith("#") or text == "using namespace std;" or text in {"{", "}", "};"}:
                self.corrected_lines.append(raw)
                continue

            # Strip block punctuation so "} else if (x) {" or "for (...) {" parse as headers
            header = re.sub(r"^\}\s*", "", text)
            header = re.sub(r"\s*\{$", "", header).strip()
            header = re.sub(r"^else\s+(?=if\b)", "", header)
            if header in {"", "else", "do", "try", "default:"} or re.fullmatch(r"case\s+.+:", header):
                self.corrected_lines.append(raw)
                continue
            if re.fullmatch(r"(break|continue)\s*;", header):
                self.corrected_lines.append(raw)
                continue
            # i++; --i; x += 2;  -> uses (and assigns) the variable
            incdec = re.fullmatch(r"(?:(\+\+|--)\s*([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*(\+\+|--)|([A-Za-z_]\w*)\s*([+\-*/%]=)\s*(.+?))\s*;", header)
            if incdec:
                name = incdec.group(2) or incdec.group(3) or incdec.group(5)
                self.check_expression(name, line_no)
                if incdec.group(7):
                    self.check_expression(incdec.group(7), line_no)
                self.assignments.setdefault(name, []).append(line_no)
                self.known_constants.pop(name, None)
                self.corrected_lines.append(raw)
                continue
            # cin >> a >> b;
            cin = re.fullmatch(r"(?:std\s*::\s*)?cin\s*>>\s*(.+?)\s*;", header)
            if cin:
                for name in [p.strip() for p in cin.group(1).split(">>")]:
                    self.check_expression(name, line_no)
                    if name in self.symbols:
                        self.assignments.setdefault(name, []).append(line_no)
                        self.known_constants.pop(name, None)
                self.corrected_lines.append(raw)
                continue

            function = FUNCTION_DEF.match(text)
            control = CONTROL.match(header)
            for_loop = FOR_LOOP.match(header)
            if re.fullmatch(r"(switch)\s*\((.*)\)", header):
                self.corrected_lines.append(raw)
                continue

            if function:
                return_type, name, parameters, _opening_brace = function.groups()
                self.register_function(line_no, return_type, name, parameters)
                self.corrected_lines.append(raw)
                continue

            if control:
                self.check_expression(control.group(2), line_no)
                self.corrected_lines.append(raw)
                continue

            if for_loop:
                init_part, cond_part, update_part = for_loop.groups()
                loop_decl = DECLARATION.match(init_part.strip())
                if loop_decl:
                    # for (int i = 0; ...) declares the loop variable
                    data_type, name, expression = loop_decl.groups()
                    if expression:
                        self.check_expression(expression, line_no)
                    self.symbols[name] = {"type": data_type, "value": "-", "line": line_no}
                    self.assignments.setdefault(name, []).append(line_no)
                    self.usages.setdefault(name, []).append(line_no)
                elif init_part.strip():
                    self.check_expression(init_part, line_no)
                if cond_part.strip():
                    self.check_expression(cond_part, line_no)
                if update_part.strip():
                    self.check_expression(update_part, line_no)
                self.corrected_lines.append(raw)
                continue

            has_semicolon = text.endswith(";")
            statement = text[:-1].strip() if has_semicolon else text
            corrected_stmt = raw

            next_code = next((l.split("//", 1)[0].strip() for l in source_lines[line_no:] if l.split("//", 1)[0].strip()), "")
            if not has_semicolon and next_code.startswith(("<<", ">>", "+", "-", "*", "/", "&&", "||", "?", ":", ".", ",")):
                self.corrected_lines.append(raw)
                continue

            if not has_semicolon:
                likely_statement = bool(DECLARATION.match(statement) or ASSIGNMENT.match(statement)
                                        or PRINT.match(statement) or PRINTF.match(statement) or COUT.match(statement) or RETURN.match(statement))
                if likely_statement:
                    self.add("ERROR", line_no, len(raw) + 1, "Missing ';' at the end of the statement.",
                             f"Suggested correction: {statement};", f"{statement};")
                    corrected_stmt = raw.rstrip() + ";"
                    has_semicolon = True
                else:
                    self.add("ERROR", line_no, 1, "Invalid statement syntax.", "Ensure statement has valid syntax and ends with semicolon.")
                    self.corrected_lines.append(raw)
                    continue

            # Check if this line has a typo correction for auto-fixing
            declaration = DECLARATION.match(statement)
            assignment = ASSIGNMENT.match(statement)
            printing = PRINT.match(statement)
            printf = PRINTF.match(statement)
            returning = RETURN.match(statement)
            cout = COUT.match(statement)

            if declaration:
                data_type, name, expression = declaration.groups()
                if name in self.symbols and self.symbols[name]["value"] != "parameter":
                    self.add("ERROR", line_no, 1, f"Duplicate declaration of '{name}'.", f"Remove or rename duplicate variable '{name}'.")
                else:
                    value = "-"
                    if expression:
                        self.check_expression(expression, line_no)
                        value = self.optimize_expression(expression, line_no, name)
                    self.symbols[name] = {"type": data_type, "value": value, "line": line_no}
                    self.assignments.setdefault(name, []).append(line_no)
                self.corrected_lines.append(corrected_stmt)

            elif assignment:
                name, expression = assignment.groups()
                line_to_add = corrected_stmt
                if name not in self.symbols:
                    choices = difflib.get_close_matches(name, self.symbols.keys(), n=1, cutoff=0.60)
                    if choices:
                        candidate = choices[0]
                        suggestion = f"Did you mean '{candidate}'?"
                        self.add("ERROR", line_no, 1, f"'{name}' is not declared.", suggestion, f"{candidate} = {expression};")
                        # Fix in corrected lines
                        if self.allow_guess_fixes:
                            line_to_add = re.sub(rf"\b{re.escape(name)}\b", candidate, corrected_stmt, count=1)
                    else:
                        self.auto_declarations.setdefault(name, line_no)
                        suggestion = f"Corrected Code adds: int {name} = 0; before this statement."
                        self.add("ERROR", line_no, 1, f"'{name}' is not declared.", suggestion)
                else:
                    self.assignments.setdefault(name, []).append(line_no)
                    self.symbols[name]["value"] = self.optimize_expression(expression, line_no, name)

                self.check_expression(expression, line_no)
                # Check if expression had a typo that we can fix in corrected line
                for bad_var in self.identifiers(expression):
                    if bad_var not in self.symbols:
                        choices = difflib.get_close_matches(bad_var, self.symbols.keys(), n=1, cutoff=0.60)
                        if choices and self.allow_guess_fixes:
                            line_to_add = re.sub(rf"\b{re.escape(bad_var)}\b", choices[0], line_to_add)

                self.corrected_lines.append(line_to_add)

            elif printing:
                expression = printing.group(1).strip()
                suggested_cout = f"cout << {expression} << endl;" if expression else 'cout << "" << endl;'
                self.add(
                    "ERROR",
                    line_no,
                    1,
                    f"'print()' is not standard C/C++. Use 'cout << {expression} << endl;' or 'printf(...)'.",
                    f"Replace with: {suggested_cout}",
                    suggested_cout
                )
                self.corrected_lines.append(suggested_cout)

            elif printf:
                arg_expr = printf.group(1).strip()
                self.check_expression(arg_expr, line_no)
                self.corrected_lines.append(corrected_stmt)

            elif cout:
                expression = cout.group(1).strip()
                self.check_expression(expression, line_no)
                self.corrected_lines.append(corrected_stmt)

            elif returning:
                expression = returning.group(1)
                if expression:
                    self.check_expression(expression, line_no)
                self.corrected_lines.append(corrected_stmt)

            else:
                self.add("ERROR", line_no, 1, "Unsupported C/C++ statement. Use variable declarations, assignments, functions, printf(), or cout <<.", "Check statement syntax.")
                self.corrected_lines.append(corrected_stmt)

        # Post-analysis checks for unused variables & dead stores
        for name, info in self.symbols.items():
            used = self.usages.get(name, [])
            assignments = self.assignments.get(name, [])
            if not used and info["value"] != "parameter":
                self.add("WARNING", info["line"], 1, f"'{name}' is declared but never used (dead-code candidate).", f"Consider removing unused variable '{name}'.")
            elif len(assignments) > 1 and not any(assignments[i] < u < assignments[i + 1]
                                                for i in range(len(assignments) - 1) for u in used):
                self.add("WARNING", assignments[0], 1, f"Earlier assignment to '{name}' is overwritten before use.", f"Check if initial value of '{name}' is redundant.")

        # corrected_lines is 1:1 with source lines here; tag each with its source line
        entries: List[Tuple[int, str]] = list(enumerate(self.corrected_lines, 1))

        # Auto declarations insertion for un-fixable missing variables
        guesses = self.auto_declarations if self.allow_guess_fixes else {}
        for name, line_no in sorted(guesses.items(), key=lambda item: item[1], reverse=True):
            insert_idx = max(0, line_no - 1)
            entries.insert(insert_idx, (line_no, f"    int {name} = 0; // Auto-declared fix"))

        before = len(self.diagnostics)
        entries = self.check_program_structure(entries)
        for d in self.diagnostics[before:]:
            d.source = "structure"
        self.corrected_lines = [text for _, text in entries]

    @staticmethod
    def _is_executable_statement(text: str) -> bool:
        """True for lines that must live inside a function body (cout, assignments, loops, return...)."""
        if not text or text.startswith("#") or text.startswith("using ") or text.startswith("namespace "):
            return False
        if set(text) <= {"{", "}", ";", " "}:
            return False
        if FUNCTION_DEF.match(text):
            return False
        # Any function definition/prototype header, whatever the return type (templates, classes ...)
        if re.fullmatch(r"(?:[\w:<>,\*&]+\s+)+[\*&]*[\w:~]+\s*\(.*\)\s*(?:const)?\s*(?:\{.*|;)?", text) \
                and not re.match(r"(?:else\s+)?(?:if|while|for|switch|return)\b", text):
            return False
        if re.match(r"(?:public|private|protected)\s*:", text):
            return False
        statement = text[:-1].strip() if text.endswith(";") else text
        # Global variable declarations are legal outside functions
        if DECLARATION.match(statement):
            return False
        # Type definitions and other declarations: struct/class/enum, typedef, template, arrays, const ...
        if re.match(r"^(struct|class|enum|union|typedef|template|namespace|extern|static|const|constexpr|"
                    r"unsigned|signed|long|short|auto|int|float|double|char|bool|string|void|std\s*::|vector\s*<)\b", statement):
            return False
        if text.startswith("}") or text.startswith("{"):
            return False
        # Function prototypes, e.g. "int add(int a, int b);"
        if re.match(r"^(int|float|double|char|void|bool|string)\s+[A-Za-z_]\w*\s*\(.*\)$", statement):
            return False
        return True

    def is_full_program(self) -> bool:
        """A source is a full program (not a quick snippet) once it has headers, a namespace or functions."""
        lines = self.source.splitlines()
        return (
            any(l.strip().startswith("#") for l in lines)
            or any(USING_STD.match(l) for l in lines)
            or bool(self.functions)
        )

    def check_program_structure(self, entries: List[Tuple[int, str]]) -> List[Tuple[int, str]]:
        """
        Whole-program checks a real C/C++ compiler/linker would enforce:
        a main() entry point, statements inside functions, the right headers and namespace.

        Full programs get ERRORs. Bare snippets (no headers, no functions) are still allowed
        to run - they are auto-wrapped - but INFO diagnostics say exactly what was assumed.
        """
        lines = self.source.splitlines()
        code_lines = [STRING_LITERAL.sub('""', l.split("//", 1)[0]) for l in lines]
        full = self.is_full_program()
        has_main = any(MAIN_DEF.search(l) for l in code_lines)
        has_iostream = any(IOSTREAM_INCLUDE.match(l) for l in lines)
        has_stdio = any(STDIO_INCLUDE.match(l) for l in lines)
        has_using_std = any(USING_STD.match(l) for l in lines)

        def first_line(pattern) -> Optional[int]:
            for no, l in enumerate(code_lines, 1):
                if not l.strip().startswith("#") and pattern.search(l):
                    return no
            return None

        iostream_line = first_line(IOSTREAM_NAMES)
        stdio_line = first_line(PRINTF_CALL)
        unqualified_line = first_line(UNQUALIFIED_STD) if self.language == "cpp" else None

        if not full:
            # Snippet mode: the runner wraps the code, so explain what it assumes in one note
            assumed = []
            if iostream_line and not has_iostream:
                assumed.append("#include <iostream>")
            if stdio_line and not has_stdio and not has_iostream:
                assumed.append("#include <stdio.h>" if self.language == "c" else "#include <cstdio>")
            if unqualified_line and not has_using_std:
                assumed.append("using namespace std;")
            if not has_main and self.toplevel_statements:
                assumed.append("int main() { ... return 0; }")
            if assumed:
                self.add("INFO", 1, 1,
                         "Snippet mode: this is not a complete program. To run it, the compiler adds "
                         + ", ".join(f"'{a}'" for a in assumed) + ".",
                         "Write these yourself to make it a complete C/C++ program.")
        else:
            # 1. Missing headers
            if iostream_line and not has_iostream:
                name = IOSTREAM_NAMES.search(code_lines[iostream_line - 1]).group(1)
                self.add("ERROR", iostream_line, 1,
                         f"'{name}' is used but '#include <iostream>' is missing.",
                         "Add '#include <iostream>' at the top of the file.", "#include <iostream>")
            if stdio_line and not has_stdio and not has_iostream:
                name = PRINTF_CALL.search(code_lines[stdio_line - 1]).group(1)
                header = "<stdio.h>" if self.language == "c" else "<cstdio>"
                self.add("WARNING", stdio_line, 1,
                         f"'{name}()' is used but '#include {header}' is missing.",
                         f"Add '#include {header}' at the top of the file.", f"#include {header}")

            # 2. Missing 'using namespace std;'
            if unqualified_line and not has_using_std:
                name = UNQUALIFIED_STD.search(code_lines[unqualified_line - 1]).group(1)
                self.add("ERROR", unqualified_line, 1,
                         f"'{name}' was not declared in this scope: it lives in namespace std.",
                         f"Add 'using namespace std;' after your #include lines, or write 'std::{name}'.",
                         "using namespace std;")

            # 3. Statements outside any function
            for line_no, text in self.toplevel_statements:
                self.add("ERROR", line_no, 1,
                         f"Statement '{text}' is outside any function. "
                         "Executable statements must be inside a function body such as int main() { ... }.",
                         "Move this statement inside int main() { ... }.")

            # 4. Missing main()
            if not has_main:
                at = self.toplevel_statements[0][0] if self.toplevel_statements else max(1, len(lines))
                self.add("ERROR", at, 1,
                         "No 'int main()' function is defined. Every C/C++ program needs main() as its entry point "
                         "(the linker reports: undefined reference to 'main').",
                         "Add:  int main() {  ...your statements...  return 0; }",
                         "int main() {")

        # ---- Build the corrected program (always a complete, standard program) ----
        prefix: List[Tuple[int, str]] = []
        if iostream_line and not has_iostream:
            prefix.append((0, "#include <iostream>"))
        if stdio_line and not has_stdio and not has_iostream:
            prefix.append((0, "#include <stdio.h>" if self.language == "c" else "#include <cstdio>"))

        if not has_main:
            if full:
                toplevel = {no for no, _ in self.toplevel_statements}
                in_main = lambda no, t: no in toplevel
            else:
                # Snippet: everything except directives goes inside main()
                in_main = lambda no, t: not t.strip().startswith(("#", "using "))
            body = [(no, ("    " + t) if t.strip() else "") for no, t in entries if in_main(no, t)]
            outside = [(no, t) for no, t in entries if not in_main(no, t)]
            while outside and not outside[-1][1].strip():
                outside.pop()
            while body and not body[-1][1].strip():
                body.pop()
            # Re-indent the body relative to its least-indented line
            indents = [len(t) - len(t.lstrip()) for _, t in body if t.strip()]
            strip = (min(indents) - 4) if indents else 0
            body = [(no, t[strip:] if t.strip() else t) for no, t in body]
            entries = outside + ([(0, "")] if outside else []) + [(0, "int main() {")] + body + [(0, "    return 0;"), (0, "}")]
        elif self.toplevel_statements:
            # main() exists, but statements were written outside it: move them to the top of main()
            toplevel = {no for no, _ in self.toplevel_statements}
            moved = [(no, "    " + t.strip()) for no, t in entries if no in toplevel]
            entries = [(no, t) for no, t in entries if no not in toplevel]
            main_idx = next((i for i, (_, t) in enumerate(entries) if MAIN_DEF.search(t)), None)
            if main_idx is not None:
                brace_idx = next((i for i in range(main_idx, len(entries)) if "{" in entries[i][1]), main_idx)
                entries[brace_idx + 1:brace_idx + 1] = moved

        if unqualified_line and not has_using_std:
            # Place 'using namespace std;' right after the last #include
            last_include = max((i for i, (_, t) in enumerate(entries) if t.strip().startswith("#")), default=-1)
            if last_include >= 0:
                entries.insert(last_include + 1, (0, "using namespace std;"))
            else:
                prefix.append((0, "using namespace std;"))

        if prefix:
            first = entries[0][1].strip() if entries else ""
            gap = [(0, "")] if first and not first.startswith(("#", "using ")) else []
            entries = prefix + gap + entries
        return entries

    def analyze(self):
        self.lex()
        self.parse()
        return self

    # ------------------------------------------------------------------
    # Real-compiler verification: g++/gcc is the authority on the ISO standard
    # ------------------------------------------------------------------
    def compiler_check(self):
        fixer = AutoFixer(self.source, self.language)
        if not fixer.compiler:
            return
        lines = self.source.splitlines()
        offset = 0
        code = self.source
        if not self.is_full_program():
            # Snippet: compile it the way the runner will run it
            header = ["#include <stdio.h>"] if self.language == "c" else \
                     ["#include <iostream>", "#include <cstdio>", "#include <string>", "using namespace std;"]
            header.append("int main() {")
            offset = len(header)
            code = "\n".join(header + lines + ["return 0;", "}"])
        diags = fixer.compile_diagnostics(code)
        if diags is None:
            return
        errors = []
        for d in diags:
            if d["kind"] not in {"error", "fatal error"}:
                continue
            line = d["line"] - offset
            if re.match(r"expected '(;|,)'", d["message"]) and 1 <= line <= len(lines):
                # gcc points at the token AFTER the missing ';' - report the line that needs it
                before = lines[line - 1][: max(0, d["column"] - 1)]
                if not before.strip():
                    prev = line - 1
                    while prev >= 1 and not lines[prev - 1].split("//", 1)[0].strip():
                        prev -= 1
                    if prev >= 1:
                        line = prev
                        d = {**d, "column": len(lines[prev - 1].rstrip()) + 1}
            if 1 <= line <= len(lines):
                errors.append((line, d))

        self.compiles_clean = not errors
        if not errors:
            # The real compiler accepts the code: our pattern-based ERRORs were false alarms.
            # Structural errors stay (e.g. a missing main() is only caught by the linker).
            self.diagnostics = [d for d in self.diagnostics
                                if d.level != "ERROR" or d.message.startswith("No 'int main()'")]
            return

        vague = ("Invalid statement syntax", "Unsupported C/C++ statement")
        compiler_text = " ".join(d["message"] for _, d in errors)
        stray_lines = {line for line, d in errors if d["message"].startswith(("stray", "missing terminating"))}

        def confirmed(diag) -> bool:
            if diag.level != "ERROR" or diag.source == "structure":
                return True
            if diag.message.startswith(vague):
                return False
            m = re.match(r"(?:Function )?'([A-Za-z_]\w*)' is not declared", diag.message)
            if m:
                return f"'{m.group(1)}'" in compiler_text
            if diag.message.startswith("Invalid character"):
                return diag.line in stray_lines
            return True

        self.diagnostics = [d for d in self.diagnostics if confirmed(d)]
        flagged = {d.line for d in self.diagnostics if d.level == "ERROR"}
        for line, d in errors:
            if line in flagged:
                continue
            flagged.add(line)
            self.add("ERROR", line, d["column"], f"{d['message']}",
                     "Click 'Fix All Errors' to repair this automatically.", None)
            self.diagnostics[-1].source = "compiler"

    def build_corrected_code(self) -> Tuple[str, List[str]]:
        """
        Rules first (typos, << vs <, ';', braces, headers, main...), then the analyzer's
        own fixes and program structure, then a compile-and-repair loop with g++/gcc.
        """
        fixer = AutoFixer(self.source, self.language)
        if self.compiles_clean:
            # Valid code is never rewritten. Only a missing main() is added.
            has_main = any(MAIN_DEF.search(split_code(l)[0]) for l in self.source.splitlines())
            if has_main:
                return self.source, []
            wrapper = CompilerAnalyzer(self.source, self.language)
            wrapper.allow_guess_fixes = False
            wrapper.lex()
            wrapper.parse()
            fixer.note(0, "Added the int main() entry point required by every C/C++ program.")
            return fixer.compiler_loop("\n".join(wrapper.corrected_lines)), fixer.fixes
        stage1 = fixer.prepass(self.source)
        second = CompilerAnalyzer(stage1, self.language)
        second.allow_guess_fixes = fixer.compiler is None
        second.lex()
        second.parse()
        for d in second.diagnostics:
            if d.source != "structure":
                continue
            if "int main()" in d.message or "Snippet mode" in d.message:
                fixer.note(0, "Put the statements inside int main() { ... return 0; }.")
            if "namespace std" in d.message or "'using namespace std;'" in d.message:
                fixer.note(0, "Added 'using namespace std;'.")
            m = re.search(r"#include <([\w.]+)>", d.message)
            if m:
                fixer.note(0, f"Added '#include <{m.group(1)}>'.")
        stage2 = fixer.prepass("\n".join(second.corrected_lines))
        final = fixer.compiler_loop(stage2)
        return final, fixer.fixes

    def execute_code(self) -> Dict[str, Any]:
        """
        Execute the code and return stdout, stderr, execution status and time.
        First tries native GCC/G++ compilation if available;
        If snippet doesn't have main() or header, wraps automatically or runs through interpreter.
        """
        # If there are syntax/semantic errors, report execution blocked
        errors = [d for d in self.diagnostics if d.level == "ERROR"]
        if errors:
            err_summary = "\n".join([f"Line {e.line}: {e.message}" for e in errors])
            return {
                "success": False,
                "output": "",
                "error": f"Build halted: {len(errors)} error(s) detected.\n{err_summary}",
                "execution_type": "static_check"
            }

        # Locate g++ compiler on system
        gxx_path = shutil.which("g++")
        if not gxx_path:
            for candidate in [
                r"C:\msys64\ucrt64\bin\g++.exe",
                r"C:\MinGW\bin\g++.exe",
                r"C:\msys64\mingw64\bin\g++.exe",
                "/usr/bin/g++"
            ]:
                if os.path.exists(candidate):
                    gxx_path = candidate
                    break

        # Prepare executable code snippet
        raw_code = self.source
        executable_code = raw_code

        has_main = bool(re.search(r"\b(int|void)\s+main\s*\(", executable_code))
        has_include = "#include" in executable_code
        has_namespace = "using namespace std;" in executable_code

        full_cpp = []
        if not has_include:
            full_cpp.append("#include <iostream>")
            full_cpp.append("#include <cstdio>")
        if not has_namespace:
            full_cpp.append("using namespace std;")

        if not has_main:
            # Wrap standalone top-level statements inside main(), but keep
            # preprocessor directives and 'using' declarations at file scope -
            # putting '#include <iostream>' inside main() breaks the std headers.
            body = []
            for line in executable_code.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("using "):
                    full_cpp.append(line)
                else:
                    body.append(line)
            full_cpp.append("int main() {")
            for line in body:
                full_cpp.append("    " + line)
            full_cpp.append("    return 0;")
            full_cpp.append("}")
        else:
            full_cpp.append(executable_code)

        final_source = "\n".join(full_cpp)

        # 1. Try native compilation if g++ is present
        if gxx_path:
            temp_dir = tempfile.mkdtemp(prefix="smart_compiler_")
            src_file = os.path.join(temp_dir, "program.cpp")
            exe_file = os.path.join(temp_dir, "program.exe" if os.name == "nt" else "program.out")

            try:
                with open(src_file, "w", encoding="utf-8") as f:
                    f.write(final_source)

                # Compile
                compile_proc = subprocess.run(
                    [gxx_path, "-O2", src_file, "-o", exe_file],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5
                )

                if compile_proc.returncode != 0:
                    return {
                        "success": False,
                        "output": "",
                        "error": compile_proc.stderr,
                        "execution_type": "native_g++"
                    }

                # Run executable
                run_proc = subprocess.run(
                    [exe_file],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=4
                )

                return {
                    "success": run_proc.returncode == 0,
                    "output": run_proc.stdout if run_proc.stdout else "(Program exited successfully with code 0)",
                    "error": run_proc.stderr,
                    "execution_type": "native_g++"
                }
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "output": "",
                    "error": "Execution timed out (infinite loop or process exceeded 4 seconds limit).",
                    "execution_type": "native_g++"
                }
            except Exception as e:
                # Fallback to simulated execution if error occurs
                pass
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        # 2. Built-in interpreter simulation (works anywhere even without g++)
        simulated_output = []
        for line in raw_code.splitlines():
            # Check print(expr) or cout << expr
            m_print = re.search(r"\bprint\s*\(\s*(.*?)\s*\)", line)
            m_cout = re.search(r"\bcout\s*<<\s*(.*?)(?:<<\s*endl)?\s*;", line)
            expr = None
            if m_print:
                expr = m_print.group(1).strip()
            elif m_cout:
                expr = m_cout.group(1).strip()

            if expr:
                # Substitute known symbols
                val_expr = expr
                for s_name, s_info in self.symbols.items():
                    val = str(s_info.get("value", ""))
                    if val and val != "-":
                        val_expr = re.sub(rf"\b{re.escape(s_name)}\b", val, val_expr)
                try:
                    res = eval(val_expr, {"__builtins__": {}}, {})
                    simulated_output.append(str(res))
                except Exception:
                    # If string literal or variable
                    if expr in self.symbols:
                        simulated_output.append(str(self.symbols[expr]["value"]))
                    else:
                        simulated_output.append(expr.strip('"').strip("'"))

        return {
            "success": True,
            "output": "\n".join(simulated_output) if simulated_output else "(Program analyzed and completed successfully)",
            "error": "",
            "execution_type": "fast_interpreter"
        }

    def get_results(self) -> Dict[str, Any]:
        # Verify with the real compiler before deciding what is an error
        self.compiler_check()
        errors = sum(1 for d in self.diagnostics if d.level == "ERROR")
        warnings = sum(1 for d in self.diagnostics if d.level == "WARNING")
        corrected_code, fixes = self.build_corrected_code()

        # Execute program
        execution_res = self.execute_code()

        return {
            "tokens": [t.to_dict() for t in self.tokens],
            "symbols": [
                {"name": name, "type": info["type"], "value": info["value"], "line": info["line"]}
                for name, info in self.symbols.items()
            ],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "optimizations": self.optimizations,
            "corrected_code": corrected_code,
            "fixes": fixes,
            "execution": execution_res,
            "summary": {
                "token_count": len(self.tokens),
                "symbol_count": len(self.symbols),
                "errors": errors,
                "warnings": warnings,
                "optimization_count": len(self.optimizations),
                "status": "Analysis completed with diagnostics." if errors else "Analysis completed successfully."
            }
        }
