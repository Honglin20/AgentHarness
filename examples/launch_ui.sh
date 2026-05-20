#!/bin/bash
# Start AgentHarness — backend serves both API and UI
# Usage: bash examples/launch_ui.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Build frontend if needed
if [ ! -d "$ROOT/frontend/out" ]; then
  echo "=== Building frontend ==="
  cd "$ROOT/frontend" && npm run build
fi

echo "=== Starting AgentHarness (http://localhost:8000) ==="
cd "$ROOT"
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
