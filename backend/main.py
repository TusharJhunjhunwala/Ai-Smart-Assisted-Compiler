import os
import re
import difflib
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from compiler_engine import CompilerAnalyzer
from autofix import AutoFixer, warm_up
from ai_service import ai_service
from models import AnalyzeRequest, AutocompleteRequest, ExplainFixRequest, FixAllRequest, FixDiagnosticRequest
from examples import SAMPLE_PROGRAMS

app = FastAPI(
    title="AI-Assisted Smart Compiler API",
    description="Backend compiler analysis, predictive code completion, and diagnostic explanation engine.",
    version="2.0.0"
)

# Precompile <iostream> in the background so the first Fix All is already fast
warm_up(AutoFixer.find_compiler())

# Enable CORS for React frontend (Vite default port 5173 or other local dev ports)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "ai_configured": bool(ai_service.api_key),
        "ai_provider": ai_service.provider if ai_service.api_key else "offline_rule_engine",
        "supported_languages": ["cpp", "c"]
    }

@app.get("/api/examples")
def get_examples():
    return SAMPLE_PROGRAMS

@app.post("/api/analyze")
def analyze_code(req: AnalyzeRequest):
    """
    Execute lexical analysis, symbol table parsing, semantic/syntax error detection,
    optimization passes, and corrected code generation.
    """
    analyzer = CompilerAnalyzer(source=req.source, language=req.language)
    analyzer.analyze()
    return analyzer.get_results()

@app.post("/api/autocomplete")
def predictive_autocomplete(req: AutocompleteRequest):
    """
    Real-time predictive AI code completion.
    Debounced by frontend and responds with ghost text suggestions.
    """
    # Extract known symbols if not explicitly supplied
    symbols = req.symbols
    functions = req.functions
    if symbols is None:
        quick_analyzer = CompilerAnalyzer(source=req.prefix)
        quick_analyzer.lex()
        quick_analyzer.parse()
        symbols = [
            {"name": name, "type": info["type"], "value": info["value"]}
            for name, info in quick_analyzer.symbols.items()
        ]
        functions = list(quick_analyzer.functions.keys())

    result = ai_service.get_predictive_completion(
        prefix=req.prefix,
        suffix=req.suffix,
        line=req.line,
        col=req.column,
        language=req.language,
        symbols=symbols,
        functions=functions
    )
    return result

@app.post("/api/explain-fix")
def explain_and_fix(req: ExplainFixRequest):
    """
    AI-powered diagnostics explainer and tailored fix generator.
    """
    return ai_service.explain_and_fix(
        diagnostic=req.diagnostic,
        code_context=req.code_context,
        language=req.language
    )

@app.post("/api/fix-all")
def fix_all_errors(req: FixAllRequest):
    """
    Generates proposed corrected version of the program with unified diff.
    """
    analyzer = CompilerAnalyzer(source=req.source, language=req.language)
    analyzer.analyze()
    corrected, fixes = analyzer.corrected_only()

    # Generate unified diff
    orig_lines = req.source.splitlines(keepends=True)
    corr_lines = corrected.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        orig_lines,
        corr_lines,
        fromfile="original.cpp",
        tofile="corrected.cpp"
    ))
    diff_text = "".join(diff)

    # Count the distinct places that were changed
    matcher = difflib.SequenceMatcher(None, req.source.splitlines(), corrected.splitlines())
    changed = sum(1 for tag, *_ in matcher.get_opcodes() if tag != "equal")

    return {
        "original_code": req.source,
        "corrected_code": corrected,
        "diff": diff_text,
        "fixed_count": max(changed, len(fixes)) if corrected != req.source else 0,
        "fixes": fixes,
    }


STRUCTURAL = re.compile(r"^(#\s*include\b.*|using namespace std;|int main\(\) \{|return 0;|\}|\{|)$")


@app.post("/api/fix-diagnostic")
def fix_single_diagnostic(req: FixDiagnosticRequest):
    """
    Apply only the part of the full correction that repairs ONE diagnostic.
    The whole program is corrected first, then only the change at that line is kept.
    """
    analyzer = CompilerAnalyzer(source=req.source, language=req.language)
    analyzer.analyze()
    corrected, fixes = analyzer.corrected_only()
    orig, corr = req.source.splitlines(), corrected.splitlines()
    if orig == corr:
        return {"fixed_code": req.source, "applied": False,
                "message": "Nothing to change automatically for this diagnostic."}

    # Align ignoring indentation, so wrapping code in main() does not count as a change
    matcher = difflib.SequenceMatcher(None, [l.strip() for l in orig], [l.strip() for l in corr], autojunk=False)
    ops = []
    for op in matcher.get_opcodes():
        tag, i1, i2, j1, j2 = op
        if tag == "equal":
            continue
        if tag == "replace" and i2 - i1 == j2 - j1:
            # neighbouring edited lines are separate fixes: one click, one line
            ops.extend(("replace", i1 + k, i1 + k + 1, j1 + k, j1 + k + 1) for k in range(i2 - i1))
        else:
            ops.append(op)
    target = max(0, int(req.diagnostic.get("line", 1)) - 1)
    structural = req.diagnostic.get("source") == "structure" or req.diagnostic.get("level") == "INFO"

    def is_structural(op):
        _, i1, i2, j1, j2 = op
        return all(STRUCTURAL.match(l.strip()) for l in orig[i1:i2] + corr[j1:j2])

    def distance(op):
        _, i1, i2, _, _ = op
        return 0 if i1 <= target < max(i2, i1 + 1) else min(abs(target - i1), abs(target - (i2 - 1)))

    if structural:
        chosen = [op for op in ops if is_structural(op)] or ops
    else:
        exact = [op for op in ops if distance(op) == 0]
        near = exact or [op for op in ops if distance(op) <= 1][:1]
        chosen = near or ([min(ops, key=distance)] if ops and distance(min(ops, key=distance)) <= 4 else [])
    if not chosen:
        return {"fixed_code": req.source, "applied": False,
                "message": "No automatic fix found near this line. Try Fix All Errors."}

    result = list(orig)
    for tag, i1, i2, j1, j2 in sorted(chosen, key=lambda op: op[1], reverse=True):
        replacement = corr[j1:j2]
        if i2 - i1 == j2 - j1:
            # keep the user's own indentation on lines that were edited in place
            replacement = [re.match(r"\s*", o).group(0) + c.lstrip() if o.strip() else c
                           for o, c in zip(orig[i1:i2], replacement)]
        result[i1:i2] = replacement
    fixed = "\n".join(result)
    return {"fixed_code": fixed, "applied": fixed != req.source,
            "message": "Applied the fix." if fixed != req.source else "Nothing to change."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
