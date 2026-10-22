#!/usr/bin/env bash
# Run on a machine with GitHub auth (gh auth login OR GH_TOKEN with repo+workflow).
# Pushes Phase 3 branches and dispatches the paper-trading workflow. SIMULATED only.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
REPO="${PHASE3_GITHUB_REPO:-AadeshSahoo/QuantStrategyFinder}"
EXPECTED=774936e63dedec57f05aac1831aee23f3e3ddcdc634ef9ff4c9b1d6b58f3fd8f

actual="$(python3 - <<'PY'
from pathlib import Path
import hashlib
print(hashlib.sha256(Path("configs/phase3-forward-trading-config.yaml").read_bytes()).hexdigest())
PY
)"
[[ "$actual" == "$EXPECTED" ]] || { echo "Config hash drift: $actual"; exit 2; }

if ! git remote get-url github >/dev/null 2>&1; then
  git remote add github "https://github.com/${REPO}.git"
else
  git remote set-url github "https://github.com/${REPO}.git"
fi

echo "Pushing feature branch..."
git push -u github cursor/phase3-forward-paper-trading-96e7
echo "Pushing phase3-ledger..."
git push -u github phase3-ledger
echo "Pushing main (no force)..."
git push github origin/main:main || echo "WARN: main push failed — merge PR #4 on Origin first or push main manually"

if command -v gh >/dev/null 2>&1; then
  gh auth status
  # Prefer Actions write permission in repo settings
  gh workflow run phase3-paper.yml --repo "$REPO" --ref cursor/phase3-forward-paper-trading-96e7 \
    -f reason="activation verification" || \
  gh workflow run "Phase 3 paper trading (SIMULATED)" --repo "$REPO" --ref cursor/phase3-forward-paper-trading-96e7 \
    -f reason="activation verification"
  echo "Waiting for run..."
  sleep 8
  gh run list --repo "$REPO" --workflow phase3-paper.yml --limit 3
  echo "After green run: git fetch github phase3-ledger && git log github/phase3-ledger -1"
else
  echo "gh not installed — trigger workflow_dispatch in the GitHub Actions UI"
fi
