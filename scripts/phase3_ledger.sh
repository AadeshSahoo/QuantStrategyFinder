#!/usr/bin/env bash
# Restore / persist Phase 3 SQLite ledger via durable git branch `phase3-ledger`.
# SIMULATED paper trading only — not live brokerage.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LEDGER_BRANCH="${PHASE3_LEDGER_BRANCH:-phase3-ledger}"
LEDGER_DIR="${PHASE3_LEDGER_DIR:-$ROOT/.phase3-ledger}"
DB_PATH="$ROOT/data/phase3/paper_trading.sqlite"
SNAP_PATH="$ROOT/data/phase3/registered_config_snapshot.yaml"
EXPORTS_DIR="$ROOT/reports/phase3"
EXPECTED_HASH="${PHASE3_EXPECTED_CONFIG_HASH:-774936e63dedec57f05aac1831aee23f3e3ddcdc634ef9ff4c9b1d6b58f3fd8f}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

cmd="${1:-}"
case "$cmd" in
  restore)
    log "RESTORE ledger from origin/$LEDGER_BRANCH"
    rm -rf "$LEDGER_DIR"
    mkdir -p "$ROOT/data/phase3" "$EXPORTS_DIR"
    if git ls-remote --exit-code --heads origin "$LEDGER_BRANCH" >/dev/null 2>&1; then
      git fetch origin "$LEDGER_BRANCH":"refs/remotes/origin/$LEDGER_BRANCH"
      git worktree remove --force "$LEDGER_DIR" 2>/dev/null || true
      rm -rf "$LEDGER_DIR"
      git worktree add --detach "$LEDGER_DIR" "origin/$LEDGER_BRANCH"
      if [[ -f "$LEDGER_DIR/paper_trading.sqlite" ]]; then
        cp -f "$LEDGER_DIR/paper_trading.sqlite" "$DB_PATH"
        log "Restored SQLite ($(wc -c <"$DB_PATH") bytes)"
      else
        log "WARNING: ledger branch has no paper_trading.sqlite — fresh DB will be created on register"
      fi
      if [[ -f "$LEDGER_DIR/registered_config_snapshot.yaml" ]]; then
        cp -f "$LEDGER_DIR/registered_config_snapshot.yaml" "$SNAP_PATH"
      fi
      if [[ -d "$LEDGER_DIR/exports" ]]; then
        cp -f "$LEDGER_DIR"/exports/* "$EXPORTS_DIR/" 2>/dev/null || true
      fi
    else
      log "No remote ledger branch yet — starting empty (first run)"
    fi
    ;;

  verify-hash)
    log "VERIFY frozen config hash == $EXPECTED_HASH"
    actual="$(python3 - <<'PY'
from pathlib import Path
import hashlib
print(hashlib.sha256(Path("configs/phase3-forward-trading-config.yaml").read_bytes()).hexdigest())
PY
)"
    if [[ "$actual" != "$EXPECTED_HASH" ]]; then
      log "ERROR: config hash drift: actual=$actual expected=$EXPECTED_HASH"
      exit 2
    fi
    if [[ -f "$DB_PATH" ]]; then
      db_hash="$(sqlite3 "$DB_PATH" 'SELECT config_hash FROM registration WHERE id=1;' 2>/dev/null || true)"
      if [[ -n "$db_hash" && "$db_hash" != "$EXPECTED_HASH" ]]; then
        log "ERROR: registered DB hash drift: db=$db_hash expected=$EXPECTED_HASH"
        exit 3
      fi
      log "OK config + registration hash match ($actual)"
    else
      log "OK config file hash match ($actual); DB not present yet"
    fi
    ;;

  persist)
    log "PERSIST ledger to origin/$LEDGER_BRANCH"
    if [[ ! -f "$DB_PATH" ]]; then
      log "ERROR: missing $DB_PATH — nothing to persist"
      exit 4
    fi
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    git worktree remove --force "$LEDGER_DIR" 2>/dev/null || true
    rm -rf "$LEDGER_DIR"
    if git ls-remote --exit-code --heads origin "$LEDGER_BRANCH" >/dev/null 2>&1; then
      git fetch origin "$LEDGER_BRANCH":"refs/remotes/origin/$LEDGER_BRANCH"
      git worktree add "$LEDGER_DIR" -B "$LEDGER_BRANCH" "origin/$LEDGER_BRANCH"
    else
      mkdir -p "$LEDGER_DIR"
      git worktree add --detach "$LEDGER_DIR" HEAD
      (
        cd "$LEDGER_DIR"
        git checkout --orphan "$LEDGER_BRANCH"
        git rm -rf . >/dev/null 2>&1 || true
      )
    fi
    mkdir -p "$LEDGER_DIR/exports" "$LEDGER_DIR/runs"
    cp -f "$DB_PATH" "$LEDGER_DIR/paper_trading.sqlite"
    [[ -f "$SNAP_PATH" ]] && cp -f "$SNAP_PATH" "$LEDGER_DIR/registered_config_snapshot.yaml"
    if [[ -d "$EXPORTS_DIR" ]]; then
      cp -f "$EXPORTS_DIR"/*.csv "$LEDGER_DIR/exports/" 2>/dev/null || true
      cp -f "$EXPORTS_DIR"/*.md "$LEDGER_DIR/exports/" 2>/dev/null || true
      cp -f "$EXPORTS_DIR"/*.json "$LEDGER_DIR/exports/" 2>/dev/null || true
    fi
    if [[ -f "${PHASE3_RUN_LOG:-}" ]]; then
      cp -f "$PHASE3_RUN_LOG" "$LEDGER_DIR/runs/${stamp}.json"
    fi
    cat >"$LEDGER_DIR/README.md" <<EOF
# Phase 3 durable paper-trading ledger (SIMULATED)

**Not live brokerage.** Authoritative SQLite for automated forward tests.

- Branch: \`$LEDGER_BRANCH\`
- Frozen config hash: \`$EXPECTED_HASH\`
- Last persist (UTC): \`$stamp\`

Do not edit strategy parameters here. Rebuild from \`configs/phase3-forward-trading-config.yaml\` only via \`qsf phase3 register\` on an empty DB.
EOF
    (
      cd "$LEDGER_DIR"
      git config user.name "${GIT_AUTHOR_NAME:-qsf-phase3-bot}"
      git config user.email "${GIT_AUTHOR_EMAIL:-phase3-bot@users.noreply.origin.cursor.com}"
      git add -f README.md paper_trading.sqlite registered_config_snapshot.yaml exports runs 2>/dev/null || true
      if git diff --cached --quiet; then
        log "No ledger changes to commit"
      else
        git commit -m "phase3-ledger: persist simulated paper state @ ${stamp}"
        git push -u origin "HEAD:refs/heads/$LEDGER_BRANCH"
        log "Pushed ledger commit $(git rev-parse --short HEAD)"
      fi
    )
    git worktree remove --force "$LEDGER_DIR" 2>/dev/null || true
    rm -rf "$LEDGER_DIR"
    ;;

  *)
    echo "Usage: $0 {restore|verify-hash|persist}" >&2
    exit 1
    ;;
esac
