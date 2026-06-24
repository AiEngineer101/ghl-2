"""Shadow handler for WF | Gate | InsuranceScope (Sales).

Spec source: workflow/01-gates/ev-to-dt/gate-insurance-scope.md
- Trigger (live): Opportunity Changed, scoped to the Sales pipeline (Allow Re-Entry=Yes).
- IF: ev_insurance_scope_doc is not empty
- DO: if dt_insurance_scope_received is empty -> set it = Today (first receipt only)
- Idempotent: dt_insurance_scope_received is write-once.

Not job-type-gated: the gate just stamps when the scope doc is present (Retail jobs
never have one). Job-type branching happens at the S20->S30 mover.

SHADOW (SUPPORTS_WRITE=False) — Sales watch-only until a test harness exists.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "gate-insurance-scope"
SUPPORTS_WRITE = False  # shadow-first

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
INPUT_FIELD = "ev_insurance_scope_doc"
OUTPUT_FIELD = "dt_insurance_scope_received"


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
            "reason": f"{OUTPUT_FIELD} already set ({dt_current}); write-once enforced",
        }

    target = date.today().isoformat()
    return {
        **base,
        "decision": "would_stamp",
        "target_value": target,
        "reason": (
            f"{INPUT_FIELD} present and {OUTPUT_FIELD} is empty — "
            f"would set {OUTPUT_FIELD} = {target}"
        ),
    }


def _to_str(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Stamp dt_insurance_scope_received via the GHL writer. Inert while SUPPORTS_WRITE=False."""
    from handlers._writers import stamp_custom_field
    return await stamp_custom_field(opp_data, decision, OUTPUT_FIELD)
