@echo off
echo ========================================================
echo   Launching AI-Assisted Smart Compiler Web Application
echo ========================================================

echo Starting Python FastAPI Backend on http://127.0.0.1:8000 ...
start "Smart Compiler Backend" cmd /k "cd /d %~dp0backend && py -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload"

timeout /t 2 >nul

echo Starting React + Vite Frontend on http://127.0.0.1:5173 ...
start "Smart Compiler Frontend" cmd /k "cd /d %~dp0frontend && npm run dev -- --host 127.0.0.1 --port 5173"

timeout /t 2 >nul

echo Opening Browser...
start http://127.0.0.1:5173

echo Done! Leave the console windows open while using the application.
