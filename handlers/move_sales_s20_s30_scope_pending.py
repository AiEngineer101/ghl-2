"""Shadow handler for WF | Move | Sales | S20->S30 (Inspection Complete -> Scope Pending).

Spec sources:
  - workflow/03-move/sales/move-sales-inspection-complete-scope-pending.md (ACTIVE, Insurance/Hybrid)
  - pipelines/sales/inspection-complete.md (Layer-1, authority — job-type-conditional mover)
  - workflow/03-move/sales/move-sales-s20-s30-start-numbers-stage.md (DRAFTED/superseded — the
    old timed auto-mover; we do NOT replicate it)

Job-type-conditional advance from Inspection Complete (S20) to Scope Pending / Build Estimate (S30):
  - Retail           -> advance immediately. Retail does not wait for carrier scope (Layer-1 §4:
                        "Inspection Complete is a transient checkpoint, not a wait state").
  - Insurance/Hybrid -> advance only when dt_insurance_scope_received is stamped (the carrier-scope
                        hold point). Move on the durable DT, never raw ev_insurance_scope_doc.
  - Unknown/missing job type -> HOLD (skip_condition_unmet); we will not advance a job whose branch
                        we cannot determine.

Design note: the live GHL build splits this into a Drafted timed mover (Retail double-move) plus an
active Insurance/Hybrid scope mover. In the Code OS we collapse both into one job-type-conditional
mover keyed off durable truth — simpler and it cannot auto-advance Insurance/Hybrid past the hold.

SHADOW (SUPPORTS_WRITE=False) — Sales watch-only until a test harness exists.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "move-sales-s20-s30-scope-pending"
SUPPORTS_WRITE = False  # shadow-first

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
STAGE_ID_S20 = "f66b7a47-61a0-4527-8c23-0b9810e482bc"  # Inspection Complete
STAGE_ID_S30 = "846fb074-d25d-4e31-a76e-a38b23e4e09c"  # Scope Pending / Build Estimate

# All Sales stages at or beyond S30 — idempotency guard (never re-advance).
STAGES_AT_OR_AFTER_S30: set[str] = {
    STAGE_ID_S30,
    "d270f2b4-d14e-4bff-813f-ed02e9e21d10",  # S40 Job Pending Approval
    "7d1d1248-8de5-43f0-8876-c9bc23b3b51e",  # S45 Approved — Funding Pending
    "4ced8cf3-6088-4a6b-92f6-73a6f56a030f",  # S46 Initial Funding Received
    "ee57c6b2-0613-4a49-b5ea-0b2185a0b70c",  # S50 Handoff To Production
}

JOB_TYPE_FIELD = "seg_job_type"
DT_INSURANCE_SCOPE = "dt_insurance_scope_received"

JOB_TYPE_RETAIL = "retail"
JOB_TYPE_INSURANCE = "insurance"
JOB_TYPE_HYBRID = "hybrid"
SCOPE_REQUIRED_TYPES = {JOB_TYPE_INSURANCE, JOB_TYPE_HYBRID}


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

    if stage_id in STAGES_AT_OR_AFTER_S30:
        return {
            **base,
            "decision": "skip_idempotent",
            "reason": "Already at or beyond S30; no advancement needed",
        }

    if stage_id != STAGE_ID_S20:
        return {
            **base,
            "decision": "no_op",
            "reason": f"Stage {stage_id!r} is not S20 (Inspection Complete)",
        }

    # Retail: transient checkpoint, advance immediately (no carrier scope required).
    if job_type == JOB_TYPE_RETAIL:
        return {
            **base,
            "decision": "would_move",
            "target_value": STAGE_ID_S30,
            "reason": "Retail at S20 — no carrier scope required; would move to S30 (Scope Pending)",
        }

    # Insurance / Hybrid: carrier-scope hold. Advance only on the durable scope-received truth.
    if job_type in SCOPE_REQUIRED_TYPES:
        if truthy(custom.get(DT_INSURANCE_SCOPE)):
            return {
                **base,
                "decision": "would_move",
                "target_value": STAGE_ID_S30,
                "reason": (
                    f"{job_type.title()} at S20 with {DT_INSURANCE_SCOPE} stamped — "
                    f"would move to S30 (Scope Pending)"
                ),
            }
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": (
                f"{job_type.title()} job holds at S20 for carrier scope; "
                f"{DT_INSURANCE_SCOPE} is empty"
            ),
        }

    # Unknown / missing job type — do not advance a job whose branch we can't determine.
    return {
        **base,
        "decision": "skip_condition_unmet",
        "reason": f"{JOB_TYPE_FIELD} is missing/unrecognized (value={job_type!r}); holding at S20",
    }


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the S20->S30 move via the GHL writer. Inert while SUPPORTS_WRITE=False."""
    from handlers._writers import move_stage
    return await move_stage(opp_data, decision)
