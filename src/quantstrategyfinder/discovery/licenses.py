"""License SPDX validation for discovery candidates (FR-07)."""

from __future__ import annotations

from typing import Optional

# Default permissive set; configs/discovery.yaml may extend at runtime
DEFAULT_PERMISSIVE = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "Unlicense",
        "0BSD",
        "CC0-1.0",
        "MPL-2.0",
    }
)

# Explicitly non-open / incompatible for our OPEN SOURCE badge
NON_OPEN = frozenset(
    {
        "NOASSERTION",
        "NONE",
        "OTHER",
        "LicenseRef-proprietary",
        "AGPL-3.0",
        "GPL-2.0",
        "GPL-3.0",
        "LGPL-2.1",
        "LGPL-3.0",
    }
)


def normalize_spdx(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return raw.strip()


def is_permissive_open_source(
    spdx: Optional[str],
    *,
    permissive: Optional[set[str] | frozenset[str]] = None,
) -> bool:
    """True only for genuinely permissive/compatible licenses (not merely public code)."""
    key = normalize_spdx(spdx)
    if not key or key.upper() in {"NOASSERTION", "NONE", "OTHER"}:
        return False
    allowed = permissive or DEFAULT_PERMISSIVE
    return key in allowed


def open_source_badge(
    spdx: Optional[str],
    *,
    permissive: Optional[set[str] | frozenset[str]] = None,
) -> str:
    if is_permissive_open_source(spdx, permissive=permissive):
        return "OPEN SOURCE"
    if not spdx or normalize_spdx(spdx) in {"NOASSERTION", "NONE", None}:
        return "LICENSE UNKNOWN"
    return "NOT OPEN SOURCE (incompatible or non-permissive)"
