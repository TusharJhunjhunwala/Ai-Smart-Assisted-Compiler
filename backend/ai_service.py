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
        functions: List[str]
    ) -> List[str]:
        """
        Fast, offline, contextual rule-based completion based on static analysis.
        Guarantees instant responses even if API key is not present or offline.
        """
        suggestions: List[str] = []
        lines = prefix.splitlines()
        current_line = lines[-1] if lines else ""
        trimmed = current_line.strip()

        var_names = [s["name"] for s in symbols]
        int_vars = [s["name"] for s in symbols if s.get("type") in ("int", "float")]

        # Case 1: Function signature definition ending in '{' or newline after signature
        # e.g., "void add() {" or "int sum(int a, int b) {" or "void add() {"
        func_match = re.search(r"\b(void|int|float|char|bool|string)\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*\{?$", trimmed)
        if func_match:
            ret_type, func_name, params = func_match.groups()
            brace_needed = "{" not in trimmed
            prefix_brace = "{\n" if brace_needed else "\n"
            indent = "    "
            
            # Predict body based on function name & return type
            fn_lower = func_name.lower()
            
            # Helper for parameter extraction
            p_names = [p.strip().split()[-1] for p in params.split(",") if p.strip()] if params and params.strip() != "void" else []
            
            # Operation 1: Addition / Sum
            if "add" in fn_lower or "sum" in fn_lower:
                if len(p_names) >= 2:
                    body1 = f"{indent}int result = {p_names[0]} + {p_names[1]};\n{indent}return result;\n}}" if ret_type != "void" else f"{indent}int result = {p_names[0]} + {p_names[1]};\n{indent}cout << result << endl;\n{indent}return;\n}}"
                    body2 = f"{indent}return {p_names[0]} + {p_names[1]};\n}}" if ret_type != "void" else f"{indent}cout << ({p_names[0]} + {p_names[1]}) << endl;\n{indent}return;\n}}"
                    suggestions.append(f"{prefix_brace}{body1}")
                    suggestions.append(f"{prefix_brace}{body2}")
                else:
                    if ret_type == "void":
                        body1 = f"{indent}int a = 10;\n{indent}int b = 20;\n{indent}int sum = a + b;\n{indent}cout << sum << endl;\n{indent}return;\n}}"
                        body2 = f"{indent}int a = 10;\n{indent}int b = 20;\n{indent}cout << (a + b) << endl;\n{indent}return;\n}}"
                        suggestions.append(f"{prefix_brace}{body1}")
                        suggestions.append(f"{prefix_brace}{body2}")
                    else:
                        body1 = f"{indent}int a = 10;\n{indent}int b = 20;\n{indent}int result = a + b;\n{indent}return result;\n}}"
                        body2 = f"{indent}int a = 10;\n{indent}int b = 20;\n{indent}return a + b;\n}}"
                        suggestions.append(f"{prefix_brace}{body1}")
                        suggestions.append(f"{prefix_brace}{body2}")
                return suggestions
            
            # Operation 2: Subtraction / Difference
            elif "sub" in fn_lower or "diff" in fn_lower or "minus" in fn_lower:
                if len(p_names) >= 2:
                    body = f"{indent}int result = {p_names[0]} - {p_names[1]};\n{indent}return result;\n}}" if ret_type != "void" else f"{indent}int result = {p_names[0]} - {p_names[1]};\n{indent}cout << result << endl;\n{indent}return;\n}}"
                else:
                    body = f"{indent}int a = 30;\n{indent}int b = 10;\n{indent}int diff = a - b;\n{indent}return diff;\n}}" if ret_type != "void" else f"{indent}int a = 30;\n{indent}int b = 10;\n{indent}int diff = a - b;\n{indent}cout << diff << endl;\n{indent}return;\n}}"
            
            # Operation 3: Multiplication / Product
            elif "mult" in fn_lower or "prod" in fn_lower:
                if len(p_names) >= 2:
                    body = f"{indent}int result = {p_names[0]} * {p_names[1]};\n{indent}return result;\n}}" if ret_type != "void" else f"{indent}int result = {p_names[0]} * {p_names[1]};\n{indent}cout << result << endl;\n{indent}return;\n}}"
                else:
                    body = f"{indent}int a = 5;\n{indent}int b = 4;\n{indent}return a * b;\n}}" if ret_type != "void" else f"{indent}int a = 5;\n{indent}int b = 4;\n{indent}int prod = a * b;\n{indent}cout << prod << endl;\n{indent}return;\n}}"
            
            # Operation 4: Division / Quotient
            elif "div" in fn_lower or "quot" in fn_lower:
                if len(p_names) >= 2:
                    body1 = f"{indent}if ({p_names[1]} == 0) return 0;\n{indent}return {p_names[0]} / {p_names[1]};\n}}"
                    body2 = f"{indent}return ({p_names[1]} != 0) ? ({p_names[0]} / {p_names[1]}) : 0;\n}}"
                    suggestions.append(f"{prefix_brace}{body1}")
                    suggestions.append(f"{prefix_brace}{body2}")
                else:
                    body = f"{indent}int a = 100;\n{indent}int b = 5;\n{indent}return a / b;\n}}"
                    suggestions.append(f"{prefix_brace}{body}")

            # Operation 5: Modulo / Remainder
            elif "mod" in fn_lower or "rem" in fn_lower:
                if len(p_names) >= 2:
                    suggestions.append(f"{prefix_brace}{indent}return {p_names[0]} % {p_names[1]};\n}}")
                else:
                    suggestions.append(f"{prefix_brace}{indent}int a = 17;\n{indent}int b = 5;\n{indent}return a % b;\n}}")

            # Operation 6: Power / Exponent
            elif "pow" in fn_lower or "power" in fn_lower:
                if len(p_names) >= 2:
                    body1 = f"{indent}int res = 1;\n{indent}for (int i = 0; i < {p_names[1]}; i++) {{\n{indent}    res = res * {p_names[0]};\n{indent}}}\n{indent}return res;\n}}"
                    suggestions.append(f"{prefix_brace}{body1}")
                else:
                    suggestions.append(f"{prefix_brace}{indent}int base = 2;\n{indent}int exp = 3;\n{indent}int res = 1;\n{indent}for (int i = 0; i < exp; i++) res = res * base;\n{indent}return res;\n}}")

            # Operation 7: GCD / HCF (Greatest Common Divisor)
            elif "gcd" in fn_lower or "hcf" in fn_lower:
                if len(p_names) >= 2:
                    body1 = f"{indent}while ({p_names[1]} != 0) {{\n{indent}    int temp = {p_names[1]};\n{indent}    {p_names[1]} = {p_names[0]} % {p_names[1]};\n{indent}    {p_names[0]} = temp;\n{indent}}}\n{indent}return {p_names[0]};\n}}"
                    body2 = f"{indent}if ({p_names[1]} == 0) return {p_names[0]};\n{indent}return gcd({p_names[1]}, {p_names[0]} % {p_names[1]});\n}}"
                    suggestions.append(f"{prefix_brace}{body1}")
                    suggestions.append(f"{prefix_brace}{body2}")
                else:
                    suggestions.append(f"{prefix_brace}{indent}int a = 48, b = 18;\n{indent}while (b != 0) {{\n{indent}    int t = b;\n{indent}    b = a % b;\n{indent}    a = t;\n{indent}}}\n{indent}return a;\n}}")

            # Operation 8: Prime Number Check
            elif "prime" in fn_lower:
                arg = p_names[0] if p_names else "n"
                body = f"{indent}if ({arg} <= 1) return false;\n{indent}for (int i = 2; i * i <= {arg}; i++) {{\n{indent}    if ({arg} % i == 0) return false;\n{indent}}}\n{indent}return true;\n}}"
                suggestions.append(f"{prefix_brace}{body}")

            # Operation 9: Fibonacci
            elif "fib" in fn_lower:
                arg = p_names[0] if p_names else "n"
                body1 = f"{indent}if ({arg} <= 1) return {arg};\n{indent}int a = 0, b = 1, c = 0;\n{indent}for (int i = 2; i <= {arg}; i++) {{\n{indent}    c = a + b;\n{indent}    a = b;\n{indent}    b = c;\n{indent}}}\n{indent}return b;\n}}"
                body2 = f"{indent}if ({arg} <= 1) return {arg};\n{indent}return fib({arg} - 1) + fib({arg} - 2);\n}}"
                suggestions.append(f"{prefix_brace}{body1}")
                suggestions.append(f"{prefix_brace}{body2}")

            # Operation 10: Reverse Number / Digits
            elif "reverse" in fn_lower:
                arg = p_names[0] if p_names else "num"
                body = f"{indent}int rev = 0;\n{indent}int n = {arg};\n{indent}while (n > 0) {{\n{indent}    rev = rev * 10 + (n % 10);\n{indent}    n = n / 10;\n{indent}}}\n{indent}return rev;\n}}"
                suggestions.append(f"{prefix_brace}{body}")

            # Operation 11: Square / Cube
            elif "square" in fn_lower or "sqr" in fn_lower:
                arg = p_names[0] if p_names else "n"
                suggestions.append(f"{prefix_brace}{indent}return {arg} * {arg};\n}}")
            elif "cube" in fn_lower:
                arg = p_names[0] if p_names else "n"
                suggestions.append(f"{prefix_brace}{indent}return {arg} * {arg} * {arg};\n}}")

            # Operation 12: Max / Min
            elif "max" in fn_lower:
                if len(p_names) >= 2:
                    suggestions.append(f"{prefix_brace}{indent}if ({p_names[0]} > {p_names[1]}) return {p_names[0]};\n{indent}return {p_names[1]};\n}}")
                    suggestions.append(f"{prefix_brace}{indent}return ({p_names[0]} > {p_names[1]}) ? {p_names[0]} : {p_names[1]};\n}}")
                else:
                    suggestions.append(f"{prefix_brace}{indent}int a = 15;\n{indent}int b = 25;\n{indent}return (a > b) ? a : b;\n}}")
            elif "min" in fn_lower:
                if len(p_names) >= 2:
                    suggestions.append(f"{prefix_brace}{indent}if ({p_names[0]} < {p_names[1]}) return {p_names[0]};\n{indent}return {p_names[1]};\n}}")
                    suggestions.append(f"{prefix_brace}{indent}return ({p_names[0]} < {p_names[1]}) ? {p_names[0]} : {p_names[1]};\n}}")
                else:
                    suggestions.append(f"{prefix_brace}{indent}int a = 15;\n{indent}int b = 25;\n{indent}return (a < b) ? a : b;\n}}")

            # Operation 13: Average / Mean
            elif "avg" in fn_lower or "average" in fn_lower or "mean" in fn_lower:
                if len(p_names) >= 2:
                    suggestions.append(f"{prefix_brace}{indent}return ({p_names[0]} + {p_names[1]}) / 2;\n}}")
                else:
                    suggestions.append(f"{prefix_brace}{indent}int a = 10, b = 20;\n{indent}return (a + b) / 2;\n}}")

            # Operation 14: Factorial
            elif "fact" in fn_lower or "factorial" in fn_lower:
                n_var = p_names[0] if p_names else "n"
                body1 = f"{indent}int result = 1;\n{indent}for (int i = 1; i <= {n_var}; i++) {{\n{indent}    result = result * i;\n{indent}}}\n{indent}return result;\n}}"
                body2 = f"{indent}if ({n_var} <= 1) return 1;\n{indent}return {n_var} * factorial({n_var} - 1);\n}}"
                suggestions.append(f"{prefix_brace}{body1}")
                suggestions.append(f"{prefix_brace}{body2}")

            # Operation 15: Swap
            elif "swap" in fn_lower:
                suggestions.append(f"{prefix_brace}{indent}int temp = a;\n{indent}a = b;\n{indent}b = temp;\n{indent}return;\n}}")

            # Operation 16: Even / Odd Check
            elif "iseven" in fn_lower or "even" in fn_lower:
                arg = p_names[0] if p_names else "n"
                suggestions.append(f"{prefix_brace}{indent}return ({arg} % 2 == 0);\n}}")
            elif "isodd" in fn_lower or "odd" in fn_lower:
                arg = p_names[0] if p_names else "n"
                suggestions.append(f"{prefix_brace}{indent}return ({arg} % 2 != 0);\n}}")

            # Operation 17: Binary Search
            elif "binarysearch" in fn_lower or "search" in fn_lower:
                suggestions.append(f"{prefix_brace}{indent}int left = 0, right = n - 1;\n{indent}while (left <= right) {{\n{indent}    int mid = left + (right - left) / 2;\n{indent}    if (arr[mid] == target) return mid;\n{indent}    if (arr[mid] < target) left = mid + 1;\n{indent}    else right = mid - 1;\n{indent}}}\n{indent}return -1;\n}}")

            # Default fallbacks based on return type
            elif ret_type == "int":
                suggestions.append(f"{prefix_brace}{indent}int result = 0;\n{indent}return result;\n}}")
                suggestions.append(f"{prefix_brace}{indent}return 0;\n}}")
            elif ret_type == "bool":
                suggestions.append(f"{prefix_brace}{indent}return true;\n}}")
                suggestions.append(f"{prefix_brace}{indent}return false;\n}}")
            elif ret_type == "void":
                suggestions.append(f"{prefix_brace}{indent}cout << \"Executing...\" << endl;\n{indent}return;\n}}")
            else:
                suggestions.append(f"{prefix_brace}{indent}return 0;\n}}")

            return suggestions

        # Case 2: #include completions
        if re.search(r"^\s*#include\s*<?\s*$", trimmed):
            suggestions.append("<iostream>")
            suggestions.append("<vector>")
            suggestions.append("<string>")
            suggestions.append("<cmath>")
            suggestions.append("<algorithm>")
            suggestions.append("<cstdio>")
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
            if var_names:
                suggestions.append(f"{var_names[0]} << endl;")
            suggestions.append('"Result: " << result << endl;')
            suggestions.append('"Hello, World!" << endl;')
            suggestions.append('"Value: " << total << endl;')
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
        rule_suggestions = self.rule_based_autocomplete(prefix, suffix, line, col, symbols, functions)

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
