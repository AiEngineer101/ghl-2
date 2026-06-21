"""Shadow handler for WF | Move | Prod | P30->P40 Closeout Pending.

Spec source: workflow/03-move/production/move-prod-p30-p40-closeout-pending.md
- Trigger (live): Opportunity Changed, "Stage moved to: Production / P30 Job Completed"
- IF: Pipeline=Production AND Stage=P30
- DO: Move to PL_PROD / P40 (Closeout Pending)
- Idempotent: skip if already at P40 or beyond
- Note: the spec's "wait 3 minutes" is a GHL visibility delay only; the code move is
  unconditional once the opp is at P30.

Shadow-only for now (SUPPORTS_WRITE=False). Cut over to active writes once parity is
confirmed AND the live "Move P30->P40" GHL workflow is set to Draft.
"""
from __future__ import annotations

from typing import Any

from handlers._common import unwrap_opportunity

HANDLER_ID = "move-prod-p30-p40-closeout-pending"
SUPPORTS_WRITE = False  # shadow-only until cutover

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
    """Perform the P30->P40 move and stamp sys_last_good_* via the GHL writer."""
    from ghl_client import ghl
    from ghl_writer import writer

    if decision.get("decision") != "would_move":
        return {"executed": False, "reason": "decision is not would_move"}

    opp = unwrap_opportunity({"opportunity": opp_data})
    opp_id = opp.get("id")
    pipeline_id = opp.get("pipelineId")
    if not opp_id:
        return {"executed": False, "reason": "missing opp_id"}

    id_to_key = await ghl.get_opportunity_field_key_map()
    key_to_id = {v: k for k, v in id_to_key.items()}
    custom_fields = []
    for key, value in (
        ("sys_last_good_pipeline_code", "PL_PROD"),
        ("sys_last_good_stage_code", "P40"),
    ):
        fid = key_to_id.get(key)
        if fid:
            custom_fields.append({"id": fid, "field_value": value})

    updates: dict[str, Any] = {"pipelineStageId": STAGE_ID_P40}
    if custom_fields:
        updates["customFields"] = custom_fields

    response = await writer.update_opportunity(opp_id, pipeline_id, updates)
    return {"executed": True, "response": response, "applied": updates}
