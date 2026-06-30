"""Shadow handler for WF | Gate | MeasurementReport (Sales).

Spec source: workflow/01-gates/ev-to-dt/gate-measurement-report.md (CR-0020)
- Trigger (live): Opportunity Changed, scoped to the Sales pipeline (no job-type filter, Allow
  Re-Entry=Yes).
- IF: ev_measurement_report is not empty AND the received-date is empty
- DO: set the measurement-report received date = Today (first receipt only, all job types)
- Idempotent: the received date is write-once.

⚠️ LIVE FIELD KEY: the measurement-report received date lives in live GHL under the MALFORMED
key `_measurement_report_received_date` (no dt_ prefix), NOT the spec key
`dt_measurement_report_received`. We must WRITE the live key or the PUT won't resolve to a real
field. (Discovered 2026-06-29 — same bug the derived-production-readiness fix d6cb448 addressed;
that handler reads EITHER key. This gate stamps the live key and treats EITHER as "already set"
for idempotency, so it never double-stamps and stays consistent with the live GHL gate.)

Feeds production-readiness (global prerequisite). NOTE: measurement report is context-only — it
is NOT a stage-exit gate; it only contributes to readiness (do not expect it to move a stage).

SHADOW (SUPPORTS_WRITE=False) — new gate per docs/sales-gate-migration-plan.md (Tier 1): ship
shadow, validate on /decisions (would_stamp + key resolves) on a test opp, THEN flip to True and
Draft the matching GHL gate. The live GHL gate keeps stamping until then (idempotent on the
write-once date, so the overlap is harmless).

Note: the GHL gate also flips lowercase "status —/missing —" measurement-report tags — tag parity
is phase 2 (our readiness keys on the date, not tags), so this handler stamps the date only.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "gate-measurement-report"
SUPPORTS_WRITE = False  # shadow until validated (see docs/sales-gate-migration-plan.md)

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
INPUT_FIELD = "ev_measurement_report"
# Write target = the LIVE (malformed) key so the PUT resolves to the real GHL field.
OUTPUT_FIELD = "_measurement_report_received_date"
# Either key counts as "already received" for the write-once idempotency check (the spec key is
# kept for tolerance, matching derived_production_readiness.MEASUREMENT_REPORT_KEYS).
RECEIVED_KEYS = ("_measurement_report_received_date", "dt_measurement_report_received")


def _received_value(custom: dict[str, Any]) -> Any:
    """Return the first present measurement-report received-date value, across both keys."""
    for k in RECEIVED_KEYS:
        v = custom.get(k)
        if truthy(v):
            return v
    return None


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    custom = custom_field_map(opp)
    ev_value = custom.get(INPUT_FIELD)
    dt_current = _received_value(custom)

    base = {
        "handler_id": HANDLER_ID,
        "target_field": OUTPUT_FIELD,
        "current_value": _to_str(dt_current),
    }

    if pipeline_id != PIPELINE_ID_SALES:
        return {
            **base,
            "decision": "no_op",
            "reason": f"pipelineId {pipeline_id!r} is not Sales ({PIPELINE_ID_SALES})",
        }

    if not truthy(ev_value):
        return {
            **base,
            "decision": "no_op",
            "reason": f"{INPUT_FIELD} is empty; nothing to stamp",
        }

    if truthy(dt_current):
        return {
            **base,
            "decision": "skip_idempotent",
            "reason": f"measurement-report received date already set ({dt_current}); write-once enforced",
        }

    target = date.today().isoformat()
    return {
        **base,
        "decision": "would_stamp",
        "target_value": target,
        "reason": (
            f"{INPUT_FIELD} present and no received date yet — "
            f"would set {OUTPUT_FIELD} = {target}"
        ),
    }


def _to_str(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Stamp the live measurement-report received-date key via the GHL writer (inert while shadow)."""
    from handlers._writers import stamp_custom_field
    return await stamp_custom_field(opp_data, decision, OUTPUT_FIELD)
