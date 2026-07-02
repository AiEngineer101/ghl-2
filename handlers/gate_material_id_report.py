"""Active handler for WF | Gate | MaterialIdReport.

Spec source: production/ready-for-materials.md §2 condition 1-2
- Trigger: Opportunity Changed (in Production pipeline)
- IF: ev_material_id_report is not empty
- DO: if dt_material_id_report_received is empty -> set dt_material_id_report_received = Today
- Idempotent: never overwrites an existing dt_material_id_report_received

This DT stamp is also the trigger condition for the P05->P10 mover.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "gate-material-id-report"
SUPPORTS_WRITE = True
INPUT_FIELD = "ev_material_id_report"
OUTPUT_FIELD = "dt_material_id_report_received"


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    custom = custom_field_map(opp)
    ev_value = custom.get(INPUT_FIELD)
    dt_current = custom.get(OUTPUT_FIELD)

    base = {
        "handler_id": HANDLER_ID,
        "target_field": OUTPUT_FIELD,
        "current_value": _to_str(dt_current),
    }

    if not truthy(ev_value):
        return {**base, "decision": "no_op", "reason": f"{INPUT_FIELD} is empty; nothing to stamp"}

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
            f"{INPUT_FIELD} is present and {OUTPUT_FIELD} is empty — "
            f"would set {OUTPUT_FIELD} = {target}"
        ),
    }


def _to_str(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    from handlers._writers import stamp_custom_field
    return await stamp_custom_field(opp_data, decision, OUTPUT_FIELD)
