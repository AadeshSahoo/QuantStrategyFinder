# Phase 3 scheduler & persistent hosting

**Cursor cloud VMs are not continuous hosts.** Forward testing is only “officially active”
when this job runs on a machine you control (VPS, always-on workstation, GitHub Actions
scheduled workflow with secrets, etc.).

## One-shot job (verified in development)

```bash
source .venv/bin/activate
qsf phase3 register
qsf phase3 run
```

SQLite ledger: `data/phase3/paper_trading.sqlite`  
Exports: `reports/phase3/`

## Cron example (Linux persistent host)

```cron
# Every weekday 21:30 UTC after US cash equity close / crypto continuous
30 21 * * 1-5 cd /opt/QuantStrategyFinder && . .venv/bin/activate && qsf phase3 run >> /var/log/qsf-phase3.log 2>&1
```

Or:

```bash
python scripts/phase3_paper_job.py
```

## systemd timer sketch

`/etc/systemd/system/qsf-phase3.service` + `.timer` calling the same command daily.

## What was verified here vs what you must host

| Capability | Verified in this agent environment | Needs your persistent host |
|---|---|---|
| Config registration + config hash | Yes | — |
| Idempotent paper job + SQLite persistence | Yes | — |
| CSV/MD exports | Yes | — |
| Continuous/scheduled ingestion | **No** (VM not continuous) | Yes |
| Multi-week forward sample | **No** yet (forward_start=2026-10-22; few/new bars) | Accrues over time on host |

Do **not** claim continuous forward testing is active until the scheduler row above is true.
