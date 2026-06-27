"""Shadow handler for WF | Move | Sales | S30->S40 Job Pending Approval.

Spec source: workflow/03-move/sales/move-sales-s30-s40-job-pending-approval.md

Advance Scope Pending / Build Estimate (S30) -> Job Pending Approval (S40) once the
job-type-specific truth is present:
  - Retail     -> dt_estimate_presented present
  - Insurance  -> dt_insurance_scope_received present
  - Hybrid     -> BOTH dt_estimate_presented AND dt_insurance_scope_received present
  - unknown/missing truth -> hold at S30

DESIGN NOTE — no estimate-presented gate handler here:
  dt_estimate_presented is stamped by a GHL "Documents & Contracts (Sent)" event
  (gate-estimate-presented-dc.md), NOT an Opportunity-Changed custom-field update. Our
  service only receives Opportunity Changed webhooks, so it never sees the D&C send event
  and cannot stamp this date itself. We READ dt_estimate_presented (stamped by the live GHL
  D&C gate) and gate the move on it. dt_insurance_scope_received comes from our own
  gate-insurance-scope (slice 2) or the live GHL gate.

ACTIVE — pipeline-live for Sales (cut over to pipeline-wide writes after live validation).
SUPPORTS_WRITE=True and the Sales pipeline is in the writer's pipeline-allowlist
(settings.write_allowed_pipeline_ids), so the writer PUTs for EVERY Sales opp. The matching
live GHL Sales workflow must be Drafted so it doesn't double-drive this move.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "move-sales-s30-s40-job-pending-approval"
SUPPORTS_WRITE = True  # active, but writer enforces the per-opp allowlist

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
STAGE_ID_S30 = "846fb074-d25d-4e31-a76e-a38b23e4e09c"  # Scope Pending / Build Estimate
STAGE_ID_S40 = "d270f2b4-d14e-4bff-813f-ed02e9e21d10"  # Job Pending Approval

# All Sales stages at or beyond S40 — idempotency guard (never re-advance).
STAGES_AT_OR_AFTER_S40: set[str] = {
    STAGE_ID_S40,
    "7d1d1248-8de5-43f0-8876-c9bc23b3b51e",  # S45 Approved — Funding Pending
    "4ced8cf3-6088-4a6b-92f6-73a6f56a030f",  # S46 Initial Funding Received
    "ee57c6b2-0613-4a49-b5ea-0b2185a0b70c",  # S50 Handoff To Production
}

JOB_TYPE_FIELD = "seg_job_type"
DT_ESTIMATE = "dt_estimate_presented"
DT_INSURANCE_SCOPE = "dt_insurance_scope_received"

JOB_TYPE_RETAIL = "retail"
JOB_TYPE_INSURANCE = "insurance"
JOB_TYPE_HYBRID = "hybrid"


def _job_type(value: Any) -> str:
    """Normalize seg_job_type to a lowercase scalar ("", "retail", "insurance", "hybrid")."""
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return ""
    return str(value).strip().lower()


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    stage_id = opp.get("pipelineStageId")
    custom = custom_field_map(opp)
    job_type = _job_type(custom.get(JOB_TYPE_FIELD))
    has_estimate = truthy(custom.get(DT_ESTIMATE))
    has_scope = truthy(custom.get(DT_INSURANCE_SCOPE))

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

    if stage_id in STAGES_AT_OR_AFTER_S40:
        return {
            **base,
            "decision": "skip_idempotent",
            "reason": "Already at or beyond S40; no advancement needed",
        }

    if stage_id != STAGE_ID_S30:
        return {
            **base,
            "decision": "no_op",
            "reason": f"Stage {stage_id!r} is not S30 (Scope Pending / Build Estimate)",
        }

    # Determine which truths this job type requires, then check them.
    if job_type == JOB_TYPE_RETAIL:
        required = {DT_ESTIMATE: has_estimate}
    elif job_type == JOB_TYPE_INSURANCE:
        required = {DT_INSURANCE_SCOPE: has_scope}
    elif job_type == JOB_TYPE_HYBRID:
        required = {DT_ESTIMATE: has_estimate, DT_INSURANCE_SCOPE: has_scope}
    else:
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"{JOB_TYPE_FIELD} is missing/unrecognized (value={job_type!r}); holding at S30",
        }

    missing = [field for field, present in required.items() if not present]
    if missing:
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"{job_type.title()} job holds at S30; missing: {', '.join(missing)}",
        }

    return {
        **base,
        "decision": "would_move",
        "target_value": STAGE_ID_S40,
        "reason": (
            f"{job_type.title()} at S30 with required truth present "
            f"({', '.join(required)}) — would move to S40 (Job Pending Approval)"
        ),
    }


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the S30->S40 move via the GHL writer (write gated by the writer allowlist)."""
    from handlers._writers import move_stage
    from handlers.sales_stages import LAST_GOOD_PIPELINE_CODE
    return await move_stage(
        opp_data, decision,
        last_good_stage_code="S40", last_good_pipeline_code=LAST_GOOD_PIPELINE_CODE,
    )
