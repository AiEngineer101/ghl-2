"""Handler for WF | Move | Prod | P40->P50 Closeout Complete.

Spec source: workflow/03-move/production/move-prod-p40-p50-closeout-complete.md
- Trigger (live): Opportunity Changed on any closeout input (docs / payment / permit / CO).
- IF: Pipeline=Production AND Stage=P40 AND closeout readiness holds.
- DO: Move to PL_PROD / P50 (Closeout Complete; renamed from "Closed Won" per CR-0026).
- Idempotent: skip if already at P50.

Readiness is recomputed here from the raw proof (via derived-closeout-ready's
closeout_readiness) so the move fires in the SAME event the final proof is entered,
instead of waiting for the sys_closeout_ready flag to be written and echoed back by GHL
(which it doesn't reliably do — leaving jobs stuck at Closeout Pending with everything
already satisfied). Same self-checking pattern the enforcer's P50 guardrail uses.

ACTIVE writer (cut over 2026-06-21). The live "Move P40->P50" GHL workflow must be
set to Draft so the two don't double-drive.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, unwrap_opportunity

HANDLER_ID = "move-prod-p40-p50-closeout-complete"
SUPPORTS_WRITE = True  # ACTIVE (cut over 2026-06-21)

# GHL pipeline/stage IDs
PIPELINE_ID_PROD = "88V9uYY6visCrtI9V0NR"
STAGE_ID_P40 = "bb84bafb-5266-4063-b1f6-bc1ef21a0790"
STAGE_ID_P50 = "de0bc542-b6a0-4885-b991-18ed02b19fe7"

# Still computed by derived-closeout-ready (for tags/reporting); the move no longer depends on it.
INPUT_FIELD_CLOSEOUT_READY = "sys_closeout_ready"


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

    # Recompute readiness from the raw proof in THIS event (docs + cash-from-amounts + permit
    # + change order) rather than reading the stored sys_closeout_ready flag. That flag is
    # written by a separate handler on a prior event, and the move would only fire once GHL
    # sent one MORE event after it flipped to Yes — which it doesn't reliably do, leaving jobs
    # stuck at Closeout Pending with everything satisfied. Self-checking here closes the job in
    # the same event the last proof lands.
    from handlers.derived_closeout_ready import closeout_readiness

    ready, missing = closeout_readiness(custom)
    if not ready:
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"closeout not ready — still missing: {', '.join(missing)}",
        }

    return {
        **base,
        "decision": "would_move",
        "target_value": STAGE_ID_P50,
        "reason": "At P40 and all closeout proof present — would move to P50 (Closeout Complete)",
    }


MILESTONE_TAGS = ["milestone — closeout complete", "milestone — review requested"]


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the P40->P50 move + stamp sys_last_good_* (P50) + add milestone tags."""
    from handlers._writers import add_contact_tags, move_stage

    result = await move_stage(
        opp_data, decision, last_good_stage_code="P50", last_good_pipeline_code="PL_PROD"
    )
    if result.get("executed"):
        tag_result = await add_contact_tags(opp_data, MILESTONE_TAGS, handler_id=HANDLER_ID)
        result["tags"] = tag_result
    return result
