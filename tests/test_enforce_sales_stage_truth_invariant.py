"""Unit tests for the Sales stage-truth invariant enforcer."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.enforce_sales_stage_truth_invariant import (  # noqa: E402
    PIPELINE_ID_SALES,
    STAGE_ID_S10,
    STAGE_ID_S20,
    STAGE_ID_S30,
    STAGE_ID_S40,
    STAGE_ID_S45,
    STAGE_ID_S46,
    STAGE_ID_S50,
    evaluate,
)
from handlers.sales_stages import stage_code_for  # noqa: E402

# --- field fixtures ---
INSPECTION_TRUTHS = {
    "dt_inspection_completed": "2026-06-20",
    "dt_front_of_home_inspection_photo_received": "2026-06-20",
}
# A Retail opp legitimately resting at S40 (inspection done + estimate presented).
RETAIL_AT_S40 = {**INSPECTION_TRUTHS, "seg_job_type": "Retail", "dt_estimate_presented": "2026-06-21"}
# Everything S46 needs for Retail (contract + a deposit), still inspection-complete.
RETAIL_AT_S46 = {
    **RETAIL_AT_S40,
    "dt_signed_contract_received": "2026-06-22",
    "dt_retail_deposit_proof_received": "2026-06-22",
}
# Full production-readiness for Retail (so S50 is legitimately held).
RETAIL_S50_READY = {
    **RETAIL_AT_S46,
    "dt_measurement_report_received": "2026-06-22",
    "amt_contract_value": "18000",
    "seg_permit_required": "No",
}


def _opp(stage_id: str, fields: dict | None = None, pipeline_id: str = PIPELINE_ID_SALES) -> dict:
    cf = [{"fieldKey": k, "fieldValue": v} for k, v in (fields or {}).items()]
    return {"opportunity": {"pipelineId": pipeline_id, "pipelineStageId": stage_id, "customFields": cf}}


# --- scoping ---

def test_no_op_when_not_sales():
    r = evaluate(_opp(STAGE_ID_S40, RETAIL_AT_S40, pipeline_id="88V9uYY6visCrtI9V0NR"))
    assert r["decision"] == "no_op"


def test_no_op_when_stage_not_in_sales_ladder():
    r = evaluate(_opp("some-other-stage-id", INSPECTION_TRUTHS))
    assert r["decision"] == "no_op"


def test_no_op_at_s10_base():
    """S10 has no entry requirement — never rewound."""
    r = evaluate(_opp(STAGE_ID_S10))
    assert r["decision"] == "no_op"


# --- the enforcer only rewinds, never advances ---

def test_does_not_advance_only_rewinds():
    """At S10 with full proof, the enforcer must NOT advance — that's the movers' job."""
    r = evaluate(_opp(STAGE_ID_S10, RETAIL_S50_READY))
    assert r["decision"] == "no_op"


# --- satisfied invariants -> no_op ---

def test_no_op_retail_legitimately_at_s40():
    r = evaluate(_opp(STAGE_ID_S40, RETAIL_AT_S40))
    assert r["decision"] == "no_op"


def test_no_op_at_s50_when_production_ready():
    r = evaluate(_opp(STAGE_ID_S50, RETAIL_S50_READY))
    assert r["decision"] == "no_op"


def test_tolerates_list_form_job_type():
    fields = {**RETAIL_AT_S40, "seg_job_type": ["Retail"]}
    r = evaluate(_opp(STAGE_ID_S40, fields))
    assert r["decision"] == "no_op"


# --- genuine drift -> rewind ---

def test_rewind_s20_to_s10_when_inspection_truth_missing():
    r = evaluate(_opp(STAGE_ID_S20))  # no inspection truths
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_S10


def test_rewind_retail_s40_to_s30_when_estimate_missing():
    """Retail dragged to S40 with inspection done but no estimate → back to S30."""
    fields = {**INSPECTION_TRUTHS, "seg_job_type": "Retail"}  # no dt_estimate_presented
    r = evaluate(_opp(STAGE_ID_S40, fields))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_S30
    assert "dt_estimate_presented" in r["reason"]


def test_rewind_insurance_s40_to_s20_when_scope_missing():
    """Insurance at S40 without carrier scope: S30 (scope) fails → rewind to S20."""
    fields = {**INSPECTION_TRUTHS, "seg_job_type": "Insurance"}  # no dt_insurance_scope_received
    r = evaluate(_opp(STAGE_ID_S40, fields))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_S20


def test_rewind_s45_to_s40_when_contract_missing():
    """Retail at S45 (estimate done) but no signed contract → back to S40."""
    r = evaluate(_opp(STAGE_ID_S45, RETAIL_AT_S40))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_S40
    assert "dt_signed_contract_received" in r["reason"]


def test_rewind_s46_to_s45_when_funding_missing():
    """At S46 with contract but no funding proof → back to S45."""
    fields = {**RETAIL_AT_S40, "dt_signed_contract_received": "2026-06-22"}  # contract, no deposit
    r = evaluate(_opp(STAGE_ID_S46, fields))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_S45


def test_rewind_s50_to_s46_when_not_production_ready():
    """At S50 (handoff) but production readiness recompute fails → bounce to S46."""
    # RETAIL_AT_S46 satisfies S46 but lacks measurement report / contract value / permit.
    r = evaluate(_opp(STAGE_ID_S50, RETAIL_AT_S46))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_S46
    assert "production readiness" in r["reason"]


def test_s50_recomputes_readiness_ignoring_stale_flag():
    """A stale stored sys_production_readiness=Yes must NOT keep a non-ready job at S50."""
    fields = {**RETAIL_AT_S46, "sys_production_readiness": "Yes"}  # flag set, prereqs missing
    r = evaluate(_opp(STAGE_ID_S50, fields))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_S46


# --- indeterminate job type: do NOT rewind on a missing branch selector ---

def test_no_rewind_when_job_type_unknown_at_s40():
    """Unknown job type at S40 (inspection done): can't determine branch → leave as-is."""
    r = evaluate(_opp(STAGE_ID_S40, INSPECTION_TRUTHS))  # no seg_job_type
    assert r["decision"] == "no_op"
    assert "job-type" in r["reason"].lower() or "job type" in r["reason"].lower()


def test_rewind_even_with_unknown_job_type_if_inspection_missing():
    """Job-type-independent failure (S20) still rewinds regardless of job type."""
    r = evaluate(_opp(STAGE_ID_S40))  # nothing set at all
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_S10


# --- the shared stage-code map (used for sys_last_good_stage_code) ---

def test_stage_code_for_mapping():
    assert stage_code_for(STAGE_ID_S10) == "S10"
    assert stage_code_for(STAGE_ID_S46) == "S46"
    assert stage_code_for(STAGE_ID_S50) == "S50"
    assert stage_code_for("not-a-sales-stage") is None
    assert stage_code_for(None) is None
