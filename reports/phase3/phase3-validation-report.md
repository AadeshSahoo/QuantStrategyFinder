# Phase 3 Forward Validation Report

**Label:** SIMULATED PAPER TRADING — NOT LIVE BROKERAGE

- Config hash: `774936e63dedec57f05aac1831aee23f3e3ddcdc634ef9ff4c9b1d6b58f3fd8f`
- Code version pin: `7448363`
- Registered at: 2026-10-22T02:59:17.564177+00:00
- Forward start: **2026-10-22** (after Phase 2 OOS consumption)
- Candidates registered: **5**
- Latest job: id=3 status=`completed` finished=2026-10-22T03:00:33.543174+00:00

## Integrity

- Shortlist frozen before forward processing; parameters not re-optimized.
- Phase 1/2 holdouts are **not** reused as fresh evidence.
- Multiple-testing correction: Benjamini–Hochberg over **n=5** registered candidates.
- No strategy is labeled STATISTICALLY VALIDATED on a short forward sample.

## Summary counts

- Insufficient evidence: **5**
- Forward running (unvalidated): **0**
- Statistically validated: **0**

> No candidate is labeled STATISTICALLY VALIDATED on this forward sample. 

## Per-candidate

| Candidate | Symbol | Days | Fills | Total return | vs BAH | Status |
|---|---|---:|---:|---:|---:|---|
| atr_breakout_ETH-USD | ETH-USD | 1 | 1 | N/A | N/A | `INSUFFICIENT_EVIDENCE` |
| bollinger_reversion_AMZN | AMZN | 0 | 0 | N/A | N/A | `INSUFFICIENT_EVIDENCE` |
| dual_sma_SHY | SHY | 0 | 0 | N/A | N/A | `INSUFFICIENT_EVIDENCE` |
| tsmom_NVDA | NVDA | 0 | 0 | N/A | N/A | `INSUFFICIENT_EVIDENCE` |
| zscore_reversion_META | META | 0 | 0 | N/A | N/A | `INSUFFICIENT_EVIDENCE` |

## Warnings / data notes

- bollinger_reversion_AMZN: no bars on/after 2026-10-22 yet (latest cached end=2026-10-21).
- dual_sma_SHY: no bars on/after 2026-10-22 yet (latest cached end=2026-10-21).
- tsmom_NVDA: no bars on/after 2026-10-22 yet (latest cached end=2026-10-21).
- zscore_reversion_META: no bars on/after 2026-10-22 yet (latest cached end=2026-10-21).

## Scheduler / hosting

One-shot job completed in this environment. Continuous forward testing requires a persistent host running scripts/phase3_paper_job.py on a schedule (see docs/phase3-scheduler.md).

## Candidates & limitations

### `atr_breakout_ETH-USD`
- Params: `{'atr_period': 14, 'k': 2.0}`
- Limitations: Combined top-1 in Phase 2 diagnostic; failed bootstrap CI, activity<10, and BH-FDR on consumed OOS. Forward test is new evidence only after forward_start_date.


### `tsmom_NVDA`
- Params: `{'lookback': 252, 'threshold': 0.0}`
- Limitations: Axis CAGR leader but excess vs BAH was 0 on consumed OOS; activity 0; DD gate fail. May closely track buy-and-hold — monitor excess carefully.


### `zscore_reversion_META`
- Params: `{'window': 20, 'entry_z': 1.5, 'exit_z': 0.25}`
- Limitations: Near-miss: passed all Phase 2 gates except BH-FDR (excess bootstrap p≈0.40).


### `bollinger_reversion_AMZN`
- Params: `{'window': 20, 'n_std': 2.0}`
- Limitations: Near-miss: passed all Phase 2 gates except BH-FDR (excess bootstrap p≈0.44).


### `dual_sma_SHY`
- Params: `{'fast': 50, 'slow': 200}`
- Limitations: Axis Sharpe leader on low-vol FI; excess vs BAH was 0 on consumed OOS (BAH-like path).

