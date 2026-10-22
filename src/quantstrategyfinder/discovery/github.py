"""GitHub repository discovery with rate-limit handling (FR-07).

Discovery NEVER executes third-party code — metadata + license only.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests
import yaml

from .licenses import open_source_badge
from .scoring import infer_markets, reproducibility_score, suggest_adapter
from .store import CandidateStore

logger = logging.getLogger(__name__)

API = "https://api.github.com"


class RateLimitError(RuntimeError):
    """Raised when GitHub rate limit is exhausted and wait is disabled."""


def _token() -> Optional[str]:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None


def _headers() -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "QuantStrategyFinder-discovery/0.2",
    }
    tok = _token()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _request_json(
    session: requests.Session,
    url: str,
    *,
    params: Optional[dict] = None,
    wait_on_rate_limit: bool = True,
) -> Any:
    while True:
        resp = session.get(url, headers=_headers(), params=params, timeout=60)
        remaining = resp.headers.get("X-RateLimit-Remaining")
        reset = resp.headers.get("X-RateLimit-Reset")
        if resp.status_code == 403 and remaining == "0":
            wait_s = max(0, int(reset or time.time()) - int(time.time())) + 2
            if not wait_on_rate_limit:
                raise RateLimitError(f"GitHub rate limit hit; reset in {wait_s}s")
            logger.warning("GitHub rate limit hit; sleeping %ss", wait_s)
            time.sleep(min(wait_s, 90))
            continue
        if resp.status_code == 422:
            # Search query invalid / empty — return empty
            logger.warning("GitHub search 422 for %s params=%s: %s", url, params, resp.text[:200])
            return {"items": [], "total_count": 0}
        resp.raise_for_status()
        return resp.json()


def load_discovery_config(path: str = "configs/discovery.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _repo_license_spdx(item: dict[str, Any]) -> Optional[str]:
    lic = item.get("license") or {}
    return lic.get("spdx_id")


def _fetch_commit_sha(session: requests.Session, full_name: str, branch: str) -> Optional[str]:
    try:
        data = _request_json(session, f"{API}/repos/{full_name}/commits/{branch}")
        return data.get("sha")
    except Exception as exc:  # noqa: BLE001
        logger.debug("commit fetch failed for %s: %s", full_name, exc)
        return None


def search_repositories(
    queries: list[str],
    *,
    min_stars: int = 5,
    max_repos: int = 80,
    per_page: int = 30,
    wait_on_rate_limit: bool = True,
) -> dict[str, dict[str, Any]]:
    """Search GitHub; return deduplicated map full_name -> raw item + query hits."""
    session = requests.Session()
    found: dict[str, dict[str, Any]] = {}
    for q in queries:
        page = 1
        while len(found) < max_repos:
            params = {
                "q": f"{q} stars:>={min_stars}",
                "sort": "stars",
                "order": "desc",
                "per_page": min(per_page, 100),
                "page": page,
            }
            logger.info("GitHub search: %s page=%s", q, page)
            data = _request_json(
                session,
                f"{API}/search/repositories",
                params=params,
                wait_on_rate_limit=wait_on_rate_limit,
            )
            items = data.get("items") or []
            if not items:
                break
            for item in items:
                name = item.get("full_name")
                if not name:
                    continue
                if name not in found:
                    found[name] = {"item": item, "query_hits": [q]}
                else:
                    found[name]["query_hits"].append(q)
                if len(found) >= max_repos:
                    break
            if len(items) < per_page:
                break
            page += 1
            if page > 5:
                break
            time.sleep(0.4)  # be polite to search API
        if len(found) >= max_repos:
            break
    return found


def enrich_and_store(
    found: dict[str, dict[str, Any]],
    *,
    cfg: dict[str, Any],
    store: CandidateStore,
    fetch_commits: bool = True,
) -> list[dict[str, Any]]:
    """Convert search hits to candidate rows with license badge + score. No code execution."""
    session = requests.Session()
    permissive = set(cfg.get("permissive_spdx") or [])
    market_kw = cfg.get("market_keywords") or {}
    adapter_families = cfg.get("adapter_families") or {}
    rows: list[dict[str, Any]] = []

    for full_name, bundle in found.items():
        item = bundle["item"]
        desc = item.get("description") or ""
        spdx = _repo_license_spdx(item)
        badge = open_source_badge(spdx, permissive=permissive or None)
        markets = infer_markets(f"{full_name} {desc}", market_kw)
        score = reproducibility_score(
            stars=int(item.get("stargazers_count") or 0),
            language=item.get("language"),
            license_badge=badge,
            description=desc,
            updated_at=item.get("updated_at"),
            query_hits=bundle["query_hits"],
        )
        adapter_id, fidelity = suggest_adapter(desc + " " + full_name, adapter_families)
        branch = item.get("default_branch") or "main"
        sha = None
        if fetch_commits and badge == "OPEN SOURCE":
            sha = _fetch_commit_sha(session, full_name, branch)
            time.sleep(0.15)

        row = {
            "repo_full_name": full_name,
            "html_url": item.get("html_url"),
            "description": desc,
            "language": item.get("language"),
            "stars": int(item.get("stargazers_count") or 0),
            "updated_at": item.get("updated_at"),
            "license_spdx": spdx,
            "open_source_badge": badge,
            "default_branch": branch,
            "commit_hash": sha,
            "markets_json": __import__("json").dumps(markets),
            "reproducibility_score": score,
            "shortlisted": 0,
            "review_status": "pending",
            "adapter_id": adapter_id,
            "fidelity": fidelity,  # REIMPLEMENTATION until human verifies reproduction
            "claimed_metrics_json": "[]",
            "author_claimed_note": "AUTHOR-CLAIMED metrics in upstream README are not independently verified",
            "query_hits_json": __import__("json").dumps(bundle["query_hits"]),
            "raw_json": __import__("json").dumps(
                {
                    "id": item.get("id"),
                    "fork": item.get("fork"),
                    "archived": item.get("archived"),
                    "topics": item.get("topics"),
                }
            ),
            "discovered_at": datetime.now(timezone.utc).isoformat(),
            "approved_at": None,
            "approval_note": None,
        }
        store.upsert_candidate(row)
        rows.append(row)
    return rows


def discover_repositories(
    *,
    config_path: str = "configs/discovery.yaml",
    store_path: str = "data/discovery/candidates.sqlite",
    fetch_commits: bool = True,
    wait_on_rate_limit: bool = True,
) -> dict[str, Any]:
    """
    Full discovery pipeline: search → enrich → shortlist.
    Does not execute any repository code.
    """
    cfg = load_discovery_config(config_path)
    store = CandidateStore(store_path)
    found = search_repositories(
        list(cfg.get("queries") or []),
        min_stars=int(cfg.get("min_stars", 5)),
        max_repos=int(cfg.get("max_repos", 80)),
        per_page=int(cfg.get("per_page", 30)),
        wait_on_rate_limit=wait_on_rate_limit,
    )
    rows = enrich_and_store(found, cfg=cfg, store=store, fetch_commits=fetch_commits)

    # Shortlist: prefer OPEN SOURCE + high reproducibility
    ranked = sorted(
        rows,
        key=lambda r: (
            1 if r["open_source_badge"] == "OPEN SOURCE" else 0,
            float(r["reproducibility_score"]),
            int(r["stars"]),
        ),
        reverse=True,
    )
    n_short = int(cfg.get("shortlist_size", 15))
    # Prefer open-source for shortlist; fill with others if needed but flag
    open_ranked = [r for r in ranked if r["open_source_badge"] == "OPEN SOURCE"]
    shortlist = open_ranked[:n_short]
    if len(shortlist) < n_short:
        extras = [r for r in ranked if r not in shortlist]
        shortlist.extend(extras[: n_short - len(shortlist)])
    store.mark_shortlisted([r["repo_full_name"] for r in shortlist])

    run_id = datetime.now(timezone.utc).strftime("disc_%Y%m%dT%H%M%SZ")
    summary = {
        "run_id": run_id,
        "n_discovered": len(rows),
        "n_open_source": sum(1 for r in rows if r["open_source_badge"] == "OPEN SOURCE"),
        "n_shortlisted": len(shortlist),
        "shortlist": [r["repo_full_name"] for r in shortlist],
        "note": "Discovery never executes third-party code. Approval required before adapters run.",
        "authenticated": bool(_token()),
    }
    store.save_discovery_run(run_id, summary)
    # Export JSON snapshot for dashboard
    from pathlib import Path
    import json

    out_dir = Path("data/discovery")
    out_dir.mkdir(parents=True, exist_ok=True)
    snap = out_dir / f"{run_id}.json"
    snap.write_text(
        json.dumps(
            {"summary": summary, "shortlist": shortlist, "all_count": len(rows)},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    summary["snapshot"] = str(snap)
    return summary
