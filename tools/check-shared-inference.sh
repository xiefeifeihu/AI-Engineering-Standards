#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}

exec "$PYTHON_BIN" "$SCRIPT_DIR/check-shared-inference.py" "$@"
