"""Candidate review queue — explicit approval before any adapter execution."""

from __future__ import annotations

from typing import Any, Optional

from .store import CandidateStore


ALLOWED_STATUSES = {"pending", "approved", "rejected", "needs_info"}


def review_queue(
    store: Optional[CandidateStore] = None,
    *,
    shortlisted_only: bool = True,
) -> list[dict[str, Any]]:
    store = store or CandidateStore()
    rows = store.list_candidates(shortlisted_only=shortlisted_only)
    return rows


def approve_candidate(
    repo_full_name: str,
    *,
    adapter_id: str,
    note: str = "",
    store: Optional[CandidateStore] = None,
    fidelity: str = "REIMPLEMENTATION",
) -> dict[str, Any]:
    """
    Approve running a FIRST-PARTY adapter mapped to this repo.

    This does NOT authorize executing upstream repository code.
    Fidelity defaults to REIMPLEMENTATION (rules reimplemented in-house).
    """
    if fidelity not in {"REIMPLEMENTATION", "REPRODUCED ORIGINAL"}:
        raise ValueError("fidelity must be REIMPLEMENTATION or REPRODUCED ORIGINAL")
    store = store or CandidateStore()
    row = store.get(repo_full_name)
    if not row:
        raise KeyError(f"Unknown candidate: {repo_full_name}")
    if row.get("open_source_badge") != "OPEN SOURCE" and fidelity == "REPRODUCED ORIGINAL":
        raise ValueError(
            "Cannot mark REPRODUCED ORIGINAL without OPEN SOURCE license badge"
        )
    store.set_review(
        repo_full_name,
        status="approved",
        adapter_id=adapter_id,
        fidelity=fidelity,
        note=note
        or (
            "Approved first-party adapter only; upstream code is never executed. "
            f"Fidelity={fidelity}."
        ),
    )
    return store.get(repo_full_name) or {}


def reject_candidate(
    repo_full_name: str,
    *,
    note: str = "",
    store: Optional[CandidateStore] = None,
) -> dict[str, Any]:
    store = store or CandidateStore()
    store.set_review(repo_full_name, status="rejected", note=note or "Rejected")
    return store.get(repo_full_name) or {}


def assign_fallback_adapters(
    *,
    store: Optional[CandidateStore] = None,
    adapter_ids: Optional[list[str]] = None,
    open_source_only: bool = True,
) -> list[dict[str, Any]]:
    """
    Assign unused first-party adapter families to unmapped shortlisted OPEN SOURCE repos.

    Mapping is heuristic for research coverage; fidelity remains REIMPLEMENTATION.
    Does not download or execute upstream code.
    """
    from quantstrategyfinder.strategies.adapters import ADAPTER_REGISTRY

    store = store or CandidateStore()
    pool = list(adapter_ids or sorted(ADAPTER_REGISTRY.keys()))
    used = {
        r.get("adapter_id")
        for r in store.list_candidates(shortlisted_only=True)
        if r.get("adapter_id") and r.get("adapter_id") != "UNMAPPED"
    }
    available = [a for a in pool if a not in used]
    updated: list[dict[str, Any]] = []
    for row in store.list_candidates(shortlisted_only=True):
        if open_source_only and row.get("open_source_badge") != "OPEN SOURCE":
            continue
        if row.get("adapter_id") and row.get("adapter_id") != "UNMAPPED":
            continue
        if not available:
            break
        aid = available.pop(0)
        store.set_review(
            row["repo_full_name"],
            status=row.get("review_status") or "pending",
            adapter_id=aid,
            fidelity="REIMPLEMENTATION",
            note=(
                "Heuristic fallback adapter assignment for shortlist coverage; "
                "first-party REIMPLEMENTATION only — upstream not executed."
            ),
        )
        # set_review with pending may clear approved_at — re-read and keep pending
        # Actually set_review always sets approved_at only when approved. Good.
        # But we need to update adapter_id without changing status incorrectly.
        updated.append(store.get(row["repo_full_name"]) or {})
    return updated


def approve_shortlist_mapped(
    *,
    store: Optional[CandidateStore] = None,
    open_source_only: bool = True,
    assign_fallbacks: bool = True,
) -> list[dict[str, Any]]:
    """
    Bulk-approve shortlisted candidates that have an adapter_id mapping.
    Optionally assign fallback adapters to unmapped OPEN SOURCE shortlist entries first.
    Still runs only first-party adapters — never upstream code.
    """
    store = store or CandidateStore()
    if assign_fallbacks:
        assign_fallback_adapters(store=store, open_source_only=open_source_only)
    approved: list[dict[str, Any]] = []
    for row in store.list_candidates(shortlisted_only=True):
        if open_source_only and row.get("open_source_badge") != "OPEN SOURCE":
            continue
        adapter_id = row.get("adapter_id")
        if not adapter_id or adapter_id == "UNMAPPED":
            continue
        approved.append(
            approve_candidate(
                row["repo_full_name"],
                adapter_id=adapter_id,
                fidelity=row.get("fidelity") or "REIMPLEMENTATION",
                note="Bulk-approved mapped first-party adapter (upstream not executed).",
                store=store,
            )
        )
    return approved
