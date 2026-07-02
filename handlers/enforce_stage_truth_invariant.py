"""Invariant enforcer: keep stage <= the highest stage whose truth is satisfied.

Closes a real gap in the GHL workflow design. The published stage-gate workflows
(stage-gate-prod-p10/p20/p30-requires-*) only fire on the trigger filter
"Stage moved to <X>" — i.e., on stage TRANSITIONS, not on field-clear events.
That means once an opp has reached P30, if a user/automation later clears
`tf_work_completed`, no GHL workflow walks the opp back. The truth and the
stage drift apart silently.

This handler runs on every Opportunity Changed event in the Production
pipeline. It computes the highest stage whose entry requirement is currently
satisfied, then rewinds the stage if it's higher than that.

Two regimes:
  - P05–P30: a sequential truth ladder (each stage's entry requirement builds on
    the previous). Rewinds to the highest stage whose truth still holds.
  - P50 (Closeout Complete): a single-step readiness guardrail. A job may only rest
    at P50 while closeout readiness is satisfied; if proof is missing (manual/owner
    drag, or proof later broke), bounce it back to P40 (Closeout Pending) and surface
    the missing item. Spec: closeout-complete.md §5, Edge 7 (CR answered by Bill 06-23).
  - P40 (Closeout Pending) is a valid resting stage reached automatically from P30 and
    has no entry-truth gate of its own — it is left alone.

Stage entry requirements (per the live stage-gate specs):
  P10  requires  dt_material_id_report_received is not empty (materials order confirmed)
  P20  requires  tf_work_started   = Yes
  P30  requires  tf_work_completed = Yes
  P05  requires  (nothing — base stage)
  P50  requires  closeout readiness (recomputed from proof fields; → bounce to P40)
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity, yes
from handlers.derived_closeout_ready import closeout_readiness

HANDLER_ID = "enforce-stage-truth-invariant"
SUPPORTS_WRITE = True  # active writer — performs stage rewinds

PIPELINE_ID_PROD = "88V9uYY6visCrtI9V0NR"
STAGE_ID_P05 = "c98f59ed-7b38-4dd6-ae64-01c5a6537894"
STAGE_ID_P10 = "7a4f2d75-f033-4971-8eed-8ca4285e639e"
STAGE_ID_P20 = "ebef66b1-a570-412c-93b3-1be988d6a33f"
STAGE_ID_P30 = "96f19b6d-4d85-4e66-910f-4a4f071bf9c0"
STAGE_ID_P40 = "bb84bafb-5266-4063-b1f6-bc1ef21a0790"
STAGE_ID_P50 = "de0bc542-b6a0-4885-b991-18ed02b19fe7"

# Ordered low-to-high. Each tuple: (stage_id, label, entry_requirement_fn).
# entry_requirement_fn returns (satisfied: bool, reason: str) given the
# customField map. None means no entry requirement (P05 is the base).
STAGE_LADDER: list[tuple[str, str, Any]] = [
    (STAGE_ID_P05, "P05", None),
    (
        STAGE_ID_P10,
        "P10",
        lambda cf: (truthy(cf.get("dt_material_id_report_received")), "dt_material_id_report_received"),
    ),
    (
        STAGE_ID_P20,
        "P20",
        lambda cf: (yes(cf.get("tf_work_started")), "tf_work_started"),
    ),
    (
        STAGE_ID_P30,
        "P30",
        lambda cf: (yes(cf.get("tf_work_completed")), "tf_work_completed"),
    ),
]

# P40 (Closeout Pending) is a valid resting stage with no entry-truth gate — left alone.
# P50 (Closeout Complete) is handled by the dedicated readiness guardrail below.


def _stage_index(stage_id: str) -> int | None:
    for i, (sid, _, _) in enumerate(STAGE_LADDER):
        if sid == stage_id:
            return i
    return None


def _highest_satisfied_index(custom: dict[str, Any]) -> tuple[int, list[str]]:
    """Walk up the ladder; the highest stage whose entry req is satisfied wins.

    Returns (index, list_of_failure_reasons). Failure reasons are the
    requirements that prevented advancement beyond the returned index.
    """
    failures: list[str] = []
    last_ok = 0  # P05 always satisfied
    for i, (_, label, req_fn) in enumerate(STAGE_LADDER):
        if req_fn is None:
            last_ok = i
            continue
        ok, field = req_fn(custom)
        if ok:
            last_ok = i
        else:
            failures.append(f"{label} requires {field}")
            break  # ladder is sequential — once a stage fails, higher stages also fail
    return last_ok, failures


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

    # P40 (Closeout Pending): no entry-truth gate — auto-reached from P30. Left as-is.
    if stage_id == STAGE_ID_P40:
        return {
            **base,
            "decision": "no_op",
            "reason": "P40 (Closeout Pending) has no entry-truth gate; left as-is",
        }

    # P50 (Closeout Complete) readiness guardrail: bounce back to P40 if the job is not
    # actually closeout-ready. Readiness is recomputed from the proof fields so this stays
    # correct within the same event even before derived-closeout-ready's write lands.
    if stage_id == STAGE_ID_P50:
        ready, missing = closeout_readiness(custom)
        if ready:
            return {
                **base,
                "decision": "no_op",
                "reason": "closeout readiness satisfied at P50 (Closeout Complete); no bounce needed",
            }
        return {
            **base,
            "decision": "would_rewind",
            "target_value": STAGE_ID_P40,
            "reason": (
                "At Closeout Complete (P50) but closeout readiness fails: "
                f"missing {', '.join(missing)}. Bouncing back to Closeout Pending (P40)."
            ),
        }

    current_idx = _stage_index(stage_id)
    if current_idx is None:
        return {
            **base,
            "decision": "no_op",
            "reason": f"stage {stage_id!r} not in the managed P05–P30 ladder",
        }

    target_idx, failures = _highest_satisfied_index(custom)
    if target_idx >= current_idx:
        return {
            **base,
            "decision": "no_op",
            "reason": "stage truth invariant satisfied (no rewind needed)",
        }

    target_stage_id, target_label, _ = STAGE_LADDER[target_idx]
    _, current_label, _ = STAGE_LADDER[current_idx]
    return {
        **base,
        "decision": "would_rewind",
        "target_value": target_stage_id,
        "reason": (
            f"At {current_label} but truth invariant fails: "
            f"{'; '.join(failures)}. Rewinding to {target_label}."
        ),
    }


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the stage rewind via the GHL writer."""
    from ghl_writer import writer

    if decision.get("decision") != "would_rewind":
        return {"executed": False, "reason": "decision is not would_rewind"}

    opp = unwrap_opportunity({"opportunity": opp_data})
    opp_id = opp.get("id")
    pipeline_id = opp.get("pipelineId")
    target_stage_id = decision.get("target_value")
    if not opp_id or not target_stage_id:
        return {"executed": False, "reason": "missing opp_id or target_value"}

    updates = {"pipelineStageId": target_stage_id}
    response = await writer.update_opportunity(opp_id, pipeline_id, updates)
    return {"executed": True, "response": response, "applied": updates}
