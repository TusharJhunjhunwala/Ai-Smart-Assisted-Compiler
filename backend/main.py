import os
import difflib
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from compiler_engine import CompilerAnalyzer
from ai_service import ai_service
from models import AnalyzeRequest, AutocompleteRequest, ExplainFixRequest, FixAllRequest
from examples import SAMPLE_PROGRAMS

app = FastAPI(
    title="AI-Assisted Smart Compiler API",
    description="Backend compiler analysis, predictive code completion, and diagnostic explanation engine.",
    version="2.0.0"
)

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
    results = analyzer.get_results()
    corrected = results["corrected_code"]
    
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

    return {
        "original_code": req.source,
        "corrected_code": corrected,
        "diff": diff_text,
        "fixed_count": len(results["diagnostics"])
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
