import os
import re
import difflib
import json
from typing import List, Dict, Optional, Any
import requests

class AIService:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY")
        self.provider = "gemini" if (os.getenv("GEMINI_API_KEY") or not os.getenv("OPENAI_API_KEY")) else "openai"
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _call_gemini(self, prompt: str, max_tokens: int = 200, temperature: float = 0.2) -> Optional[str]:
        if not self.api_key:
            return None
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
                "stopSequences": ["\n\n\n", "```"]
            }
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=3.5)
            if resp.status_code == 200:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return text
        except Exception as e:
            print(f"[AI Gemini Error] {e}")
        return None

    def _call_openai(self, prompt: str, max_tokens: int = 200, temperature: float = 0.2) -> Optional[str]:
        if not self.api_key:
            return None
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "model": self.openai_model,
            "messages": [
                {"role": "system", "content": "You are a code completion engine. Return ONLY the code continuation without markdown, backticks, or explanation."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=3.5)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[AI OpenAI Error] {e}")
        return None

    def _call_llm(self, prompt: str, max_tokens: int = 200, temperature: float = 0.2) -> Optional[str]:
        if not self.api_key:
            return None
        if self.provider == "gemini":
            return self._call_gemini(prompt, max_tokens, temperature)
        else:
            return self._call_openai(prompt, max_tokens, temperature)

    def rule_based_autocomplete(
        self,
        prefix: str,
        suffix: str,
        line: int,
        col: int,
        symbols: List[Dict[str, Any]],
        functions: List[str],
        language: str = "cpp"
    ) -> List[str]:
        """
        Fast, offline, contextual rule-based completion based on static analysis.
        Guarantees instant responses even if API key is not present or offline.
        """
        suggestions: List[str] = []
        lines = prefix.split("\n")
        current_line = lines[-1] if lines else ""
        trimmed = current_line.strip()

        var_names = [s["name"] for s in symbols]
        int_vars = [s["name"] for s in symbols if s.get("type") in ("int", "float")]

        # Case 1: a function header -> write its body.
        #   (a) cursor right after "int gcd(int a, int b) {"   (b) cursor on the blank line below it
        header_line, on_blank_line = trimmed, False
        if not trimmed and len(lines) >= 2 and lines[-2].rstrip().endswith("{"):
            header_line, on_blank_line = lines[-2].strip(), True
        func_match = re.search(r"^(?:static\s+|inline\s+)?(void|int|float|double|char|bool|string|long)\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*(\{?)$", header_line)
        if func_match and func_match.group(2) != "main":
            ret_type, func_name, params, brace = func_match.groups()
            header_src = lines[-2] if on_blank_line else current_line
            base = re.match(r"\s*", header_src).group(0)
            inner = base + "    "
            bodies = self._function_bodies(ret_type, func_name, params, language)
            for body in bodies:
                body_lines = [inner + l if l else "" for l in body]
                if on_blank_line:
                    # the cursor is already indented on the first body line
                    text = body_lines[0].lstrip() + "".join("\n" + l for l in body_lines[1:]) + "\n" + base + "}"
                else:
                    text = ("" if brace else " {") + "\n" + "\n".join(body_lines) + "\n" + base + "}"
                suggestions.append(self._balance_braces(text, prefix, suffix))
            return suggestions

        # Case 2: #include completions
        if re.search(r"^\s*#include\s*<?\s*$", trimmed):
            opened = trimmed.endswith("<")  # the '<' is already typed
            closer = ">" if not suffix.split("\n", 1)[0].lstrip().startswith(">") else ""
            for header in ("iostream", "vector", "string", "cmath", "algorithm", "cstdio"):
                suggestions.append(f"{header}{closer}" if opened else f"<{header}>")
            return suggestions

        # Case 3: "using namespace "
        if re.search(r"^\s*using\s+namespace\s*$", trimmed):
            suggestions.append(" std;")
            return suggestions

        # Case 4: int main(
        if re.search(r"^\s*int\s+main\s*\(\s*\)\s*\{?$", trimmed):
            brace = "{\n" if "{" not in trimmed else "\n"
            suggestions.append(f"{brace}    cout << \"Hello, World!\" << endl;\n    return 0;\n}}")
            suggestions.append(f"{brace}    int a = 10, b = 20;\n    int sum = a + b;\n    cout << sum << endl;\n    return 0;\n}}")
            return suggestions

        # Case 5: Incomplete assignment "int sum =" or "x =" or "int total ="
        assign_match = re.search(r"(?:(int|float|double)\s+)?([A-Za-z_]\w*)\s*=\s*$", trimmed)
        if assign_match:
            _, var_target = assign_match.groups()
            v_low = var_target.lower()
            candidates = [v for v in int_vars if v != var_target]

            if "sum" in v_low or "add" in v_low or "total" in v_low:
                if len(candidates) >= 2:
                    suggestions.append(f" {candidates[0]} + {candidates[1]};")
                    suggestions.append(f" {candidates[0]} + 10;")
                else:
                    suggestions.append(" a + b;")
                    suggestions.append(" 0;")
            elif "diff" in v_low or "sub" in v_low:
                if len(candidates) >= 2:
                    suggestions.append(f" {candidates[0]} - {candidates[1]};")
                else:
                    suggestions.append(" a - b;")
            elif "prod" in v_low or "mult" in v_low or "area" in v_low:
                if len(candidates) >= 2:
                    suggestions.append(f" {candidates[0]} * {candidates[1]};")
                else:
                    suggestions.append(" width * height;")
                    suggestions.append(" x * 2;")
            elif "avg" in v_low or "mean" in v_low:
                if len(candidates) >= 2:
                    suggestions.append(f" ({candidates[0]} + {candidates[1]}) / 2;")
                else:
                    suggestions.append(" (a + b) / 2;")
            elif "count" in v_low or "idx" in v_low or "i" in v_low:
                suggestions.append(" 0;")
                suggestions.append(" 1;")
            else:
                if len(candidates) >= 2:
                    suggestions.append(f" {candidates[0]} + {candidates[1]};")
                    suggestions.append(f" {candidates[0]};")
                elif len(candidates) == 1:
                    suggestions.append(f" {candidates[0]} + 10;")
                    suggestions.append(f" {candidates[0]};")
                else:
                    suggestions.append(" 0;")
                    suggestions.append(" 10;")
            return suggestions

        # Case 6: Incomplete control flow "if (" or "if("
        if re.search(r"\bif\s*\(\s*$", trimmed):
            if int_vars:
                v = int_vars[0]
                suggestions.append(f"{v} > 0) {{\n    \n}}")
                suggestions.append(f"{v} == 0) {{\n    return 0;\n}}")
                suggestions.append(f"{v} % 2 == 0) {{\n    // even\n}}")
                if len(int_vars) >= 2:
                    suggestions.append(f"{int_vars[0]} > {int_vars[1]}) {{\n    \n}}")
            else:
                suggestions.append("x > 0) {\n    \n}")
                suggestions.append("n == 0) {\n    return 0;\n}")
                suggestions.append("condition) {\n    \n}")
            return suggestions

        # Case 7: Else statement "else "
        if re.search(r"^\s*else\s*$", trimmed):
            suggestions.append("{\n    \n}")
            suggestions.append("if (")
            return suggestions

        # Case 8: Incomplete loop "for (" or "for("
        if re.search(r"\bfor\s*\(\s*$", trimmed):
            suggestions.append("int i = 0; i < n; i++) {\n    \n}")
            suggestions.append("int i = 0; i < 10; i++) {\n    \n}")
            suggestions.append("int i = 1; i <= n; i++) {\n    \n}")
            suggestions.append("int i = n - 1; i >= 0; i--) {\n    \n}")
            return suggestions

        # Case 9: While loop "while ("
        if re.search(r"\bwhile\s*\(\s*$", trimmed):
            if int_vars:
                suggestions.append(f"{int_vars[0]} > 0) {{\n    {int_vars[0]}--;\n}}")
                suggestions.append(f"{int_vars[0]} != 0) {{\n    \n}}")
            else:
                suggestions.append("i < 10) {\n    i++;\n}")
                suggestions.append("left <= right) {\n    \n}")
            return suggestions

        # Case 10: Switch case "switch ("
        if re.search(r"\bswitch\s*\(\s*$", trimmed):
            v = int_vars[0] if int_vars else "choice"
            suggestions.append(f"{v}) {{\n    case 1:\n        break;\n    default:\n        break;\n}}")
            return suggestions

        # Case 11: cout <<
        if re.search(r"\bcout\s*<<\s*$", trimmed):
            # only variables that really exist in the program
            for name in var_names[:2]:
                suggestions.append(f'"{name} = " << {name} << endl;')
            if var_names:
                suggestions.append(f"{var_names[0]} << endl;")
            suggestions.append('"Hello, World!" << endl;')
            return suggestions

        # Case 12: cin >>
        if re.search(r"\bcin\s*>>\s*$", trimmed):
            if var_names:
                suggestions.append(f"{var_names[0]};")
            else:
                suggestions.append("n;")
                suggestions.append("x >> y;")
            return suggestions

        # Case 13: printf(
        if re.search(r"\bprintf\s*\(\s*$", trimmed):
            if int_vars:
                suggestions.append(f'"%d\\n", {int_vars[0]});')
            else:
                suggestions.append('"Result: %d\\n", result);')
            suggestions.append('"Hello, World!\\n");')
            return suggestions

        # Case 14: Starting a variable declaration e.g. "int " or "float "
        if re.search(r"^(int|float|double|char|bool|string)\s+$", trimmed):
            dtype = trimmed.strip()
            if dtype == "int":
                suggestions.append("a = 10, b = 20;")
                suggestions.append("count = 0;")
                suggestions.append("result = 0;")
                suggestions.append("total = 100;")
                suggestions.append("n = 5;")
            elif dtype == "float" or dtype == "double":
                suggestions.append("rate = 0.05;")
                suggestions.append("pi = 3.14159;")
            elif dtype == "string":
                suggestions.append('name = "Alice";')
            elif dtype == "bool":
                suggestions.append("flag = true;")
            return suggestions

        # Case 15: Struct or Class definition
        if re.search(r"^\s*(struct|class)\s+([A-Za-z_]\w*)\s*\{?$", trimmed):
            brace = "{\n" if "{" not in trimmed else "\n"
            suggestions.append(f"{brace}public:\n    int id;\n    string name;\n}};")
            return suggestions

        # Case 16: Function call e.g. "add("
        fn_call = re.search(r"\b([A-Za-z_]\w*)\s*\(\s*$", trimmed)
        if fn_call:
            fn_name = fn_call.group(1)
            if fn_name not in ("if", "while", "for", "switch", "printf", "scanf"):
                if len(int_vars) >= 2:
                    suggestions.append(f"{int_vars[0]}, {int_vars[1]});")
                    suggestions.append(f"{int_vars[0]} + 1, {int_vars[1]});")
                elif len(int_vars) == 1:
                    suggestions.append(f"{int_vars[0]});")
                    suggestions.append(f"{int_vars[0]} + 1);")
                else:
                    suggestions.append("a, b);")
                    suggestions.append("10, 20);")
            return suggestions

        return suggestions

    # ------------------------------------------------------------------ bodies
    @staticmethod
    def _name_words(name: str) -> List[str]:
        """isPrimeNumber -> [is, prime, number];  find_max -> [find, max]"""
        return [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name.replace("_", " "))]

    @staticmethod
    def _balance_braces(text: str, prefix: str, suffix: str) -> str:
        """
        Editors auto-insert the closing '}' when '{' is typed. If the document already
        has it, drop the suggestion's own closing brace so accepting never adds an extra '}'.
        """
        from autofix import split_code
        def net(code: str) -> int:
            total, in_block = 0, False
            for ln in code.split("\n"):
                masked, _, in_block, _ = split_code(ln, in_block)
                total += masked.count("{") - masked.count("}")
            return total
        # Closers right after the cursor on the same line ({|} or (|)) are replaced on accept
        rest_line = suffix.split("\n", 1)[0]
        if re.fullmatch(r"\s*[)\]}]+;?\s*", rest_line):
            suffix = suffix[len(rest_line):]
        doc, extra = net(prefix + suffix), net(text)
        while doc + extra < 0 and text.rstrip().endswith("}"):
            text = text.rstrip()[:-1].rstrip(" \t")
            text = text[:-1] if text.endswith("\n") else text
            extra += 1
        return text

    def _function_bodies(self, ret: str, name: str, params: str, language: str = "cpp") -> List[List[str]]:
        """
        Bodies for common functions, written with the function's real parameter names.
        Never uses a variable that does not exist: without parameters, it declares sample inputs.
        """
        words, low = self._name_words(name), name.lower()

        def has(keys, prefixes=()):
            return low in keys or any(w in keys for w in words) or any(w.startswith(p) for w in words for p in prefixes)

        plist = [p.strip() for p in params.split(",") if p.strip() and p.strip() != "void"]
        all_names = [re.sub(r"\[.*\]", "", p).replace("&", " ").replace("*", " ").split()[-1] for p in plist]
        # numbers only: arrays and pointers are not used as plain values
        scalar = [(p, n) for p, n in zip(plist, all_names) if "[" not in p and "*" not in p]
        names = [n for _, n in scalar]
        floating = {n for p, n in scalar if re.search(r"\b(double|float)\b", p)}

        def iv(x: str) -> str:
            """% and digit loops need integers"""
            return f"(int){x}" if x in floating else x

        def loc(x: str) -> str:
            """a local that does not clash with a parameter name"""
            while x in all_names:
                x = x + "_"
            return x
        is_bool, is_void = ret == "bool", ret == "void"
        real = ret in ("double", "float")

        def inputs(count: int, samples=("a", "b"), values=("10", "20")):
            """Use the parameters; declare sample values only for the ones that are missing."""
            got = names[:count]
            decl = []
            for i in range(len(got), count):
                got.append(samples[i])
                decl.append(f"int {samples[i]} = {values[i]};")
            return got, decl

        def out(expr: str) -> List[str]:
            if not is_void:
                return [f"return {expr};"]
            shown = expr if re.fullmatch(r"[A-Za-z_]\w*", expr) else f"({expr})"
            if language == "c":
                return [f'printf("%d\\n", {expr});']
            return [f"cout << {shown} << endl;"]

        def truth(value: bool) -> str:
            return ("true" if value else "false") if (is_bool or language == "cpp") else ("1" if value else "0")

        bodies: List[List[str]] = []
        if has({"add", "addition", "sum", "plus", "total"}):
            (a, b), d = inputs(2)
            r = loc("result")
            bodies = [d + [f"{'double' if floating else 'int'} {r} = {a} + {b};"] + out(r), d + out(f"{a} + {b}")]
        elif has({"sub", "subtract", "subtraction", "diff", "difference", "minus"}):
            (a, b), d = inputs(2, values=("30", "10"))
            r = loc("result")
            bodies = [d + [f"{'double' if floating else 'int'} {r} = {a} - {b};"] + out(r), d + out(f"{a} - {b}")]
        elif has({"mul", "mult", "multiply", "multiplication", "product", "prod", "times"}):
            (a, b), d = inputs(2, values=("5", "4"))
            r = loc("result")
            bodies = [d + [f"{'double' if floating else 'int'} {r} = {a} * {b};"] + out(r), d + out(f"{a} * {b}")]
        elif has({"div", "divide", "division", "quotient", "quot"}):
            (a, b), d = inputs(2, values=("100", "5"))
            zero = "0.0" if real else "0"
            bodies = [d + [f"if ({b} == 0) {{", f"    return {zero};" if not is_void else "    return;", "}"] + out(f"{a} / {b}"),
                      d + out(f"({b} != 0) ? ({a} / {b}) : {zero}")]
        elif has({"mod", "modulo", "modulus", "remainder", "rem"}):
            (a, b), d = inputs(2, values=("17", "5"))
            bodies = [d + out(f"{iv(a)} % {iv(b)}")]
        elif has({"pow", "power", "exponent", "exp"}):
            (a, b), d = inputs(2, samples=("base", "exponent"), values=("2", "3"))
            r, i = loc("result"), loc("i")
            bodies = [d + [f"{'double' if a in floating else 'int'} {r} = 1;", f"for (int {i} = 0; {i} < {b}; {i}++) {{",
                           f"    {r} = {r} * {a};", "}"] + out(r)]
        elif has({"gcd", "hcf"}):
            (a, b), d = inputs(2, values=("48", "18"))
            x, y, t = loc("x"), loc("y"), loc("temp")
            loop = d + [f"int {x} = {iv(a)}, {y} = {iv(b)};", f"while ({y} != 0) {{", f"    int {t} = {y};",
                        f"    {y} = {x} % {y};", f"    {x} = {t};", "}"] + out(x)
            bodies = [loop]
            if names[:2] == [a, b] and len(all_names) == 2 and not floating and not is_void:
                bodies.append([f"if ({b} == 0) return {a};", f"return {name}({b}, {a} % {b});"])
        elif has({"prime"}, ("prime",)):
            (n,), d = inputs(1, samples=("n",), values=("7",))
            n, i, pr = iv(n), loc("i"), loc("isPrime")
            if is_void:
                bodies = [d + [f"bool {pr} = {n} > 1;", f"for (int {i} = 2; {i} * {i} <= {n}; {i}++) {{",
                               f"    if ({n} % {i} == 0) {{", f"        {pr} = false;", "        break;", "    }", "}"]
                          + ([f'printf("%s\\n", {pr} ? "Prime" : "Not prime");'] if language == "c"
                             else [f'cout << ({pr} ? "Prime" : "Not prime") << endl;'])]
            else:
                bodies = [d + [f"if ({n} <= 1) return {truth(False)};", f"for (int {i} = 2; {i} * {i} <= {n}; {i}++) {{",
                               f"    if ({n} % {i} == 0) return {truth(False)};", "}", f"return {truth(True)};"]]
        elif has({"fib", "fibo", "fibonacci"}, ("fib",)):
            (n,), d = inputs(1, samples=("n",), values=("10",))
            n = iv(n)
            pv, cu, nx, i = loc("prev"), loc("curr"), loc("next"), loc("i")
            loop = d + [f"if ({n} <= 1) " + (f"return {n};" if not is_void else f"{{ cout << {n} << endl; return; }}"),
                        f"int {pv} = 0, {cu} = 1;", f"for (int {i} = 2; {i} <= {n}; {i}++) {{", f"    int {nx} = {pv} + {cu};",
                        f"    {pv} = {cu};", f"    {cu} = {nx};", "}"] + out(cu)
            bodies = [loop]
            if len(all_names) == 1 and names and not floating and not is_void:
                bodies.append([f"if ({n} <= 1) return {n};", f"return {name}({n} - 1) + {name}({n} - 2);"])
        elif has({"reverse", "rev"}, ("revers",)):
            (n,), d = inputs(1, samples=("num",), values=("1234",))
            rv, m = loc("rev"), loc("rest")
            bodies = [d + [f"int {rv} = 0;", f"int {m} = {iv(n)};", f"while ({m} > 0) {{",
                           f"    {rv} = {rv} * 10 + {m} % 10;", f"    {m} = {m} / 10;", "}"] + out(rv)]
            bodies = [[l for l in b if l] for b in bodies]
        elif has({"square", "sqr", "sq"}):
            (n,), d = inputs(1, samples=("n",), values=("5",))
            bodies = [d + out(f"{n} * {n}")]
        elif has({"cube"}):
            (n,), d = inputs(1, samples=("n",), values=("3",))
            bodies = [d + out(f"{n} * {n} * {n}")]
        elif has({"max", "maximum", "largest", "greatest", "biggest"}):
            (a, b), d = inputs(2, values=("15", "25"))
            bodies = [d + [f"if ({a} > {b}) " + (f"return {a};" if not is_void else f"{{ cout << {a} << endl; return; }}")] + out(b),
                      d + out(f"({a} > {b}) ? {a} : {b}")]
        elif has({"min", "minimum", "smallest", "least"}):
            (a, b), d = inputs(2, values=("15", "25"))
            bodies = [d + [f"if ({a} < {b}) " + (f"return {a};" if not is_void else f"{{ cout << {a} << endl; return; }}")] + out(b),
                      d + out(f"({a} < {b}) ? {a} : {b}")]
        elif has({"avg", "average", "mean"}):
            (a, b), d = inputs(2)
            bodies = [d + out(f"({a} + {b}) / " + ("2.0" if real or is_void else "2"))]
        elif has({"fact", "factorial"}, ("fact",)):
            (n,), d = inputs(1, samples=("n",), values=("5",))
            r, i = loc("result"), loc("i")
            loop = d + [f"long long {r} = 1;", f"for (int {i} = 2; {i} <= {iv(n)}; {i}++) {{", f"    {r} = {r} * {i};", "}"] + out(r)
            bodies = [loop]
            if len(all_names) == 1 and names and not floating and not is_void:
                bodies.append([f"if ({n} <= 1) return 1;", f"return {n} * {name}({n} - 1);"])
        elif has({"swap"}):
            (a, b), d = inputs(2, values=("1", "2"))
            t = loc("temp")
            body = d + [f"{'double' if a in floating else 'int'} {t} = {a};", f"{a} = {b};", f"{b} = {t};"]
            if d or is_void and not all("&" in p or "*" in p for p in plist[:2]):
                # by-value parameters cannot swap the caller's variables: show the result
                body += [f'cout << {a} << " " << {b} << endl;'] if language == "cpp" else [f'printf("%d %d\\n", {a}, {b});']
            bodies = [body]
        elif has({"even"}, ("even",)):
            (n,), d = inputs(1, samples=("n",), values=("4",))
            bodies = [d + out(f"{iv(n)} % 2 == 0")]
        elif has({"odd"}, ("odd",)):
            (n,), d = inputs(1, samples=("n",), values=("7",))
            bodies = [d + out(f"{iv(n)} % 2 != 0")]
        elif has({"search", "bsearch", "binarysearch"}, ("search",)):
            arrays = [n for p, n in zip(plist, all_names) if "[" in p or "*" in p]
            if arrays and len(names) >= 2:
                arr, (n, target) = arrays[0], names[:2]
                prelude = []
            else:
                arr, n, target = "arr", "n", "target"
                prelude = ["int arr[] = {2, 4, 6, 8, 10};", "int n = 5;", "int target = 8;"]
            lo, hi, mid = loc("left"), loc("right"), loc("mid")
            bodies = [prelude + [f"int {lo} = 0, {hi} = {n} - 1;", f"while ({lo} <= {hi}) {{",
                                 f"    int {mid} = {lo} + ({hi} - {lo}) / 2;", f"    if ({arr}[{mid}] == {target}) return {mid};",
                                 f"    if ({arr}[{mid}] < {target}) {lo} = {mid} + 1;", f"    else {hi} = {mid} - 1;", "}",
                                 "return -1;"]]
            if is_void:
                bodies = [[l.replace(f"return {mid};", f"{{ cout << {mid} << endl; return; }}").replace("return -1;", "cout << -1 << endl;")
                           for l in bodies[0]]]
            elif ret in ("bool",):
                bodies = [[l.replace(f"return {mid};", "return true;").replace("return -1;", "return false;") for l in bodies[0]]]
        if bodies:
            return bodies
        # Fallbacks by return type
        if ret == "bool":
            return [["return true;"], ["return false;"]]
        if ret == "void":
            return [['cout << "Executing ' + name + '..." << endl;'] if language == "cpp"
                    else ['printf("Executing ' + name + '...\\n");']]
        if ret == "string":
            return [['return "";']]
        if ret in ("double", "float"):
            return [["return 0.0;"]]
        return [["int result = 0;", "return result;"], ["return 0;"]]

    def get_predictive_completion(
        self,
        prefix: str,
        suffix: str,
        line: int,
        col: int,
        language: str = "cpp",
        symbols: Optional[List[Dict[str, Any]]] = None,
        functions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        symbols = symbols or []
        functions = functions or []

        # 1. First get rule-based completions (instant, zero-latency)
        rule_suggestions = self.rule_based_autocomplete(prefix, suffix, line, col, symbols, functions, language)

        # 2. If API Key is configured, attempt intelligent LLM completion
        ai_suggestion = None
        if self.api_key:
            # Build smart prompt
            context_symbols = ", ".join([f"{s.get('type')} {s.get('name')}" for s in symbols[:8]])
            prompt = (
                f"You are an AI code completion assistant inside an IDE for {language}.\n"
                f"Known in-scope variables: {context_symbols if context_symbols else 'none'}\n"
                f"Below is the code up to the cursor position marked by <CURSOR>:\n"
                f"```\n{prefix}<CURSOR>{suffix}\n```\n"
                f"Instruction: Predict what the developer wants to write next at <CURSOR>.\n"
                f"Return ONLY the exact continuation characters/code to insert at <CURSOR>.\n"
                f"Do not repeat characters already before <CURSOR>. Do not enclose in backticks or markdown."
            )
            llm_res = self._call_llm(prompt, max_tokens=120, temperature=0.1)
            if llm_res:
                clean_res = llm_res.strip("`").strip()
                # filter if empty or echoed
                if clean_res and clean_res not in prefix:
                    ai_suggestion = clean_res

        # Combine suggestions: prioritize AI if high quality, with rule-based as alternatives
        all_suggestions = []
        if ai_suggestion:
            all_suggestions.append(ai_suggestion)
        for s in rule_suggestions:
            if s not in all_suggestions:
                all_suggestions.append(s)

        # If none matched, provide generic continuation if on identifier
        if not all_suggestions:
            last_token = prefix.split()[-1] if prefix.split() else ""
            if last_token in [s["name"] for s in symbols]:
                all_suggestions.append(" = 0;")

        return {
            "suggestions": all_suggestions,
            "source": "hybrid" if ai_suggestion else "rule_based",
            "active_ai": bool(self.api_key)
        }

    def explain_and_fix(self, diagnostic: Dict[str, Any], code_context: str, language: str = "cpp") -> Dict[str, Any]:
        """Generate human-readable explanation and code fix for a diagnostic."""
        msg = diagnostic.get("message", "")
        line = diagnostic.get("line", 1)
        level = diagnostic.get("level", "ERROR")
        existing_suggestion = diagnostic.get("suggestion", "")

        explanation = f"Diagnostic on Line {line}: {msg}."
        fix = diagnostic.get("replacement") or existing_suggestion

        if "Missing ';'" in msg:
            explanation = f"In {language}, every statement must terminate with a semicolon ';'. Line {line} is currently missing one."
        elif "is not declared" in msg:
            var_name = re.search(r"'([^']+)'", msg)
            name = var_name.group(1) if var_name else "identifier"
            explanation = f"The identifier '{name}' was referenced before being declared or defined in the symbol table."
        elif "Duplicate definition" in msg or "Duplicate declaration" in msg:
            explanation = f"Redeclaration detected. Symbols within the same scope cannot be redefined with conflicting types or identical identifiers."
        elif "dead-code" in msg or "never used" in msg:
            explanation = f"This variable is allocated in the symbol table but never referenced in any subsequent expressions. Removing it saves memory."
        elif "overwritten before use" in msg:
            explanation = f"The value assigned to this variable is superseded by a subsequent assignment before ever being read."

        if self.api_key:
            prompt = (
                f"You are an expert compiler tutor and code fixer for {language}.\n"
                f"Code snippet around line {line}:\n```\n{code_context}\n```\n"
                f"Diagnostic: [{level}] {msg}\n"
                f"Explain the root cause in 2 concise sentences and provide the single line or minimal snippet that fixes it."
                f"Return JSON format: {{\"explanation\": \"...\", \"fix\": \"...\"}}"
            )
            llm_res = self._call_llm(prompt, max_tokens=150, temperature=0.1)
            if llm_res:
                try:
                    cleaned_json = re.search(r"\{.*\}", llm_res, re.DOTALL)
                    if cleaned_json:
                        parsed = json.loads(cleaned_json.group(0))
                        return {
                            "explanation": parsed.get("explanation", explanation),
                            "fix": parsed.get("fix", fix),
                            "source": "ai"
                        }
                except Exception:
                    pass

        return {
            "explanation": explanation,
            "fix": fix,
            "source": "static_analysis"
        }

ai_service = AIService()
