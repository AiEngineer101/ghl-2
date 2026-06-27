"""Shadow handler for WF | Move | Prod | P30->P40 Closeout Pending.

Spec source: workflow/03-move/production/move-prod-p30-p40-closeout-pending.md
- Trigger (live): Opportunity Changed, "Stage moved to: Production / P30 Job Completed"
- IF: Pipeline=Production AND Stage=P30
- DO: Move to PL_PROD / P40 (Closeout Pending)
- Idempotent: skip if already at P40 or beyond
- Note: the spec's "wait 3 minutes" is a GHL visibility delay only; the code move is
  unconditional once the opp is at P30.

ACTIVE writer (cut over 2026-06-21). The live "Move P30->P40" GHL workflow must be
set to Draft so the two don't double-drive.
"""
from __future__ import annotations

from typing import Any

from handlers._common import unwrap_opportunity

HANDLER_ID = "move-prod-p30-p40-closeout-pending"
SUPPORTS_WRITE = True  # ACTIVE (cut over 2026-06-21)

# GHL pipeline/stage IDs
PIPELINE_ID_PROD = "88V9uYY6visCrtI9V0NR"
STAGE_ID_P30 = "96f19b6d-4d85-4e66-910f-4a4f071bf9c0"
STAGE_ID_P40 = "bb84bafb-5266-4063-b1f6-bc1ef21a0790"
STAGE_ID_P50 = "de0bc542-b6a0-4885-b991-18ed02b19fe7"

STAGES_AT_OR_AFTER_P40: set[str] = {STAGE_ID_P40, STAGE_ID_P50}


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    stage_id = opp.get("pipelineStageId")

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

    if stage_id in STAGES_AT_OR_AFTER_P40:
        return {
            **base,
            "decision": "skip_idempotent",
            "reason": "Already at or beyond P40; no advancement needed",
        }

    if stage_id != STAGE_ID_P30:
        return {
            **base,
            "decision": "no_op",
            "reason": f"Stage {stage_id!r} is not P30",
        }

    return {
        **base,
        "decision": "would_move",
        "target_value": STAGE_ID_P40,
        "reason": "At P30 (Job Completed) — would move to P40 (Closeout Pending)",
    }


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the P30->P40 move + stamp sys_last_good_* (P40) via the shared writer path."""
    from handlers._writers import move_stage
    return await move_stage(
        opp_data, decision, last_good_stage_code="P40", last_good_pipeline_code="PL_PROD"
    )
