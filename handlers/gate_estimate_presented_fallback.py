"""Handler for WF | Gate | EstimatePresented | FallbackArchive (Sales).

Spec source: workflow/01-gates/ev-to-dt/gate-estimate-presented-fallback-archive.md (CR-0007)
- Trigger (live): Opportunity Changed, scoped to the Sales pipeline (Allow Re-Entry=Yes).
- IF: ev_estimate_doc is not empty AND dt_estimate_presented is empty
- DO: set dt_estimate_presented = Today (write-once presentation truth)
- Idempotent: dt_estimate_presented is write-once.

Fallback-only path: covers the case where the estimate was handled outside Documents &
Contracts and a hidden internal archive copy is uploaded to ev_estimate_doc. The PRIMARY path
(estimate "Sent" in D&C) is gate-estimate-presented-dc (Tier 3, needs the D&C webhook bridge —
still GHL-owned). Both stamp the same write-once dt_estimate_presented, so they're idempotent.

Feeds the S30->S40 mover (Retail/Hybrid) and production-readiness.

ACTIVE (SUPPORTS_WRITE=True; ev_estimate_doc + dt_estimate_presented verified live via
/debug/field-keys). Idempotent overlap with the still-Published GHL gate until it's Drafted.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "gate-estimate-presented-fallback-archive"
SUPPORTS_WRITE = True  # ACTIVE; keys verified live via /debug/field-keys

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
INPUT_FIELD = "ev_estimate_doc"
OUTPUT_FIELD = "dt_estimate_presented"


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    custom = custom_field_map(opp)
    ev_value = custom.get(INPUT_FIELD)
    dt_current = custom.get(OUTPUT_FIELD)

    base = {
        "handler_id": HANDLER_ID,
        "target_field": OUTPUT_FIELD,
        "current_value": _to_str(dt_current),
    }

    if pipeline_id != PIPELINE_ID_SALES:
        return {**base, "decision": "no_op",
                "reason": f"pipelineId {pipeline_id!r} is not Sales ({PIPELINE_ID_SALES})"}

    if not truthy(ev_value):
        return {**base, "decision": "no_op",
                "reason": f"{INPUT_FIELD} is empty; nothing to stamp"}

    if truthy(dt_current):
        return {**base, "decision": "skip_idempotent",
                "reason": f"{OUTPUT_FIELD} already set ({dt_current}); write-once enforced"}

    target = date.today().isoformat()
    return {**base, "decision": "would_stamp", "target_value": target,
            "reason": (f"{INPUT_FIELD} present and {OUTPUT_FIELD} empty — "
                       f"would set {OUTPUT_FIELD} = {target}")}


def _to_str(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Stamp dt_estimate_presented via the GHL writer."""
    from handlers._writers import stamp_custom_field
    return await stamp_custom_field(opp_data, decision, OUTPUT_FIELD)
