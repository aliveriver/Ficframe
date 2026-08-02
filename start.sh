#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

HOST="${FICFRAME_HOST:-127.0.0.1}"
PORT="${FICFRAME_PORT:-8787}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

if [[ ! -f ".env" && -f ".env.example" ]]; then
  cp ".env.example" ".env"
  echo "[FicFrame] Created .env from .env.example."
fi

open_browser() {
  local url="http://${HOST}:${PORT}"
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 || true
  fi
}

if command -v uv >/dev/null 2>&1; then
  echo "[FicFrame] uv found. Using uv environment."
  export UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"
  uv sync
  echo "[FicFrame] Opening http://${HOST}:${PORT}"
  open_browser
  echo "[FicFrame] Starting server with uv. Press Ctrl+C to stop."
  exec uv run ficframe serve --host "$HOST" --port "$PORT"
fi

echo "[FicFrame] uv was not found. Falling back to Python venv + pip."
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "[FicFrame] Python 3.10+ was not found."
    echo "Please install Python first."
    exit 1
  fi
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "[FicFrame] Creating virtual environment..."
  "$PYTHON_BIN" -m venv .venv
fi

echo "[FicFrame] Installing or checking dependencies with pip..."
".venv/bin/python" -m pip install -U pip -i "$PIP_INDEX_URL"
".venv/bin/python" -m pip install -r requirements.txt -i "$PIP_INDEX_URL"

echo "[FicFrame] Opening http://${HOST}:${PORT}"
open_browser

echo "[FicFrame] Starting server with Python venv. Press Ctrl+C to stop."
exec ".venv/bin/python" -m ficframe.cli serve --host "$HOST" --port "$PORT"
