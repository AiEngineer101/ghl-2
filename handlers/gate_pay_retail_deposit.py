"""Shadow handler for WF | Gate | PayRetailDeposit (Sales).

Spec source: workflow/01-gates/ev-to-dt/gate-pay-retail-deposit.md
- Trigger (live): Opportunity Changed, scoped to the Sales pipeline (Allow Re-Entry=Yes).
- IF: ev_retail_deposit_proof is not empty
- DO: if dt_retail_deposit_proof_received is empty -> set it = Today (first receipt only)
- Idempotent: dt_retail_deposit_proof_received is write-once.

Feeds the S45->S46 funding move and production-readiness (Retail/Hybrid).

ACTIVE (SUPPORTS_WRITE=True; cut over 2026-06-30 after the output key was verified live via
/debug/field-keys). The matching GHL gate (WF | Gate | PayRetailDeposit) stays Published until
you Draft it — harmless idempotent overlap, since both write the same write-once date. Per
docs/sales-gate-migration-plan.md.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "gate-pay-retail-deposit"
SUPPORTS_WRITE = True  # ACTIVE (cut over 2026-06-30; output key verified live via /debug/field-keys)

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
INPUT_FIELD = "ev_retail_deposit_proof"
OUTPUT_FIELD = "dt_retail_deposit_proof_received"


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
    """Stamp dt_retail_deposit_proof_received via the GHL writer (inert while shadow)."""
    from handlers._writers import stamp_custom_field
    return await stamp_custom_field(opp_data, decision, OUTPUT_FIELD)
