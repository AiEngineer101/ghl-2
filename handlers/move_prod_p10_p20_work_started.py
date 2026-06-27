"""Shadow handler for WF | Move | Prod | P10->P20 Work Started.

Spec source: workflow/03-move/production/move-prod-p10-p20-work-started.md
- Trigger (live): Opportunity Changed, "Custom field updated: tf_work_started"
- IF: Pipeline=Production AND Stage in {P05,P10} AND tf_work_started=Yes
      AND (seg_stop_work_status empty OR in {Clear..., Resolved...})
- DO: Move to PL_PROD / P20 (Job In Progress)
- Idempotent: skip if already at P20 or beyond

Active writer — SUPPORTS_WRITE=True. The live GHL workflow
`WF | Move | Prod | P10→P20 Work Started` should be set to Draft so this
handler is the sole mover. The P20 stage-gate guard
`WF | Stage Gate | Prod P20 Requires Work Started` stays Published and
will bounce any move-to-P20 where tf_work_started != Yes. Since this
handler also requires tf_work_started=Yes before issuing would_move, the
two agree.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "move-prod-p10-p20-work-started"
SUPPORTS_WRITE = True  # active writer

# GHL pipeline/stage IDs
PIPELINE_ID_PROD = "88V9uYY6visCrtI9V0NR"
STAGE_ID_P05 = "c98f59ed-7b38-4dd6-ae64-01c5a6537894"
STAGE_ID_P10 = "7a4f2d75-f033-4971-8eed-8ca4285e639e"
STAGE_ID_P20 = "ebef66b1-a570-412c-93b3-1be988d6a33f"

ELIGIBLE_FROM_STAGES: set[str] = {STAGE_ID_P05, STAGE_ID_P10}
STAGES_AT_OR_AFTER_P20: set[str] = {
    STAGE_ID_P20,
    "96f19b6d-4d85-4e66-910f-4a4f071bf9c0",  # P30
    "bb84bafb-5266-4063-b1f6-bc1ef21a0790",  # P40
    "de0bc542-b6a0-4885-b991-18ed02b19fe7",  # P50
}

INPUT_FIELD_WORK_STARTED = "tf_work_started"
INPUT_FIELD_STOP_WORK = "seg_stop_work_status"

# Per spec, these seg_stop_work_status values do NOT block the move.
# Anything else (e.g., "Active", "Blocked", "Pending Resolution") blocks.
STOP_WORK_NON_BLOCKING: set[str] = {
    "Clear — Work Can Proceed",
    "Resolved — Work Can Proceed",
}


def _yes(value: Any) -> bool:
    """Return True if a truth-flag field equals Yes.

    GHL stores Yes/No fields variably: as the string "Yes", as the list ["Yes"], or
    sometimes case-shifted. Be tolerant.
    """
    if value is None:
        return False
    if isinstance(value, list):
        return any(_yes(v) for v in value)
    return str(value).strip().lower() == "yes"


def _stop_work_blocks(value: Any) -> tuple[bool, str]:
    """Return (is_blocking, display_value)."""
    if value is None:
        return False, ""
    if isinstance(value, list):
        # Coerce list to its first non-empty element for the check.
        for v in value:
            if v not in (None, ""):
                value = v
                break
        else:
            return False, ""
    s = str(value).strip()
    if not s:
        return False, s
    if s in STOP_WORK_NON_BLOCKING:
        return False, s
    return True, s


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    stage_id = opp.get("pipelineStageId")
    custom = custom_field_map(opp)
    work_started = custom.get(INPUT_FIELD_WORK_STARTED)
    stop_work = custom.get(INPUT_FIELD_STOP_WORK)

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

    if stage_id in STAGES_AT_OR_AFTER_P20:
        return {
            **base,
            "decision": "skip_idempotent",
            "reason": "Already at or beyond P20; no advancement needed",
        }

    if stage_id not in ELIGIBLE_FROM_STAGES:
        return {
            **base,
            "decision": "no_op",
            "reason": f"Stage {stage_id!r} not in eligible source stages (P05, P10)",
        }

    if not _yes(work_started):
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": f"{INPUT_FIELD_WORK_STARTED} != Yes (value={work_started!r})",
        }

    blocked, sw_value = _stop_work_blocks(stop_work)
    if blocked:
        return {
            **base,
            "decision": "skip_blocked",
            "reason": (
                f"{INPUT_FIELD_STOP_WORK}={sw_value!r} is not in non-blocking set "
                f"{sorted(STOP_WORK_NON_BLOCKING)}"
            ),
        }

    from_stage_label = "P05" if stage_id == STAGE_ID_P05 else "P10"
    return {
        **base,
        "decision": "would_move",
        "target_value": STAGE_ID_P20,
        "reason": (
            f"At {from_stage_label} with {INPUT_FIELD_WORK_STARTED}=Yes and "
            f"stop-work clear — would move to P20 (Job In Progress)"
        ),
    }


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the P10->P20 (or P05->P20) move + stamp sys_last_good_* (P20).

    Uses the shared writer path, which stamps the last-good audit fields with the
    correct GHL `field_value` key (this mover previously used `value`, which GHL
    silently ignored — that was the real "last-good not persisting" bug here).
    """
    from handlers._writers import move_stage
    return await move_stage(
        opp_data, decision, last_good_stage_code="P20", last_good_pipeline_code="PL_PROD"
    )
