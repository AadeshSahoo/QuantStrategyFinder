# Phase 3 scheduler & durable hosting

**Label:** SIMULATED PAPER TRADING — NOT LIVE BROKERAGE

This repository is Origin-hosted (`origin.cursor.com`). Native GitHub Actions will not fire
until the repo is mirrored/connected to GitHub **or** Depot CI is connected for Origin.
Durable state does **not** live on the ephemeral runner disk.

## Chosen free durable store

| Option | Role | Tradeoff |
|---|---|---|
| **Git branch `phase3-ledger` (chosen)** | Authoritative SQLite + CSV/MD exports + run logs | Free forever on any git host; history grows; force-push discouraged |
| GitHub Actions artifacts only | Ephemeral | Expire (≤90 days); **not** sufficient alone |
| Turso / libSQL free tier | Hosted SQLite | Needs account + token secrets; overkill for this slice |
| Depot CI object cache | CI acceleration | Not a substitute for the ledger branch |

**Flow each run:** `restore phase3-ledger` → `qsf phase3 run` (idempotent) → `persist` (commit+push ledger).

## Workflows (schedule + manual)

| Path | Provider |
|---|---|
| `.github/workflows/phase3-paper.yml` | GitHub Actions (free for **public** repos) |
| `.depot/workflows/phase3-paper.yml` | Depot CI on Origin (GHA-compatible; schedules from **default branch**) |

**Cron (UTC):**
- `45 21 * * 1-5` — weekdays after US cash close
- `15 12 * * 0,6` — weekend crypto catch-up

**Concurrency:** `group: phase3-paper-trading`, `cancel-in-progress: false` (no overlapping jobs).  
**Idempotency:** engine `order_key` uniqueness prevents duplicate fills if a run is retried.

## One-shot / local scheduled-run equivalent

```bash
source .venv/bin/activate
bash scripts/phase3_ci_job.sh
```

This is what CI executes: restore → verify frozen config hash → paper job → persist.

## What was verified here vs what you must enable

| Capability | Verified in agent environment | Needs you |
|---|---|---|
| Immutable config hash `774936e6…` (5 candidates) | Yes | — |
| Durable ledger branch `phase3-ledger` restore/persist | Yes (pushed to Origin) | — |
| Idempotent re-run (no duplicate fills) | Yes | — |
| Fresh yfinance ingestion in CI-equivalent job | Yes | — |
| Remote **schedule** actually firing | **No** | Connect GitHub Actions **or** Depot; merge workflow to default branch for cron |

Until the remote schedule row is true, forward testing status is **NOT ACTIVE**
(see `/cursor/stores/self/docs/phase3-activation.md`).
