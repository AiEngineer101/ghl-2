"""Handler for WF | Move | Sales | Handoff To Production (S46->S50).

Spec source: workflow/03-move/sales/move-sales-handoff-to-production-stage.md
             + pipelines/sales/handoff-to-production.md (Layer-1)

When sys_production_readiness flips to Yes, move Initial Funding Received (S46) ->
Handoff To Production (S50). S50 is a brief visibility stage before the cross-pipeline
move to Production (handled by move-sales-s50-production-pipeline).

sys_production_readiness is a DERIVED rollup (all job-type prerequisites) — computed by a
live GHL derived workflow today; we READ it. (Building the Python computer for it is a
separate, larger follow-up.)

ACTIVE — pipeline-live for Sales (Sales is in the writer's pipeline-allowlist, so the writer
PUTs for EVERY Sales opp). The matching live GHL Sales workflow must be Drafted to avoid
double-driving.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, unwrap_opportunity, yes

HANDLER_ID = "move-sales-s46-s50-handoff-to-production"
SUPPORTS_WRITE = True  # active; pipeline-live for Sales via writer allowlist

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
STAGE_ID_S46 = "4ced8cf3-6088-4a6b-92f6-73a6f56a030f"  # Initial Funding Received
STAGE_ID_S50 = "ee57c6b2-0613-4a49-b5ea-0b2185a0b70c"  # Handoff To Production

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

    if pipeline_id != PIPELINE_ID_SALES:
        return {**base, "decision": "no_op",
                "reason": f"pipelineId {pipeline_id!r} is not Sales ({PIPELINE_ID_SALES})"}

    if stage_id == STAGE_ID_S50:
        return {**base, "decision": "skip_idempotent",
                "reason": "Already at S50 (Handoff To Production); no advancement needed"}

    if stage_id != STAGE_ID_S46:
        return {**base, "decision": "no_op",
                "reason": f"Stage {stage_id!r} is not S46 (Initial Funding Received)"}

    if yes(custom.get(SYS_PRODUCTION_READINESS)):
        return {**base, "decision": "would_move", "target_value": STAGE_ID_S50,
                "reason": (f"{SYS_PRODUCTION_READINESS}=Yes — would move to S50 "
                           f"(Handoff To Production)")}

    return {**base, "decision": "skip_condition_unmet",
            "reason": f"holds at S46; {SYS_PRODUCTION_READINESS} is not Yes"}


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the S46->S50 move via the GHL writer. Inert unless writer allows the opp."""
    from handlers._writers import move_stage
    from handlers.sales_stages import LAST_GOOD_PIPELINE_CODE
    return await move_stage(
        opp_data, decision,
        last_good_stage_code="S50", last_good_pipeline_code=LAST_GOOD_PIPELINE_CODE,
    )
