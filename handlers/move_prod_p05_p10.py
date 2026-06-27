"""Shadow handler for WF | Move | Prod | P05->P10 Install Scheduled.

Spec source: workflow/03-move/production/move-prod-p05-p10-install-scheduled.md
- Trigger: Opportunity Changed (custom field updated: dt_install_scheduled)
- IF: Pipeline=Production AND Stage=P05 AND dt_install_scheduled is not empty
- DO: Move opportunity to PL_PROD / P10 (Production Scheduled)
- Idempotent: skip if already at P10+
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "move-prod-p05-p10-install-scheduled"
SUPPORTS_WRITE = True  # this handler can execute its decision when writes are enabled

# GHL pipeline/stage IDs (read from /opportunities/pipelines on 2026-06-12)
PIPELINE_ID_PROD = "88V9uYY6visCrtI9V0NR"
STAGE_ID_P05 = "c98f59ed-7b38-4dd6-ae64-01c5a6537894"
STAGE_ID_P10 = "7a4f2d75-f033-4971-8eed-8ca4285e639e"

STAGES_AFTER_P10: set[str] = {
    "ebef66b1-a570-412c-93b3-1be988d6a33f",  # P20
    "96f19b6d-4d85-4e66-910f-4a4f071bf9c0",  # P30
    "bb84bafb-5266-4063-b1f6-bc1ef21a0790",  # P40
    "de0bc542-b6a0-4885-b991-18ed02b19fe7",  # P50
}

INPUT_FIELD = "dt_install_scheduled"


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    stage_id = opp.get("pipelineStageId")
    custom = custom_field_map(opp)
    install_value = custom.get(INPUT_FIELD)

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

    if not truthy(install_value):
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"{INPUT_FIELD} is empty; cannot advance to P10",
        }

    return {
        **base,
        "decision": "would_move",
        "target_value": STAGE_ID_P10,
        "reason": (
            f"At P05 with {INPUT_FIELD}={install_value!r} — "
            f"would move to P10 (Production Scheduled)"
        ),
    }


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the P05->P10 move + stamp sys_last_good_* (P10) via the shared writer path."""
    from handlers._writers import move_stage
    return await move_stage(
        opp_data, decision, last_good_stage_code="P10", last_good_pipeline_code="PL_PROD"
    )
