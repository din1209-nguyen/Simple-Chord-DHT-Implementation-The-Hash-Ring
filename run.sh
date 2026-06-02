#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

find_python() {
    for candidate in python3.12 python3.11 python3.10 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
                printf '%s\n' "$candidate"
                return 0
            fi
        fi
    done

    printf '%s\n' "Python 3.10+ was not found. Install Python 3.10 or newer first." >&2
    return 1
}

venv_ok() {
    [ -x ".venv/bin/python" ] || return 1
    .venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1 || return 1
    .venv/bin/python -m pip --version >/dev/null 2>&1 || return 1
}

if ! venv_ok; then
    if [ -e ".venv" ]; then
        printf '%s\n' "Removing unusable .venv ..."
        rm -rf .venv
    fi

    PYTHON="$(find_python)"
    printf '%s\n' "Creating virtual environment in .venv ..."
    "$PYTHON" -m venv .venv
fi

printf '%s\n' "Installing project dependencies ..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5000}"
export HOST PORT

printf '%s\n' "Starting Simple Chord DHT at http://$HOST:$PORT"
.venv/bin/python app.py
