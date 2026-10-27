#!/usr/bin/env bash
# Everything CI checks; .github/workflows/ci.yml runs this on every push and pull request.
# Run it before pushing to see what CI will:
#
#   deploy/ci/check.sh
#
# Uses .venv/bin/python if there is one, else python (override with PYTHON=...).
set -euo pipefail
cd "$(dirname "$0")/../.."

if [[ -z "${PYTHON:-}" ]]; then
    if [[ -x .venv/bin/python ]]; then PYTHON=.venv/bin/python; else PYTHON=python; fi
fi

# private notes and the built site must never reach the public repo
echo "== private folders stay out of git"
for dir in docs/private deploy/site; do
    if ! git check-ignore -q "$dir/x"; then
        echo "$dir/ is not git-ignored"; exit 1
    fi
    tracked=$(git ls-files -- "$dir")
    if [[ -n "$tracked" ]]; then
        echo "tracked under $dir/ (remove with git rm --cached):"; echo "$tracked"; exit 1
    fi
done

echo "== lint"
"$PYTHON" -m ruff check .

echo "== tests"
"$PYTHON" -m pytest -q
