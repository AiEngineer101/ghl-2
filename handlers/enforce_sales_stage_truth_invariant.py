"""Invariant enforcer for the SALES pipeline: keep stage <= the highest stage whose
entry-proof is currently satisfied.

The Sales analogue of enforce-stage-truth-invariant (which is Production-only). The forward
movers advance a Sales opp only on proof, but nothing walks it BACK if someone manually drags
a card ahead of its evidence (or a dt_*/seg_* gets cleared after the fact). This closes that
gap: it runs on every Sales Opportunity Changed event, recomputes the highest stage whose
entry requirement still holds, and rewinds if the opp sits higher than that.

Sales differs from the Production ladder in one important way: the entry requirements at
S30 and S40 are JOB-TYPE CONDITIONAL (Retail vs Insurance vs Hybrid). So the walk is
three-valued at those rungs:
  - ok            -> requirement satisfied; keep climbing
  - fail          -> requirement provably unmet; this is the rewind boundary
  - indeterminate -> job type unknown/unrecognized, so the branch can't be determined.
                     We DO NOT rewind in this case (a missing seg_job_type must not bounce a
                     deal). We leave the stage alone until the job type is set.

Entry requirements (cumulative, low -> high), per move-handler logic:
  S10  base — none.
  S20  dt_inspection_completed AND dt_front_of_home_inspection_photo_received  (both durable
       inspection truths; job-type-independent).
  S30  Retail: none beyond S20.  Insurance/Hybrid: dt_insurance_scope_received.  Unknown: indeterminate.
  S40  Retail: dt_estimate_presented.  Insurance: dt_insurance_scope_received.
       Hybrid: BOTH.  Unknown: indeterminate.
  S45  dt_signed_contract_received  (universal contract truth).
  S46  dt_signed_contract_received AND (dt_ins_deductible_received OR dt_retail_deposit_proof_received).
  S50  production readiness — RECOMPUTED from proof fields (not the stored sys_production_readiness
       flag), so it stays correct within the same event even before derived-production-readiness's
       write lands. (Mirrors how the Production P50 guardrail recomputes closeout_readiness.)

Runs LAST among the Sales handlers (registered after the movers) so it sees the post-mover
intent. Because evaluate() reads the pre-move snapshot stage (the mover's write only lands in
_maybe_execute, after every evaluate()), the enforcer never fights a legitimate forward move:
during a real advance the current stage is still <= the highest satisfied rung, so it no-ops.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity
from handlers.derived_production_readiness import production_readiness
from handlers.sales_stages import (
    LAST_GOOD_PIPELINE_CODE,
    PIPELINE_ID_SALES,
    SALES_STAGE_ORDER,
    STAGE_ID_S10,
    STAGE_ID_S20,
    STAGE_ID_S30,
    STAGE_ID_S40,
    STAGE_ID_S45,
    STAGE_ID_S46,
    STAGE_ID_S50,
)

HANDLER_ID = "enforce-sales-stage-truth-invariant"
# ACTIVE (cut over 2026-06-27 after live shadow validation on opp CK0DVZ7Y0neREIUr5BS4:
# healthy S10 -> no_op; dragged to S30 with no proof -> would_rewind to S10, reason naming the
# missing inspection truths). Sales is pipeline-live, so this now actively rewinds ANY drifted
# Sales opp on its next event. The writer allowlist still gates the PUT (Sales is allowlisted).
SUPPORTS_WRITE = True  # active — performs Sales stage rewinds (pipeline-live)

# Three-valued requirement status.
OK = "ok"
FAIL = "fail"
INDETERMINATE = "indeterminate"

JOB_TYPE_FIELD = "seg_job_type"
JOB_TYPE_RETAIL = "retail"
JOB_TYPE_INSURANCE = "insurance"
JOB_TYPE_HYBRID = "hybrid"

DT_INSPECTION = "dt_inspection_completed"
DT_FRONT_PHOTO = "dt_front_of_home_inspection_photo_received"
DT_INSURANCE_SCOPE = "dt_insurance_scope_received"
DT_ESTIMATE = "dt_estimate_presented"
DT_CONTRACT = "dt_signed_contract_received"
DT_INS_DEDUCTIBLE = "dt_ins_deductible_received"
DT_RETAIL_DEPOSIT = "dt_retail_deposit_proof_received"


def _job_type(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return ""
    return str(value).strip().lower()


def _req_s20(cf: dict[str, Any], jt: str) -> tuple[str, str]:
    if truthy(cf.get(DT_INSPECTION)) and truthy(cf.get(DT_FRONT_PHOTO)):
        return OK, ""
    return FAIL, f"{DT_INSPECTION} + {DT_FRONT_PHOTO}"


def _req_s30(cf: dict[str, Any], jt: str) -> tuple[str, str]:
    if jt == JOB_TYPE_RETAIL:
        return OK, ""
    if jt in (JOB_TYPE_INSURANCE, JOB_TYPE_HYBRID):
        return (OK, "") if truthy(cf.get(DT_INSURANCE_SCOPE)) else (FAIL, DT_INSURANCE_SCOPE)
    return INDETERMINATE, f"{JOB_TYPE_FIELD} unknown"


def _req_s40(cf: dict[str, Any], jt: str) -> tuple[str, str]:
    if jt == JOB_TYPE_RETAIL:
        return (OK, "") if truthy(cf.get(DT_ESTIMATE)) else (FAIL, DT_ESTIMATE)
    if jt == JOB_TYPE_INSURANCE:
        return (OK, "") if truthy(cf.get(DT_INSURANCE_SCOPE)) else (FAIL, DT_INSURANCE_SCOPE)
    if jt == JOB_TYPE_HYBRID:
        if truthy(cf.get(DT_ESTIMATE)) and truthy(cf.get(DT_INSURANCE_SCOPE)):
            return OK, ""
        return FAIL, f"{DT_ESTIMATE} + {DT_INSURANCE_SCOPE}"
    return INDETERMINATE, f"{JOB_TYPE_FIELD} unknown"


def _req_s45(cf: dict[str, Any], jt: str) -> tuple[str, str]:
    return (OK, "") if truthy(cf.get(DT_CONTRACT)) else (FAIL, DT_CONTRACT)


def _req_s46(cf: dict[str, Any], jt: str) -> tuple[str, str]:
    funding = truthy(cf.get(DT_INS_DEDUCTIBLE)) or truthy(cf.get(DT_RETAIL_DEPOSIT))
    if truthy(cf.get(DT_CONTRACT)) and funding:
        return OK, ""
    return FAIL, f"{DT_CONTRACT} + ({DT_INS_DEDUCTIBLE} or {DT_RETAIL_DEPOSIT})"


def _req_s50(cf: dict[str, Any], jt: str) -> tuple[str, str]:
    ready, missing = production_readiness(cf)
    return (OK, "") if ready else (FAIL, f"production readiness ({', '.join(missing)})")


# Indexed to align with SALES_STAGE_ORDER. None = base (S10), always satisfied.
_REQ_BY_INDEX = [None, _req_s20, _req_s30, _req_s40, _req_s45, _req_s46, _req_s50]


def _stage_index(stage_id: str | None) -> int | None:
    for i, (sid, _) in enumerate(SALES_STAGE_ORDER):
        if sid == stage_id:
            return i
    return None


def _walk(custom: dict[str, Any], jt: str) -> tuple[int, str, list[str]]:
    """Climb the ladder. Return (highest_ok_index, terminal_status, failure_reasons).

    terminal_status is the status that stopped the climb: OK if every rung satisfied,
    FAIL if a rung was provably unmet, INDETERMINATE if a job-type-conditional rung
    could not be determined.
    """
    last_ok = 0  # S10 base always satisfied
    for i in range(1, len(SALES_STAGE_ORDER)):
        status, detail = _REQ_BY_INDEX[i](custom, jt)
        _, code = SALES_STAGE_ORDER[i]
        if status == OK:
            last_ok = i
            continue
        if status == INDETERMINATE:
            return last_ok, INDETERMINATE, [f"{code} requires {detail}"]
        return last_ok, FAIL, [f"{code} requires {detail}"]
    return last_ok, OK, []


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    stage_id = opp.get("pipelineStageId")
    custom = custom_field_map(opp)
    jt = _job_type(custom.get(JOB_TYPE_FIELD))

    base = {
        "handler_id": HANDLER_ID,
        "target_field": "pipelineStageId",
        "current_value": stage_id,
    }

    if pipeline_id != PIPELINE_ID_SALES:
        return {**base, "decision": "no_op",
                "reason": f"pipelineId {pipeline_id!r} is not Sales ({PIPELINE_ID_SALES})"}

    current_idx = _stage_index(stage_id)
    if current_idx is None:
        return {**base, "decision": "no_op",
                "reason": f"stage {stage_id!r} is not in the managed Sales ladder"}

    last_ok, status, failures = _walk(custom, jt)

    if current_idx <= last_ok:
        return {**base, "decision": "no_op",
                "reason": "stage truth invariant satisfied (no rewind needed)"}

    # current_idx is above the highest satisfied rung.
    if status == INDETERMINATE:
        return {**base, "decision": "no_op",
                "reason": (f"cannot determine job-type branch ({'; '.join(failures)}); "
                           f"leaving stage as-is rather than rewinding on missing job type")}

    target_stage_id, target_code = SALES_STAGE_ORDER[last_ok]
    _, current_code = SALES_STAGE_ORDER[current_idx]
    return {**base, "decision": "would_rewind", "target_value": target_stage_id,
            "reason": (f"At {current_code} but truth invariant fails: "
                       f"{'; '.join(failures)}. Rewinding to {target_code}.")}


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Perform the Sales stage rewind via the shared writer helper, stamping the corrected
    last-good stage in the same PUT."""
    from handlers._writers import move_stage
    from handlers.sales_stages import stage_code_for

    return await move_stage(
        opp_data, decision,
        last_good_stage_code=stage_code_for(decision.get("target_value")),
        last_good_pipeline_code=LAST_GOOD_PIPELINE_CODE,
    )


# Re-export the stage ids used by tests for convenience.
__all__ = [
    "HANDLER_ID", "SUPPORTS_WRITE", "PIPELINE_ID_SALES", "evaluate", "execute",
    "STAGE_ID_S10", "STAGE_ID_S20", "STAGE_ID_S30", "STAGE_ID_S40",
    "STAGE_ID_S45", "STAGE_ID_S46", "STAGE_ID_S50",
]
