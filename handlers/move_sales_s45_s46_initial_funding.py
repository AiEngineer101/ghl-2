"""Handler for WF | Move | Sales | Initial Funding Received (S45->S46).

Spec source: workflow/03-move/sales/move-sales-initial-funding-received-stage.md

Job-type-AGNOSTIC (de-branched 2026-06-08): move Approved — Funding Pending (S45) ->
Initial Funding Received (S46) when initial funding lands — retail deposit OR insurance
deductible. A job advances on its FIRST funding event; hybrid is NOT required to have both.

ACTIVE — pipeline-live for Sales (Sales is in the writer's pipeline-allowlist, so the writer
PUTs for EVERY Sales opp). The matching live GHL Sales workflow must be Drafted to avoid
double-driving.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "move-sales-s45-s46-initial-funding"
SUPPORTS_WRITE = True  # active; pipeline-live for Sales via writer allowlist

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
STAGE_ID_S45 = "7d1d1248-8de5-43f0-8876-c9bc23b3b51e"  # Approved — Funding Pending
STAGE_ID_S46 = "4ced8cf3-6088-4a6b-92f6-73a6f56a030f"  # Initial Funding Received

STAGES_AT_OR_AFTER_S46: set[str] = {
    STAGE_ID_S46,
    "ee57c6b2-0613-4a49-b5ea-0b2185a0b70c",  # S50 Handoff To Production
}

DT_INS_DEDUCTIBLE = "dt_ins_deductible_received"
DT_RETAIL_DEPOSIT = "dt_retail_deposit_proof_received"


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

    if stage_id in STAGES_AT_OR_AFTER_S46:
        return {**base, "decision": "skip_idempotent",
                "reason": "Already at or beyond S46; no advancement needed"}

    if stage_id != STAGE_ID_S45:
        return {**base, "decision": "no_op",
                "reason": f"Stage {stage_id!r} is not S45 (Approved — Funding Pending)"}

    if truthy(custom.get(DT_INS_DEDUCTIBLE)) or truthy(custom.get(DT_RETAIL_DEPOSIT)):
        return {**base, "decision": "would_move", "target_value": STAGE_ID_S46,
                "reason": (f"initial funding landed ({DT_RETAIL_DEPOSIT} or {DT_INS_DEDUCTIBLE}) — "
                           f"would move to S46 (Initial Funding Received)")}

    return {**base, "decision": "skip_condition_unmet",
            "reason": (f"holds at S45; no initial funding yet "
                       f"({DT_RETAIL_DEPOSIT} and {DT_INS_DEDUCTIBLE} both empty)")}


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the S45->S46 move via the GHL writer. Inert unless writer allows the opp."""
    from handlers._writers import move_stage
    from handlers.sales_stages import LAST_GOOD_PIPELINE_CODE
    return await move_stage(
        opp_data, decision,
        last_good_stage_code="S46", last_good_pipeline_code=LAST_GOOD_PIPELINE_CODE,
    )
