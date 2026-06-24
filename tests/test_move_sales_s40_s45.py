"""Unit tests for the Sales S40->S45/S46 mover (universal contract gate + funding skip)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.move_sales_s40_s45_funding_pending import (  # noqa: E402
    DT_CONTRACT,
    DT_INS_DEDUCTIBLE,
    DT_RETAIL_DEPOSIT,
    PIPELINE_ID_SALES,
    STAGE_ID_S40,
    STAGE_ID_S45,
    STAGE_ID_S46,
    evaluate,
)


def _opp(stage_id: str, fields: dict | None = None, pipeline_id: str = PIPELINE_ID_SALES) -> dict:
    cf = [{"fieldKey": k, "fieldValue": v} for k, v in (fields or {}).items()]
    return {"opportunity": {"pipelineId": pipeline_id, "pipelineStageId": stage_id, "customFields": cf}}


def test_no_op_when_not_sales():
    r = evaluate(_opp(STAGE_ID_S40, {DT_CONTRACT: "x"}, pipeline_id="other"))
    assert r["decision"] == "no_op"


def test_skip_idempotent_when_already_at_s45():
    r = evaluate(_opp(STAGE_ID_S45, {DT_CONTRACT: "x"}))
    assert r["decision"] == "skip_idempotent"


def test_skip_idempotent_when_already_at_s46():
    r = evaluate(_opp(STAGE_ID_S46, {DT_CONTRACT: "x"}))
    assert r["decision"] == "skip_idempotent"


def test_no_op_when_not_at_s40():
    r = evaluate(_opp("some-other-stage", {DT_CONTRACT: "x"}))
    assert r["decision"] == "no_op"


def test_holds_without_contract():
    r = evaluate(_opp(STAGE_ID_S40))
    assert r["decision"] == "skip_condition_unmet"
    assert DT_CONTRACT in r["reason"]


def test_moves_to_s45_when_contract_but_no_funding():
    r = evaluate(_opp(STAGE_ID_S40, {DT_CONTRACT: "2026-06-24"}))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_S45


def test_skips_to_s46_when_retail_deposit_in():
    r = evaluate(_opp(STAGE_ID_S40, {DT_CONTRACT: "2026-06-24", DT_RETAIL_DEPOSIT: "2026-06-24"}))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_S46


def test_skips_to_s46_when_insurance_deductible_in():
    r = evaluate(_opp(STAGE_ID_S40, {DT_CONTRACT: "2026-06-24", DT_INS_DEDUCTIBLE: "2026-06-24"}))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_S46


def test_contract_is_job_type_agnostic():
    """De-branched: no seg_job_type needed — contract alone moves it (lands S45 w/o funding)."""
    r = evaluate(_opp(STAGE_ID_S40, {DT_CONTRACT: "2026-06-24"}))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_S45
