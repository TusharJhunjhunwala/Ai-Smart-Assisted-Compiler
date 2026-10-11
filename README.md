# AI-Assisted Smart Compiler Web Application

A modern, responsive, developer-focused web application transforming the desktop compiler into a full-featured intelligent IDE with predictive AI ghost-text completions, AST optimizations, lexical analysis, symbol table inspection, diagnostic explainers, and non-destructive error resolution.

---

## 🌟 Key Features

1. **Predictive AI Code Completion (Ghost Text)**
   - Anticipates what you are writing next in real-time (e.g. typing `void add() {` suggests the entire function body).
   - Incomplete assignments (`int sum =`) suggest expressions based on in-scope variables.
   - Loop & conditional constructs (`for (`, `if (`, `while (`) suggest appropriate headers.
   - Streamlined UX: Press **Tab** to accept ghost suggestions, **Esc** to dismiss, and **Alt + ]** to cycle through alternative suggestions.
   - Powered by a hybrid engine: works **instantly offline** via AST heuristics and scales into LLM completions (Gemini / OpenAI) when an API key is provided.
   - Debounced requests with stale request cancellation.

2. **Full Compiler Analysis Suite (Preserved & Enhanced)**
   - **Lexical Analysis**: Live token stream with line numbers, columns, token types (`KEYWORD`, `IDENTIFIER`, `OPERATOR`, `DELIMITER`, `LITERAL`), and lexemes.
   - **Symbol Table**: Tracks identifier names, resolved types, current values, and declaration lines.
   - **Syntax & Semantic Diagnostics**: Inline Monaco editor squiggly markers, missing semicolon detectors, duplicate declarations, and undeclared identifier catches with Levenshtein-distance typo corrections.
   - **Intermediate Optimizations**: Constant folding, constant propagation, algebraic simplifications, strength reduction, common subexpression detection, and copy propagation.
   - **Compilation Summary**: Clear statistics on tokens, symbols, errors, warnings, and optimization passes.

3. **AI-Powered Diagnostic Explanations & Error Fixing**
   - Click **Explain** on any diagnostic to receive a clear root-cause analysis and an actionable fix snippet.
   - Non-destructive **Fix All Errors**: generates a full unified diff and split-screen comparison to preview before applying changes.

4. **Modern Developer Dashboard UI**
   - Built with **React 19**, **TypeScript**, **Tailwind CSS**, and **Monaco Editor**.
   - Dark mode developer aesthetic with subtle borders and syntax themes.
   - Live status bar tracking cursor position (Ln, Col), line count, diagnostic counters, and engine connectivity.

---

## 📁 Project Architecture

```
normal_project/
├── backend/                  # Python FastAPI Backend
│   ├── compiler_engine.py    # Core compiler analyzer (lexing, parsing, optimizations)
│   ├── ai_service.py         # Hybrid predictive AI and rule-based autocompletion
│   ├── models.py             # Pydantic request/response schemas
│   ├── examples.py           # Preloaded interactive demo programs
│   ├── main.py               # REST API endpoints & CORS middleware
│   └── requirements.txt      # Backend Python dependencies
├── frontend/                 # React + TypeScript + Tailwind CSS Frontend
│   ├── src/
│   │   ├── components/
│   │   │   ├── CodeEditor.tsx        # Monaco Editor + Ghost-Text overlay
│   │   │   ├── Navbar.tsx            # Controls, Language selector, Demos
│   │   │   ├── OutputPanel.tsx       # Tabs for Tokens, Symbols, Optimizations, etc.
│   │   │   ├── AIAssistantPanel.tsx  # Side panel for diagnostic deep dives
│   │   │   ├── DiffPreviewModal.tsx   # Side-by-side diff preview for Fix All
│   │   │   └── StatusBar.tsx         # Cursor position, line counter & status
│   │   ├── api.ts            # Frontend HTTP client
│   │   ├── types.ts          # Shared TypeScript models
│   │   ├── App.tsx           # IDE Root component
│   │   └── index.css         # Styling & custom scrollbars
│   ├── vite.config.ts        # Vite configuration & backend proxy
│   └── package.json          # Frontend packages
├── run_web_windows.bat       # 1-click Windows runner
├── run_web_mac_linux.sh      # 1-click Unix runner
├── .env.example              # Environment variables template
└── README.md
```

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.10+ (tested with Python 3.12)
- Node.js 18+ (tested with Node 24)

### 1. Backend Setup
In a terminal, navigate to the `backend` folder:
```bash
cd backend
py -m pip install -r requirements.txt
py -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```
The backend API is now running at `http://127.0.0.1:8000`. Test health at `http://127.0.0.1:8000/api/health`.

### 2. Frontend Setup
In another terminal, navigate to the `frontend` folder:
```bash
cd frontend
npm install
npm run dev
```
Open `http://127.0.0.1:5173` in your browser.

---

## 💻 1-Click Launchers

- **Windows**: Double-click [`run_web_windows.bat`](file:///c:/Users/tusha/OneDrive/Pictures/Screenshots/normal_project/run_web_windows.bat).
- **macOS / Linux**: Run `./run_web_mac_linux.sh`.

---

## 🔑 AI Configuration (Optional)

The application includes an **Offline Heuristic Engine** that immediately predicts function signatures, loops, variable assignments, and completions without needing any cloud API key or internet access.

To enable full LLM predictive capabilities:
1. Copy `.env.example` to `.env` in the root or `backend/` directory:
   ```bash
   cp .env.example backend/.env
   ```
2. Insert your Google Gemini or OpenAI API key:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   # or
   # OPENAI_API_KEY=your_openai_api_key_here
   ```
3. Restart the backend. The Status Bar and Navbar will automatically reflect `Cloud LLM (gemini)` status.

---

## 🧪 Verification & Scenarios Tested

1. **Typing `void add() {`**: Immediate ghost text completion suggests:
   ```cpp
       int a = 10;
       int b = 20;
       return;
   }
   ```
2. **Tab / Esc Shortcuts**: Pressing `Tab` accepts the suggestion directly into the editor; pressing `Esc` dismisses it.
3. **Undeclared Typo Detection**: Code with `totl = total + 20;` identifies `totl` and suggests `total` via Levenshtein matching.
4. **Fix All & Diff Modal**: Clicking **Fix All Errors** opens the non-destructive side-by-side comparison with syntax corrections and semicolon fixes.
5. **Optimization passes**: Constant folding (`10 + 20 -> 30`), strength reduction (`z * 2 -> z + z`), and common subexpression detection are recorded in the Optimization tab.
