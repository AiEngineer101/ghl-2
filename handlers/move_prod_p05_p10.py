"""Shadow handler for WF | Move | Prod | P05->P10 Install Scheduled.

Spec source: production/ready-for-materials.md §4 (mover) + §5 (guards)
- Trigger: dt_material_id_report_received is not empty (materials order confirmed)
- Guards (all must pass; return skip_condition_unmet if any fail):
    1. tf_crew_confirmed = Yes AND dt_crew_confirmed is not empty
    2. dt_install_scheduled is not empty (scheduling done)
    3. IF seg_permit_required = Yes: dt_permit_approved + ev_permit_approved_doc both present
- IF: Pipeline=Production AND Stage=P05 AND trigger + guards pass
- DO: Move to PL_PROD / P10 (Production Scheduled)
- Idempotent: skip if already at P10+
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity, yes

HANDLER_ID = "move-prod-p05-p10-install-scheduled"
SUPPORTS_WRITE = True

PIPELINE_ID_PROD = "88V9uYY6visCrtI9V0NR"
STAGE_ID_P05 = "c98f59ed-7b38-4dd6-ae64-01c5a6537894"
STAGE_ID_P10 = "7a4f2d75-f033-4971-8eed-8ca4285e639e"

STAGES_AFTER_P10: set[str] = {
    "ebef66b1-a570-412c-93b3-1be988d6a33f",  # P20
    "96f19b6d-4d85-4e66-910f-4a4f071bf9c0",  # P30
    "bb84bafb-5266-4063-b1f6-bc1ef21a0790",  # P40
    "de0bc542-b6a0-4885-b991-18ed02b19fe7",  # P50
}

# Mover trigger field
TRIGGER_FIELD = "dt_material_id_report_received"

# Guard fields
FIELD_CREW_TF = "tf_crew_confirmed"
FIELD_CREW_DT = "dt_crew_confirmed"
FIELD_INSTALL_SCHEDULED = "dt_install_scheduled"
FIELD_PERMIT_REQUIRED = "seg_permit_required"
FIELD_PERMIT_APPROVED = "dt_permit_approved"
FIELD_PERMIT_DOC = "ev_permit_approved_doc"


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    stage_id = opp.get("pipelineStageId")
    custom = custom_field_map(opp)

    base = {
        "handler_id": HANDLER_ID,
        "target_field": "pipelineStageId",
        "current_value": stage_id,
    }

    if pipeline_id != PIPELINE_ID_PROD:
        return {
            **base,
            "decision": "no_op",
            "reason": f"pipelineId {pipeline_id!r} is not Production ({PIPELINE_ID_PROD})",
        }

    if stage_id == STAGE_ID_P10 or stage_id in STAGES_AFTER_P10:
        return {
            **base,
            "decision": "skip_idempotent",
            "reason": "Already at or beyond P10; no advancement needed",
        }

    if stage_id != STAGE_ID_P05:
        return {
            **base,
            "decision": "no_op",
            "reason": f"Stage {stage_id!r} is not P05",
        }

    # Mover trigger: materials order confirmed
    if not truthy(custom.get(TRIGGER_FIELD)):
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"{TRIGGER_FIELD} is empty; materials order not yet confirmed",
        }

    # Guard 1: crew confirmed (tf + dt both required)
    if not yes(custom.get(FIELD_CREW_TF)):
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"{FIELD_CREW_TF} is not Yes; crew not confirmed",
        }
    if not truthy(custom.get(FIELD_CREW_DT)):
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"{FIELD_CREW_DT} is empty; crew confirmation not stamped",
        }

    # Guard 2: install scheduled
    if not truthy(custom.get(FIELD_INSTALL_SCHEDULED)):
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"{FIELD_INSTALL_SCHEDULED} is empty; install not yet scheduled",
        }

    # Guard 3: permit (only when required)
    if yes(custom.get(FIELD_PERMIT_REQUIRED)):
        if not truthy(custom.get(FIELD_PERMIT_APPROVED)):
            return {
                **base,
                "decision": "skip_condition_unmet",
                "reason": f"Permit required but {FIELD_PERMIT_APPROVED} is empty",
            }
        if not truthy(custom.get(FIELD_PERMIT_DOC)):
            return {
                **base,
                "decision": "skip_condition_unmet",
                "reason": f"Permit required but {FIELD_PERMIT_DOC} is empty",
            }

    return {
        **base,
        "decision": "would_move",
        "target_value": STAGE_ID_P10,
        "reason": (
            f"At P05: materials confirmed, crew confirmed, install scheduled, permit cleared — "
            f"would move to P10 (Production Scheduled)"
        ),
    }


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    from handlers._writers import move_stage
    return await move_stage(
        opp_data, decision, last_good_stage_code="P10", last_good_pipeline_code="PL_PROD"
    )
