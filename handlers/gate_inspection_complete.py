"""Shadow handler for WF | Gate | InspectionComplete (Sales).

Spec source: workflow/01-gates/tf-to-dt/gate-inspection-complete.md
- Trigger (live): Opportunity Changed, "Custom field updated: tf_inspection_completed"
- IF: tf_inspection_completed=Yes AND dt_inspection_completed is empty
      AND ev_front_of_home_inspection_photo is not empty
- DO: Set dt_inspection_completed = Now
- Idempotent: never overwrites an existing dt_inspection_completed

The required-photo precondition means inspection-complete truth is only earned once the
front-of-home proof photo exists (the front-photo EV->DT gate stamps the photo's own DT).

SHADOW (SUPPORTS_WRITE=False) — Sales watch-only until a test harness exists.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity, yes

HANDLER_ID = "gate-inspection-complete"
SUPPORTS_WRITE = False  # shadow-first

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
INPUT_FIELD = "tf_inspection_completed"
PHOTO_FIELD = "ev_front_of_home_inspection_photo"
OUTPUT_FIELD = "dt_inspection_completed"


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    custom = custom_field_map(opp)
    tf_value = custom.get(INPUT_FIELD)
    photo = custom.get(PHOTO_FIELD)
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

    if not truthy(photo):
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": (
                f"{INPUT_FIELD}=Yes but {PHOTO_FIELD} is empty — inspection-complete "
                f"truth requires the front-of-home proof photo first"
            ),
        }

    target = date.today().isoformat()
    return {
        **base,
        "decision": "would_stamp",
        "target_value": target,
        "reason": (
            f"{INPUT_FIELD}=Yes, {PHOTO_FIELD} present and {OUTPUT_FIELD} empty — "
            f"would set {OUTPUT_FIELD} = {target}"
        ),
    }


def _to_str(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Stamp dt_inspection_completed via the GHL writer. Inert while SUPPORTS_WRITE=False."""
    from handlers._writers import stamp_custom_field
    return await stamp_custom_field(opp_data, decision, OUTPUT_FIELD)
