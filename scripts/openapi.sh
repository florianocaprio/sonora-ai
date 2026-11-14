#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="${SONORA_PYTHON:-.venv/bin/python}"
"$python" -c 'import json; from services.api.app import app; print(json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=True))'
