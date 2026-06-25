"""Pure write-authorization decision — no I/O, no deps, so it's trivially testable.

A write to an opportunity is allowed when writes are enabled AND any one of:
  - the WRITING HANDLER is in the handler allowlist (the per-handler "this mover is live for
    its whole pipeline" knob — used to cut Sales over to active ONE stage at a time), OR
  - the opp's CURRENT pipeline is in the pipeline allowlist (the normal Production path), OR
  - the specific opp ID is in the opp allowlist (scoped test opps in non-allowlisted pipelines).

Three independent dimensions, widest-to-narrowest scope:
  - handler allowlist  -> "every opp this handler chooses to act on" (handlers self-scope to
                          their own pipeline+stage in evaluate(), so this is effectively
                          pipeline-wide FOR THAT ONE MOVE — the migration cutover unit).
  - pipeline allowlist -> "every opp in this pipeline" (Production: fully migrated).
  - opp allowlist      -> "just these test opps" (Sales sandbox before cutover).

A real (non-allowlisted) Sales deal whose mover is NOT yet handler-allowlisted is blocked
because it matches none of the three rules — exactly what keeps live deals safe mid-migration.
"""
from __future__ import annotations


def is_write_allowed(
    opp_id: str | None,
    pipeline_id: str | None,
    *,
    writes_enabled: bool,
    allowed_pipelines: set[str],
    allowed_opps: set[str],
    handler_id: str | None = None,
    allowed_handlers: set[str] | None = None,
) -> tuple[bool, str]:
    """Return (allowed, reason)."""
    allowed_handlers = allowed_handlers or set()
    if not writes_enabled:
        return False, "WRITES_ENABLED=false"
    if handler_id is not None and handler_id in allowed_handlers:
        return True, f"handler {handler_id!r} in handler-allowlist (pipeline-live)"
    if pipeline_id in allowed_pipelines:
        return True, f"pipeline {pipeline_id!r} in pipeline-allowlist"
    if opp_id in allowed_opps:
        return True, f"opp {opp_id!r} in opp-allowlist (scoped test opp)"
    return False, (
        f"opp {opp_id!r} (pipeline {pipeline_id!r}, handler {handler_id!r}) not writable: "
        f"handler not in {sorted(allowed_handlers)}, pipeline not in "
        f"{sorted(allowed_pipelines)}, and opp not in opp-allowlist"
    )
