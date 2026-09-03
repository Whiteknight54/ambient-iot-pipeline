#!/usr/bin/env bash
# Creates a virtual environment and installs dependencies.
# Usage: scripts/bootstrap.sh [python-interpreter]
set -euo pipefail

PYTHON="${1:-python3}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="$REPO_ROOT/.venv"
VENV_PYTHON="$VENV_PATH/bin/python"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "No usable Python interpreter found at '$PYTHON'. Install Python 3.10+ or pass a path as the first argument." >&2
    exit 1
fi

VERSION_OK=$("$PYTHON" -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')
if [ "$VERSION_OK" != "1" ]; then
    echo "Python 3.10+ required; '$PYTHON' is $("$PYTHON" -c 'import sys; print(sys.version.split()[0])')." >&2
    exit 1
fi

echo "Using interpreter: $("$PYTHON" -c 'import sys; print(sys.executable)')"

if [ ! -x "$VENV_PYTHON" ]; then
    "$PYTHON" -m venv "$VENV_PATH"
fi

"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt"

echo "Environment ready at $VENV_PATH"
echo "Activate it with: source $VENV_PATH/bin/activate"
