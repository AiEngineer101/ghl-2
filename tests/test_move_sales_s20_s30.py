"""Unit tests for the Sales S20->S30 job-type-conditional mover."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.move_sales_s20_s30_scope_pending import (  # noqa: E402
    DT_INSURANCE_SCOPE,
    JOB_TYPE_FIELD,
    PIPELINE_ID_SALES,
    STAGE_ID_S20,
    STAGE_ID_S30,
    evaluate,
)


def _opp(stage_id: str, fields: dict | None = None, pipeline_id: str = PIPELINE_ID_SALES) -> dict:
    cf = [{"fieldKey": k, "fieldValue": v} for k, v in (fields or {}).items()]
    return {"opportunity": {"pipelineId": pipeline_id, "pipelineStageId": stage_id, "customFields": cf}}


def test_no_op_when_not_sales():
    r = evaluate(_opp(STAGE_ID_S20, {JOB_TYPE_FIELD: "Retail"}, pipeline_id="other"))
    assert r["decision"] == "no_op"


def test_skip_idempotent_when_already_at_s30():
    r = evaluate(_opp(STAGE_ID_S30, {JOB_TYPE_FIELD: "Retail"}))
    assert r["decision"] == "skip_idempotent"


def test_no_op_when_not_at_s20():
    r = evaluate(_opp("some-other-stage", {JOB_TYPE_FIELD: "Retail"}))
    assert r["decision"] == "no_op"


# --- Retail: passes straight through ---

def test_retail_moves_immediately():
    r = evaluate(_opp(STAGE_ID_S20, {JOB_TYPE_FIELD: "Retail"}))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_S30


# --- Insurance / Hybrid: hold for carrier scope ---

def test_insurance_holds_without_scope():
    r = evaluate(_opp(STAGE_ID_S20, {JOB_TYPE_FIELD: "Insurance"}))
    assert r["decision"] == "skip_condition_unmet"
    assert DT_INSURANCE_SCOPE in r["reason"]


def test_insurance_moves_with_scope():
    r = evaluate(_opp(STAGE_ID_S20, {JOB_TYPE_FIELD: "Insurance", DT_INSURANCE_SCOPE: "2026-06-22"}))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_S30


def test_hybrid_holds_without_scope():
    r = evaluate(_opp(STAGE_ID_S20, {JOB_TYPE_FIELD: "Hybrid"}))
    assert r["decision"] == "skip_condition_unmet"


def test_hybrid_moves_with_scope():
    r = evaluate(_opp(STAGE_ID_S20, {JOB_TYPE_FIELD: "Hybrid", DT_INSURANCE_SCOPE: "2026-06-22"}))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_S30


def test_tolerates_list_form_and_case():
    r = evaluate(_opp(STAGE_ID_S20, {JOB_TYPE_FIELD: ["insurance"], DT_INSURANCE_SCOPE: "2026-06-22"}))
    assert r["decision"] == "would_move"


# --- Unknown / missing job type: hold ---

def test_unknown_job_type_holds():
    r = evaluate(_opp(STAGE_ID_S20, {}))
    assert r["decision"] == "skip_condition_unmet"
    assert JOB_TYPE_FIELD in r["reason"]
