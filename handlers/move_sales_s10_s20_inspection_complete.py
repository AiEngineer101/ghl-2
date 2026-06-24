"""Shadow handler for WF | Move | Sales | S10->S20 Inspection Complete.

Spec source: workflow/03-move/sales/move-sales-s10-s20-inspection-complete.md
             + pipelines/sales/inspection-booked.md (Layer-1, authority)

- Trigger (live): Opportunity Changed.
- Move Inspection Booked (S10) -> Inspection Complete (S20).

SPEC DISCREPANCY (resolved in favor of Layer-1, the newer authority):
  The older move spec's IF reads raw `tf_inspection_completed=Yes AND
  ev_front_of_home_inspection_photo is not empty`. The Layer-1 doc (§4) is explicit:
  "Do not move only from raw ev presence" — the mover keys on the two DURABLE truths:
      dt_inspection_completed              (stamped by gate-inspection-complete)
      dt_front_of_home_inspection_photo_received  (stamped by gate-front-home-photo)
  Both being present guarantees the photo was proven, not merely uploaded. We follow
  Layer-1. (Same one-event-lag model as the Production movers: the gate stamps the DT,
  the next Opportunity Changed event fires the move.)

ACTIVE — but writes are gated per-opp. SUPPORTS_WRITE=True means execute() runs, but the
writer (write_guard.is_write_allowed) only actually PUTs when the opp is in the opp-allowlist
(settings.write_allowed_opp_ids) OR its pipeline is allowlisted. Sales is NOT pipeline-
allowlisted, so this mover only moves the scoped test opp(s); every other live Sales deal is
blocked at the writer. This is the first Sales write path — keep the opp-allowlist tight.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "move-sales-s10-s20-inspection-complete"
SUPPORTS_WRITE = True  # active, but writer enforces the per-opp allowlist

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
STAGE_ID_S10 = "7358ceec-e07a-405f-a3c6-f9597a1ddf0d"  # Inspection Booked
STAGE_ID_S20 = "f66b7a47-61a0-4527-8c23-0b9810e482bc"  # Inspection Complete

# All Sales stages at or beyond S20 — used to enforce idempotency (never re-advance).
STAGES_AT_OR_AFTER_S20: set[str] = {
    STAGE_ID_S20,
    "846fb074-d25d-4e31-a76e-a38b23e4e09c",  # S30 Scope Pending / Build Estimate
    "d270f2b4-d14e-4bff-813f-ed02e9e21d10",  # S40 Job Pending Approval
    "7d1d1248-8de5-43f0-8876-c9bc23b3b51e",  # S45 Approved — Funding Pending
    "4ced8cf3-6088-4a6b-92f6-73a6f56a030f",  # S46 Initial Funding Received
    "ee57c6b2-0613-4a49-b5ea-0b2185a0b70c",  # S50 Handoff To Production
}

DT_INSPECTION = "dt_inspection_completed"
DT_FRONT_PHOTO = "dt_front_of_home_inspection_photo_received"


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

    if stage_id in STAGES_AT_OR_AFTER_S20:
        return {
            **base,
            "decision": "skip_idempotent",
            "reason": "Already at or beyond S20; no advancement needed",
        }

    if stage_id != STAGE_ID_S10:
        return {
            **base,
            "decision": "no_op",
            "reason": f"Stage {stage_id!r} is not S10 (Inspection Booked)",
        }

    missing = []
    if not truthy(custom.get(DT_INSPECTION)):
        missing.append(DT_INSPECTION)
    if not truthy(custom.get(DT_FRONT_PHOTO)):
        missing.append(DT_FRONT_PHOTO)
    if missing:
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"durable inspection truth not complete; missing: {', '.join(missing)}",
        }

    return {
        **base,
        "decision": "would_move",
        "target_value": STAGE_ID_S20,
        "reason": (
            f"At S10 with {DT_INSPECTION} and {DT_FRONT_PHOTO} both stamped — "
            f"would move to S20 (Inspection Complete)"
        ),
    }


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the S10->S20 move via the GHL writer. Inert while SUPPORTS_WRITE=False."""
    from handlers._writers import move_stage
    return await move_stage(opp_data, decision)
