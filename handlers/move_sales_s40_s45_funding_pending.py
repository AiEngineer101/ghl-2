"""Shadow handler for WF | Move | Sales | Approvals Complete -> Funding Pending (S40->S45/S46).

Spec source: workflow/03-move/sales/move-sales-approvals-complete-funding-pending.md

De-branched (Build Log §20/§21): ONE universal contract truth, no job-type fork. Leave
Job Pending Approval (S40) the moment dt_signed_contract_received is stamped. Target depends
on whether initial funding is already in:
  - funding already in (dt_ins_deductible_received OR dt_retail_deposit_proof_received present)
        -> skip straight to Initial Funding Received (S46)
  - otherwise
        -> Approved — Funding Pending (S45)
  - no signed contract -> hold at S40

NOTE: dt_signed_contract_received is stamped by the universal SignedContract gate (D&C "signed"
event + fallback upload), not by us — we READ it. UI label is "Contract Received Date"
(confirm the key resolves on first live validation).

ACTIVE — pipeline-live for Sales (the Sales pipeline is in the writer's pipeline-allowlist, so
the writer PUTs for EVERY Sales opp). The matching live GHL Sales workflow must be Drafted so it
doesn't double-drive this move. The S45 bounce-back guard is Drafted/possibly-deprecated per
spec — intentionally NOT built.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "move-sales-s40-s45-funding-pending"
SUPPORTS_WRITE = True  # active; pipeline-live for Sales via writer allowlist

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
STAGE_ID_S40 = "d270f2b4-d14e-4bff-813f-ed02e9e21d10"  # Job Pending Approval
STAGE_ID_S45 = "7d1d1248-8de5-43f0-8876-c9bc23b3b51e"  # Approved — Funding Pending
STAGE_ID_S46 = "4ced8cf3-6088-4a6b-92f6-73a6f56a030f"  # Initial Funding Received

# Sales stages at or beyond S45 — idempotency guard (never re-advance).
STAGES_AT_OR_AFTER_S45: set[str] = {
    STAGE_ID_S45,
    STAGE_ID_S46,
    "ee57c6b2-0613-4a49-b5ea-0b2185a0b70c",  # S50 Handoff To Production
}

DT_CONTRACT = "dt_signed_contract_received"
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
        return {
            **base,
            "decision": "no_op",
            "reason": f"pipelineId {pipeline_id!r} is not Sales ({PIPELINE_ID_SALES})",
        }

    if stage_id in STAGES_AT_OR_AFTER_S45:
        return {
            **base,
            "decision": "skip_idempotent",
            "reason": "Already at or beyond S45; no advancement needed",
        }

    if stage_id != STAGE_ID_S40:
        return {
            **base,
            "decision": "no_op",
            "reason": f"Stage {stage_id!r} is not S40 (Job Pending Approval)",
        }

    if not truthy(custom.get(DT_CONTRACT)):
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"holds at S40; universal contract truth {DT_CONTRACT} is empty",
        }

    # Contract signed. Skip to S46 if initial funding is already in, else land at S45.
    funding_in = truthy(custom.get(DT_INS_DEDUCTIBLE)) or truthy(custom.get(DT_RETAIL_DEPOSIT))
    if funding_in:
        return {
            **base,
            "decision": "would_move",
            "target_value": STAGE_ID_S46,
            "reason": (
                f"{DT_CONTRACT} present and initial funding already in "
                f"({DT_INS_DEDUCTIBLE} or {DT_RETAIL_DEPOSIT}) — "
                f"would skip to S46 (Initial Funding Received)"
            ),
        }
    return {
        **base,
        "decision": "would_move",
        "target_value": STAGE_ID_S45,
        "reason": (
            f"{DT_CONTRACT} present, no initial funding yet — "
            f"would move to S45 (Approved — Funding Pending)"
        ),
    }


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the S40->S45/S46 move via the GHL writer (write gated by the writer allowlist)."""
    from handlers._writers import move_stage
    from handlers.sales_stages import LAST_GOOD_PIPELINE_CODE, stage_code_for
    # Target is S45 or S46 depending on whether funding was already in — derive the code.
    code = stage_code_for(decision.get("target_value"))
    return await move_stage(
        opp_data, decision,
        last_good_stage_code=code, last_good_pipeline_code=LAST_GOOD_PIPELINE_CODE,
    )
