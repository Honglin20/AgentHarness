#!/bin/bash
# Launch the full AgentHarness UI — backend + frontend
# Usage: bash examples/launch_ui.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Starting Backend (port 8001) ==="
cd "$ROOT"
python -m uvicorn server.app:app --host 0.0.0.0 --port 8001 &
BACKEND_PID=$!

echo "=== Starting Frontend (port 3000) ==="
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "  Backend:  http://localhost:8001"
echo "  Frontend: http://localhost:3000"
echo "  API Docs: http://localhost:8001/docs"
echo ""
echo "Press Ctrl+C to stop both servers."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
