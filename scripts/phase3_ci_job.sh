#!/usr/bin/env bash
# Scheduled-run equivalent for Phase 3 paper trading (SIMULATED).
# Used by GitHub Actions / Depot CI and for local verification.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p reports/phase3 data/phase3
RUN_LOG="${PHASE3_RUN_LOG:-$ROOT/reports/phase3/last_ci_run.json}"
export PHASE3_RUN_LOG="$RUN_LOG"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

log "=== Phase 3 CI job start (SIMULATED — not live trading) ==="

bash "$ROOT/scripts/phase3_ledger.sh" restore
bash "$ROOT/scripts/phase3_ledger.sh" verify-hash

# Prefer already-active venv pip; fall back to ensurepip / get-pip on bare runners.
if command -v pip >/dev/null 2>&1; then
  pip install -q -U pip
  pip install -q -e .
elif python3 -m pip --version >/dev/null 2>&1; then
  python3 -m pip install -q -U pip
  python3 -m pip install -q -e .
else
  python3 -m ensurepip --upgrade || true
  python3 -m pip install -q -U pip
  python3 -m pip install -q -e .
fi
# Ensure package importable even if editable install is quirky
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

log "Running paper job (register if needed + process new sessions)"
set +e
# Keep logging on stderr so stdout stays JSON-parseable for the run log
python3 "$ROOT/scripts/phase3_paper_job.py" \
  >"$ROOT/reports/phase3/last_job_stdout.txt" \
  2>"$ROOT/reports/phase3/last_job_stderr.txt"
rc=$?
set -e
if [[ -f "$ROOT/reports/phase3/last_job_stderr.txt" ]]; then
  cat "$ROOT/reports/phase3/last_job_stderr.txt" >&2 || true
fi
export ROOT PHASE3_EXIT_CODE="$rc"

# Build structured run log (extract last JSON object from job stdout)
python3 - <<'PY'
import json, hashlib, re, os
from pathlib import Path
from datetime import datetime, timezone

root = Path(os.environ.get("ROOT", "."))
cfg = (root / "configs/phase3-forward-trading-config.yaml").read_bytes()
cfg_hash = hashlib.sha256(cfg).hexdigest()
expected = "774936e63dedec57f05aac1831aee23f3e3ddcdc634ef9ff4c9b1d6b58f3fd8f"
stdout_path = root / "reports/phase3/last_job_stdout.txt"
stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
detail = {}
# Prefer brace-matching from the last top-level '{'
for m in re.finditer(r"\{", stdout):
    chunk = stdout[m.start() :]
    try:
        detail = json.loads(chunk)
    except json.JSONDecodeError:
        continue
run_log = Path(os.environ["PHASE3_RUN_LOG"])
rc = int(os.environ["PHASE3_EXIT_CODE"])
payload = {
    "label": "SIMULATED_PAPER_TRADING_NOT_LIVE",
    "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    "exit_code": rc,
    "config_hash": cfg_hash,
    "expected_config_hash": expected,
    "config_hash_ok": cfg_hash == expected,
    "job_detail": detail,
    "ingestion_ok": rc == 0,
    "warnings": detail.get("warnings") if isinstance(detail, dict) else [],
    "job_id": detail.get("job_id") if isinstance(detail, dict) else None,
}
run_log.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
print(json.dumps({"run_log": str(run_log), "exit_code": rc, "config_hash_ok": payload["config_hash_ok"]}, indent=2))
PY

if [[ "$rc" -ne 0 ]]; then
  log "FAILURE: paper job exit=$rc — still attempting ledger persist of prior state if DB exists"
  if [[ -f data/phase3/paper_trading.sqlite ]]; then
    bash "$ROOT/scripts/phase3_ledger.sh" persist || true
  fi
  exit "$rc"
fi

bash "$ROOT/scripts/phase3_ledger.sh" verify-hash
bash "$ROOT/scripts/phase3_ledger.sh" persist
log "=== Phase 3 CI job success ==="
exit 0
