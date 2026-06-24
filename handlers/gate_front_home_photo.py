"""Shadow handler for WF | Gate | FrontHomePhoto (Sales).

Spec source: workflow/01-gates/ev-to-dt/gate-front-home-photo.md (CR-0001)
- Trigger (live): Opportunity Changed, scoped to the Sales pipeline (Allow Re-Entry=Yes).
  Per spec, do NOT use an EV field trigger filter — evaluate EV/DT state inside the handler.
- IF: ev_front_of_home_inspection_photo is not empty
- DO: if dt_front_of_home_inspection_photo_received is empty -> set it = Today
- Idempotent: DT_received is stamped once (write-once).

SHADOW (SUPPORTS_WRITE=False) — Sales is live with no test harness yet, so every new
Sales handler is added watch-only and validated on the dashboard before any cutover.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "gate-front-home-photo"
SUPPORTS_WRITE = False  # shadow-first

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
INPUT_FIELD = "ev_front_of_home_inspection_photo"
OUTPUT_FIELD = "dt_front_of_home_inspection_photo_received"


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

    # Spec scopes this gate to the Sales pipeline.
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
    """Stamp dt_front_of_home_inspection_photo_received via the GHL writer.

    Wired but inert while SUPPORTS_WRITE=False (app.py only calls execute() for
    write-enabled handlers).
    """
    from handlers._writers import stamp_custom_field
    return await stamp_custom_field(opp_data, decision, OUTPUT_FIELD)
