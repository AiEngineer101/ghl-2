"""Shadow handler for WF | Move | Prod | P40->P50 Closeout Complete.

Spec source: workflow/03-move/production/move-prod-p40-p50-closeout-complete.md
- Trigger (live): Opportunity Changed, "Custom field updated: sys_closeout_ready"
- IF: Pipeline=Production AND Stage=P40 AND sys_closeout_ready=Yes
- DO: Move to PL_PROD / P50 (Closeout Complete; renamed from "Closed Won" per CR-0026)
- Idempotent: skip if already at P50

sys_closeout_ready is computed by the `derived-closeout-ready` handler.

ACTIVE writer (cut over 2026-06-21). The live "Move P40->P50" GHL workflow must be
set to Draft so the two don't double-drive.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, unwrap_opportunity, yes

HANDLER_ID = "move-prod-p40-p50-closeout-complete"
SUPPORTS_WRITE = True  # ACTIVE (cut over 2026-06-21)

# GHL pipeline/stage IDs
PIPELINE_ID_PROD = "88V9uYY6visCrtI9V0NR"
STAGE_ID_P40 = "bb84bafb-5266-4063-b1f6-bc1ef21a0790"
STAGE_ID_P50 = "de0bc542-b6a0-4885-b991-18ed02b19fe7"

INPUT_FIELD_CLOSEOUT_READY = "sys_closeout_ready"


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    stage_id = opp.get("pipelineStageId")
    custom = custom_field_map(opp)
    closeout_ready = custom.get(INPUT_FIELD_CLOSEOUT_READY)

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

    if stage_id == STAGE_ID_P50:
        return {
            **base,
            "decision": "skip_idempotent",
            "reason": "Already at P50 (Closeout Complete); no advancement needed",
        }

    if stage_id != STAGE_ID_P40:
        return {
            **base,
            "decision": "no_op",
            "reason": f"Stage {stage_id!r} is not P40",
        }

    if not yes(closeout_ready):
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"{INPUT_FIELD_CLOSEOUT_READY} != Yes (value={closeout_ready!r})",
        }

    return {
        **base,
        "decision": "would_move",
        "target_value": STAGE_ID_P50,
        "reason": (
            f"At P40 with {INPUT_FIELD_CLOSEOUT_READY}=Yes — "
            f"would move to P50 (Closeout Complete)"
        ),
    }


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the P40->P50 move + stamp sys_last_good_* (P50) via the shared writer path."""
    from handlers._writers import move_stage
    return await move_stage(
        opp_data, decision, last_good_stage_code="P50", last_good_pipeline_code="PL_PROD"
    )
