#!/usr/bin/env bash
echo "========================================================"
echo "  Launching AI-Assisted Smart Compiler Web Application"
echo "========================================================"

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

echo "Starting Python FastAPI Backend..."
(cd "$DIR/backend" && python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload) &
BACKEND_PID=$!

sleep 2

echo "Starting React Frontend..."
(cd "$DIR/frontend" && npm run dev -- --host 127.0.0.1 --port 5173) &
FRONTEND_PID=$!

echo "Both services started (Backend PID $BACKEND_PID, Frontend PID $FRONTEND_PID)."
echo "Visit: http://127.0.0.1:5173"

trap "kill $BACKEND_PID $FRONTEND_PID" EXIT
wait
