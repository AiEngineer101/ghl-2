"""Handler for WF | Move | Sales -> Production (S50 -> Production / P05).

Spec source: workflow/03-move/sales/move-sales-production-pipeline.md
             + pipelines/sales/handoff-to-production.md (Layer-1)

CROSS-PIPELINE move: when at Handoff To Production (S50) with sys_production_readiness=Yes,
move the opp into the Production pipeline at Ready for Materials (P05). This changes BOTH
pipelineId and pipelineStageId, so execute() writes both (the generic move_stage helper only
sets the stage).

The live GHL workflow adds a 3-minute visibility wait + readiness re-check before crossing;
in the Code OS the re-check is inherent — we re-evaluate readiness on each event, and only
emit would_move while readiness holds.

After the cross, the opp is a Production-pipeline job and is governed by the Production
handlers (and the Production-side Block Production Entry guard re-verifies readiness).

ACTIVE — pipeline-live for Sales (Sales is in the writer's pipeline-allowlist, so the writer
PUTs for EVERY Sales opp; the allowlist check uses the opp's CURRENT pipeline = Sales). The
matching live GHL Sales workflow must be Drafted to avoid double-driving.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, unwrap_opportunity, yes

HANDLER_ID = "move-sales-s50-production-pipeline"
SUPPORTS_WRITE = True  # active; pipeline-live for Sales via writer allowlist

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
PIPELINE_ID_PROD = "88V9uYY6visCrtI9V0NR"
STAGE_ID_S50 = "ee57c6b2-0613-4a49-b5ea-0b2185a0b70c"  # Sales / Handoff To Production
STAGE_ID_P05 = "c98f59ed-7b38-4dd6-ae64-01c5a6537894"  # Production / Ready for Materials

SYS_PRODUCTION_READINESS = "sys_production_readiness"


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

    # Once crossed into Production (or any non-Sales pipeline), nothing to do here.
    if pipeline_id != PIPELINE_ID_SALES:
        return {**base, "decision": "no_op",
                "reason": f"pipelineId {pipeline_id!r} is not Sales (already crossed / N/A)"}

    if stage_id != STAGE_ID_S50:
        return {**base, "decision": "no_op",
                "reason": f"Stage {stage_id!r} is not S50 (Handoff To Production)"}

    if yes(custom.get(SYS_PRODUCTION_READINESS)):
        return {**base, "decision": "would_move", "target_value": STAGE_ID_P05,
                "reason": (f"{SYS_PRODUCTION_READINESS}=Yes at S50 — would cross to Production / "
                           f"P05 (Ready for Materials)")}

    return {**base, "decision": "skip_condition_unmet",
            "reason": f"holds at S50; {SYS_PRODUCTION_READINESS} is not Yes (cross re-check fails)"}


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Cross-pipeline write: set BOTH pipelineId (Production) and pipelineStageId (P05).

    Only called when decision is would_move AND the writer allows this opp.
    """
    from ghl_writer import writer

    if decision.get("decision") != "would_move":
        return {"executed": False, "reason": "decision is not would_move"}

    opp = unwrap_opportunity({"opportunity": opp_data})
    opp_id = opp.get("id")
    current_pipeline_id = opp.get("pipelineId")  # Sales — used for the writer allowlist check
    if not opp_id:
        return {"executed": False, "reason": "missing opp_id"}

    updates: dict[str, Any] = {"pipelineId": PIPELINE_ID_PROD, "pipelineStageId": STAGE_ID_P05}

    # The opp is now a Production job — stamp the Production last-good codes (PL_PROD / P05),
    # matching what the Production movers write, not the Sales codes.
    from handlers._writers import _last_good_custom_fields
    cfs = await _last_good_custom_fields("P05", "PL_PROD")
    if cfs:
        updates["customFields"] = cfs

    response = await writer.update_opportunity(
        opp_id, current_pipeline_id, updates, handler_id=HANDLER_ID
    )
    return {"executed": True, "response": response, "applied": updates}
