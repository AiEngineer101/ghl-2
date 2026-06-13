"""Active handler for WF | Gate | MaterialsVerified.

Spec source: workflow/01-gates/ev-to-dt/gate-materials-verified.md
- Trigger: Opportunity Changed (in Production pipeline)
- IF: ev_materials_verified_photos is not empty
- DO: if dt_materials_verified is empty -> set dt_materials_verified = Today
- Idempotent: never overwrites an existing dt_materials_verified

Active writer — the corresponding live GHL workflow should be set to Draft.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "gate-materials-verified"
SUPPORTS_WRITE = True  # active writer
INPUT_FIELD = "ev_materials_verified_photos"
OUTPUT_FIELD = "dt_materials_verified"


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
    """Stamp dt_materials_verified via the GHL writer."""
    from handlers._writers import stamp_custom_field
    return await stamp_custom_field(opp_data, decision, OUTPUT_FIELD)
