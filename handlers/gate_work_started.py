"""Shadow handler for WF | Gate | WorkStarted.

Spec source: workflow/01-gates/tf-to-dt/gate-work-started.md
- Trigger (live): Opportunity Changed, "Custom field updated: tf_work_started"
- IF: tf_work_started=Yes AND dt_work_started is empty
- DO: Set dt_work_started = Today
- Idempotent: never overwrites an existing dt_work_started

Active writer — the corresponding live GHL workflow should be set to Draft.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity, yes

HANDLER_ID = "gate-work-started"
SUPPORTS_WRITE = True  # active writer
INPUT_FIELD = "tf_work_started"
OUTPUT_FIELD = "dt_work_started"


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
    """Stamp dt_work_started via the GHL writer."""
    from handlers._writers import stamp_custom_field
    return await stamp_custom_field(opp_data, decision, OUTPUT_FIELD)
