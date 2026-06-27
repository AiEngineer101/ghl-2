"""Shadow handler for WF | Move | Prod | P20->P30 Work Completed.

Spec source: workflow/03-move/production/move-prod-p20-p30-work-completed.md
- Trigger (live): Opportunity Changed, "Custom field updated: tf_work_completed"
- IF: Pipeline=Production AND Stage in {P10, P20} AND tf_work_completed=Yes
- DO: Move to PL_PROD / P30 (Job Completed)
- Idempotent: skip if already at P30 or beyond

Active writer — the corresponding live GHL workflow should be set to Draft.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, unwrap_opportunity

HANDLER_ID = "move-prod-p20-p30-work-completed"
SUPPORTS_WRITE = True  # active writer

# GHL pipeline/stage IDs
PIPELINE_ID_PROD = "88V9uYY6visCrtI9V0NR"
STAGE_ID_P10 = "7a4f2d75-f033-4971-8eed-8ca4285e639e"
STAGE_ID_P20 = "ebef66b1-a570-412c-93b3-1be988d6a33f"
STAGE_ID_P30 = "96f19b6d-4d85-4e66-910f-4a4f071bf9c0"

ELIGIBLE_FROM_STAGES: set[str] = {STAGE_ID_P10, STAGE_ID_P20}
STAGES_AT_OR_AFTER_P30: set[str] = {
    STAGE_ID_P30,
    "bb84bafb-5266-4063-b1f6-bc1ef21a0790",  # P40
    "de0bc542-b6a0-4885-b991-18ed02b19fe7",  # P50
}

INPUT_FIELD_WORK_COMPLETED = "tf_work_completed"


def _yes(value: Any) -> bool:
    """Return True if a truth-flag field equals Yes (tolerates string, list, case)."""
    if value is None:
        return False
    if isinstance(value, list):
        return any(_yes(v) for v in value)
    return str(value).strip().lower() == "yes"


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    stage_id = opp.get("pipelineStageId")
    custom = custom_field_map(opp)
    work_completed = custom.get(INPUT_FIELD_WORK_COMPLETED)

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

    if stage_id in STAGES_AT_OR_AFTER_P30:
        return {
            **base,
            "decision": "skip_idempotent",
            "reason": "Already at or beyond P30; no advancement needed",
        }

    if stage_id not in ELIGIBLE_FROM_STAGES:
        return {
            **base,
            "decision": "no_op",
            "reason": f"Stage {stage_id!r} not in eligible source stages (P10, P20)",
        }

    if not _yes(work_completed):
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"{INPUT_FIELD_WORK_COMPLETED} != Yes (value={work_completed!r})",
        }

    from_stage_label = "P10" if stage_id == STAGE_ID_P10 else "P20"
    return {
        **base,
        "decision": "would_move",
        "target_value": STAGE_ID_P30,
        "reason": (
            f"At {from_stage_label} with {INPUT_FIELD_WORK_COMPLETED}=Yes — "
            f"would move to P30 (Job Completed)"
        ),
    }


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """PUT pipelineStageId=P30 and stamp sys_last_good_* (destination) via the GHL writer.

    Records last-good = the DESTINATION stage (P30), matching the other Production movers
    (p05-p10→P10, p10-p20→P20, p30-p40→P40, p40-p50→P50). Previously this mover stamped no
    last-good at all, leaving sys_last_good_stage_code stale at P20 after a P20→P30 move —
    which the GHL stage-gate/override revert logic reads as the bounce-back target.
    (Related: R9 last-good spec defect, webhook-event-contract §6.1.)
    """
    from handlers._writers import move_stage
    return await move_stage(
        opp_data, decision, last_good_stage_code="P30", last_good_pipeline_code="PL_PROD"
    )
