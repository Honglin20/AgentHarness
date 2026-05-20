#!/bin/bash
# Start AgentHarness — backend serves both API and UI
# Usage: bash examples/launch_ui.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Build frontend if needed
if [ ! -d "$ROOT/frontend/out" ]; then
  echo "=== Frontend not built — checking prerequisites ==="

  if ! command -v node &>/dev/null; then
    echo ""
    echo "ERROR: Node.js is not installed."
    echo "  Install it from: https://nodejs.org/ (LTS recommended)"
    echo "  Or: brew install node   /  apt install nodejs npm"
    exit 1
  fi

  if ! command -v npm &>/dev/null; then
    echo ""
    echo "ERROR: npm is not installed (should come with Node.js)."
    exit 1
  fi

  if [ ! -d "$ROOT/frontend/node_modules" ]; then
    echo "=== Installing frontend dependencies ==="
    cd "$ROOT/frontend" && npm install
  fi

  echo "=== Building frontend ==="
  cd "$ROOT/frontend" && npm run build
fi

echo "=== Starting AgentHarness (http://localhost:8000) ==="
cd "$ROOT"
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
