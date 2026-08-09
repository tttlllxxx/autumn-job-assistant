#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -x .venv/bin/python ]]; then
  echo "缺少 .venv。请先按 README 的“首次本机安装”创建 Python 3.12 环境。" >&2
  exit 2
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "缺少 npm。请先安装 Node.js 22 或更高版本。" >&2
  exit 2
fi
if [[ ! -d frontend/node_modules ]]; then
  npm --prefix frontend ci --no-audit --no-fund
fi

npm --prefix frontend run build
.venv/bin/alembic upgrade head

APP_PORT_VALUE="${APP_PORT:-8000}"
exec .venv/bin/python -m uvicorn app.main:app \
  --app-dir backend \
  --host 127.0.0.1 \
  --port "$APP_PORT_VALUE" \
  --workers 1
