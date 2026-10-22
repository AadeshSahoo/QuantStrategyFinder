# Origin → GitHub transfer (QuantStrategyFinder)

**Target (exact):** https://github.com/AadeshSahoo/QuantStrategyFinder.git  
**Source of truth today:** Origin (`origin.cursor.com` QuantStrategyFinder)  
**Goal:** Mirror existing Phase 1–3 work into the empty public GitHub repo **without recreating the project** and without losing history.

**Frozen config hash (must not change):**  
`774936e63dedec57f05aac1831aee23f3e3ddcdc634ef9ff4c9b1d6b58f3fd8f`

The Cloud Agent **cannot** push for you: this VM has no GitHub login (`GH_TOKEN` unset, SSH publickey denied). Run the steps below on your laptop (or any machine where `gh auth login` / a PAT works).

---

## 0. Prerequisites

1. Repo https://github.com/AadeshSahoo/QuantStrategyFinder is **public** and empty (or only has a README you are willing to replace via normal first push — do **not** force-push over real history later).
2. Local git has the Origin clone with branches:
   - `main`
   - `cursor/phase3-forward-paper-trading-96e7`
   - `phase3-ledger`
3. Auth: `gh auth login` **or** `export GH_TOKEN=...` with write access:
   - **Classic PAT:** scopes `repo` + `workflow`
   - **Fine-grained PAT:** repository `AadeshSahoo/QuantStrategyFinder` with **Contents: Read and write** and **Workflows: Read and write** (Metadata read-only).  
     A token that can `gh api user` but returns **403** on `git push` / Contents API is missing Contents write — recreate the token.

Verify hash before pushing:

```bash
python3 - <<'PY'
from pathlib import Path
import hashlib
h = hashlib.sha256(Path("configs/phase3-forward-trading-config.yaml").read_bytes()).hexdigest()
assert h == "774936e63dedec57f05aac1831aee23f3e3ddcdc634ef9ff4c9b1d6b58f3fd8f", h
print("OK", h)
PY
```

---

## 1. Remotes (do not replace Origin)

```bash
cd /path/to/QuantStrategyFinder   # existing project clone — not a new empty git init

# Keep Origin as origin
git remote -v

# Point github at the exact URL (create or update)
git remote remove github 2>/dev/null || true
git remote add github https://github.com/AadeshSahoo/QuantStrategyFinder.git
# or: git remote set-url github https://github.com/AadeshSahoo/QuantStrategyFinder.git

git fetch origin
git fetch origin main phase3-ledger cursor/phase3-forward-paper-trading-96e7
```

**Do not** `git init` a new unrelated repo. **Do not** delete Origin remotes.

---

## 2. Push order (non-destructive)

Push **feature branch first** (full P1–P3 history on that line), then **main**, then **ledger**. No `--force` unless GitHub rejects a non-fast-forward on an empty repo for an unexpected reason — and never force-overwrite a branch that already has commits you care about.

```bash
# 1) Phase 3 feature branch (includes Phase 1–3 commits on this line of history)
git push -u github cursor/phase3-forward-paper-trading-96e7

# 2) main from Origin — all prior merged work; do NOT force
git push github origin/main:main

# 3) Durable SQLite ledger branch
git push -u github phase3-ledger
```

One-shot helper (same remotes/order), if present on the Phase 3 branch:

```bash
export PHASE3_GITHUB_REPO=AadeshSahoo/QuantStrategyFinder
bash scripts/phase3_github_activate.sh
```

### If `main` push is rejected

- If GitHub created a default commit (README/license) on `main`, either:
  - **Preferred:** pull with allow-unrelated and merge, then push normally, **or**
  - Delete the README-only commit on GitHub UI and push again **without** `--force` if the remote `main` becomes empty, **or**
  - Only as last resort on an **empty-history** remote: `git push github origin/main:main` after removing the README commit — still avoid `--force` onto history that contains real work.
- Never replace your Origin `main` with an empty GitHub tree.

### How to avoid losing work

| Don’t | Do |
|---|---|
| `git init` a new project and copy files | Push existing branches from the Origin clone |
| `git push --force` to `main` / `phase3-ledger` | Fast-forward / normal pushes only |
| Change `configs/phase3-forward-trading-config.yaml` to “fix” CI | Keep hash `774936e6…` |
| Delete Origin remote | Keep `origin` + add `github` |
| Recreate strategies | Reuse frozen shortlist on `phase3-ledger` |

---

## 3. Actions read/write (required for ledger persist)

1. Open https://github.com/AadeshSahoo/QuantStrategyFinder/settings/actions  
2. **Workflow permissions** → **Read and write permissions**  
3. Check **Allow GitHub Actions to create and approve pull requests** (optional)  
4. **Save**

Without write permission, the paper job can run but **cannot** push updates to `phase3-ledger`.

---

## 4. `workflow_dispatch` (verify scheduling path)

After the Phase 3 branch (or `main`) contains `.github/workflows/phase3-paper.yml`:

```bash
gh workflow run phase3-paper.yml \
  --repo AadeshSahoo/QuantStrategyFinder \
  --ref cursor/phase3-forward-paper-trading-96e7 \
  -f reason="activation verification"

gh run list --repo AadeshSahoo/QuantStrategyFinder --workflow phase3-paper.yml --limit 5
gh run watch --repo AadeshSahoo/QuantStrategyFinder   # optional
```

Or UI: **Actions → Phase 3 paper trading (SIMULATED) → Run workflow** (select the Phase 3 branch).

---

## 5. Confirm success (then ACTIVE)

```bash
git fetch github phase3-ledger
git log github/phase3-ledger -3 --oneline

# Inspect latest run log on the ledger branch
git show github/phase3-ledger:runs/   # list
# Pick newest runs/*.json — need:
#   "ingestion_ok": true
#   "config_hash_ok": true
#   "config_hash": "774936e63dedec57f05aac1831aee23f3e3ddcdc634ef9ff4c9b1d6b58f3fd8f"
```

Also confirm the Actions run is **green**.

Optional: merge Origin PR #4 into Origin `main`, then `git push github origin/main:main` so **cron** schedules fire from GitHub `main` (schedules only run from the default branch).

---

## 6. What the agent already prepared on Origin

- Branch `cursor/phase3-forward-paper-trading-96e7` with Phase 3 engine + workflows  
- Branch `phase3-ledger` with SQLite + exports  
- Helper: `scripts/phase3_github_activate.sh`  
- Status doc: `/cursor/stores/self/docs/phase3-activation.md`
