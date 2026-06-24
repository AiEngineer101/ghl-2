"""Unit tests for the Sales S46->S50 mover (handoff to production)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.move_sales_s46_s50_handoff_to_production import (  # noqa: E402
    PIPELINE_ID_SALES,
    STAGE_ID_S46,
    STAGE_ID_S50,
    SYS_PRODUCTION_READINESS,
    evaluate,
)


def _opp(stage_id, fields=None, pipeline_id=PIPELINE_ID_SALES):
    cf = [{"fieldKey": k, "fieldValue": v} for k, v in (fields or {}).items()]
    return {"opportunity": {"pipelineId": pipeline_id, "pipelineStageId": stage_id, "customFields": cf}}


def test_no_op_when_not_sales():
    assert evaluate(_opp(STAGE_ID_S46, {SYS_PRODUCTION_READINESS: "Yes"}, pipeline_id="other"))["decision"] == "no_op"


def test_skip_idempotent_when_already_at_s50():
    assert evaluate(_opp(STAGE_ID_S50, {SYS_PRODUCTION_READINESS: "Yes"}))["decision"] == "skip_idempotent"


def test_no_op_when_not_at_s46():
    assert evaluate(_opp("other-stage", {SYS_PRODUCTION_READINESS: "Yes"}))["decision"] == "no_op"


def test_holds_when_not_ready():
    r = evaluate(_opp(STAGE_ID_S46, {SYS_PRODUCTION_READINESS: "No"}))
    assert r["decision"] == "skip_condition_unmet"


def test_holds_when_readiness_absent():
    assert evaluate(_opp(STAGE_ID_S46))["decision"] == "skip_condition_unmet"


def test_moves_when_ready():
    r = evaluate(_opp(STAGE_ID_S46, {SYS_PRODUCTION_READINESS: "Yes"}))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_S50


def test_tolerates_list_form_yes():
    r = evaluate(_opp(STAGE_ID_S46, {SYS_PRODUCTION_READINESS: ["Yes"]}))
    assert r["decision"] == "would_move"
