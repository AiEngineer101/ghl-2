"""Unit tests for the Sales S45->S46 mover (initial funding received)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.move_sales_s45_s46_initial_funding import (  # noqa: E402
    DT_INS_DEDUCTIBLE,
    DT_RETAIL_DEPOSIT,
    PIPELINE_ID_SALES,
    STAGE_ID_S45,
    STAGE_ID_S46,
    evaluate,
)


def _opp(stage_id, fields=None, pipeline_id=PIPELINE_ID_SALES):
    cf = [{"fieldKey": k, "fieldValue": v} for k, v in (fields or {}).items()]
    return {"opportunity": {"pipelineId": pipeline_id, "pipelineStageId": stage_id, "customFields": cf}}


def test_no_op_when_not_sales():
    assert evaluate(_opp(STAGE_ID_S45, {DT_RETAIL_DEPOSIT: "x"}, pipeline_id="other"))["decision"] == "no_op"


def test_skip_idempotent_when_already_at_s46():
    assert evaluate(_opp(STAGE_ID_S46, {DT_RETAIL_DEPOSIT: "x"}))["decision"] == "skip_idempotent"


def test_no_op_when_not_at_s45():
    assert evaluate(_opp("other-stage", {DT_RETAIL_DEPOSIT: "x"}))["decision"] == "no_op"


def test_holds_without_funding():
    r = evaluate(_opp(STAGE_ID_S45))
    assert r["decision"] == "skip_condition_unmet"


def test_moves_on_retail_deposit():
    r = evaluate(_opp(STAGE_ID_S45, {DT_RETAIL_DEPOSIT: "2026-06-24"}))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_S46


def test_moves_on_insurance_deductible():
    r = evaluate(_opp(STAGE_ID_S45, {DT_INS_DEDUCTIBLE: "2026-06-24"}))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_S46
