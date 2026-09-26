#!/usr/bin/env bash
# Copy the skill without evals/ and tests/ (so agents under test cannot read expected answers)
# and pre-build its environment. Usage: evals/make_test_copy.sh /tmp/skill-under-test
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:?destination directory}/wiki-interest-research"
rm -rf "$DEST" && mkdir -p "$DEST"
rsync -a --exclude evals --exclude tests --exclude .venv --exclude __pycache__ --exclude .pytest_cache \
  --exclude pytest.ini "$SRC/" "$DEST/"
"$DEST/scripts/wpv" --help >/dev/null
echo "$DEST"
