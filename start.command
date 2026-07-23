#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$script_dir"

if [ -x "$script_dir/.venv/bin/moth" ]; then
    exec "$script_dir/.venv/bin/moth" serve --open-browser
fi

if command -v moth >/dev/null 2>&1; then
    exec moth serve --open-browser
fi

printf '%s\n' \
    "Moth is not installed. Install the project environment or put moth on PATH." \
    >&2
exit 1
