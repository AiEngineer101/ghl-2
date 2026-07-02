"""Active handler for WF | Gate | CrewConfirmed.

Spec source: production/ready-for-materials.md §2 condition 3
- Trigger: Opportunity Changed (in Production pipeline)
- IF: tf_crew_confirmed = Yes
- DO: if dt_crew_confirmed is empty -> set dt_crew_confirmed = Today
- Idempotent: never overwrites an existing dt_crew_confirmed

Note: dt_crew_confirmed is marked [NEW FIELD — to be created] in the spec. The stamp
will silently no-op until the field is created in GHL (field ID not found in key map).
The guard in move_prod_p05_p10 reads both tf_crew_confirmed and dt_crew_confirmed.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity, yes

HANDLER_ID = "gate-crew-confirmed"
SUPPORTS_WRITE = True
INPUT_FIELD = "tf_crew_confirmed"
OUTPUT_FIELD = "dt_crew_confirmed"


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    custom = custom_field_map(opp)
    tf_value = custom.get(INPUT_FIELD)
    dt_current = custom.get(OUTPUT_FIELD)

    base = {
        "handler_id": HANDLER_ID,
        "target_field": OUTPUT_FIELD,
        "current_value": _to_str(dt_current),
    }

    if not yes(tf_value):
        return {
            **base,
            "decision": "no_op",
            "reason": f"{INPUT_FIELD} is not Yes (value={tf_value!r}); nothing to stamp",
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
            f"{INPUT_FIELD}=Yes and {OUTPUT_FIELD} is empty — "
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
