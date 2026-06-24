"""Pure write-authorization decision — no I/O, no deps, so it's trivially testable.

A write to an opportunity is allowed when writes are enabled AND either:
  - the opp's CURRENT pipeline is in the pipeline allowlist (the normal Production path), OR
  - the specific opp ID is in the opp allowlist (scoped test opps in non-allowlisted pipelines).

The opp allowlist is what lets us drive a single Sales test opportunity to ACTIVE writes
without opening writes to every other Sales opportunity in production. Production opps keep
working via the pipeline allowlist; a real (non-allowlisted) Sales deal is blocked because it
matches neither rule.
"""
from __future__ import annotations


def is_write_allowed(
    opp_id: str | None,
    pipeline_id: str | None,
    *,
    writes_enabled: bool,
    allowed_pipelines: set[str],
    allowed_opps: set[str],
) -> tuple[bool, str]:
    """Return (allowed, reason)."""
    if not writes_enabled:
        return False, "WRITES_ENABLED=false"
    if pipeline_id in allowed_pipelines:
        return True, f"pipeline {pipeline_id!r} in pipeline-allowlist"
    if opp_id in allowed_opps:
        return True, f"opp {opp_id!r} in opp-allowlist (scoped test opp)"
    return False, (
        f"opp {opp_id!r} (pipeline {pipeline_id!r}) not writable: pipeline not in "
        f"{sorted(allowed_pipelines)} and opp not in opp-allowlist"
    )
