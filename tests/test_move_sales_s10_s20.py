"""Unit tests for the Sales S10->S20 mover (Inspection Complete)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.move_sales_s10_s20_inspection_complete import (  # noqa: E402
    DT_FRONT_PHOTO,
    DT_INSPECTION,
    PIPELINE_ID_SALES,
    STAGE_ID_S10,
    STAGE_ID_S20,
    evaluate,
)

BOTH_TRUTHS = {DT_INSPECTION: "2026-06-20", DT_FRONT_PHOTO: "2026-06-20"}


def _opp(stage_id: str, fields: dict | None = None, pipeline_id: str = PIPELINE_ID_SALES) -> dict:
    cf = [{"fieldKey": k, "fieldValue": v} for k, v in (fields or {}).items()]
    return {"opportunity": {"pipelineId": pipeline_id, "pipelineStageId": stage_id, "customFields": cf}}


def test_no_op_when_not_sales():
    r = evaluate(_opp(STAGE_ID_S10, BOTH_TRUTHS, pipeline_id="other"))
    assert r["decision"] == "no_op"


def test_no_op_when_not_at_s10():
    # An arbitrary non-Sales-ladder stage id that isn't S10 or >=S20.
    r = evaluate(_opp("some-leads-stage-id", BOTH_TRUTHS))
    assert r["decision"] == "no_op"


def test_skip_idempotent_when_already_at_s20():
    r = evaluate(_opp(STAGE_ID_S20, BOTH_TRUTHS))
    assert r["decision"] == "skip_idempotent"


def test_skip_condition_unmet_when_no_truths():
    r = evaluate(_opp(STAGE_ID_S10))
    assert r["decision"] == "skip_condition_unmet"
    assert DT_INSPECTION in r["reason"] and DT_FRONT_PHOTO in r["reason"]


def test_skip_condition_unmet_when_only_photo_truth():
    r = evaluate(_opp(STAGE_ID_S10, {DT_FRONT_PHOTO: "2026-06-20"}))
    assert r["decision"] == "skip_condition_unmet"
    assert DT_INSPECTION in r["reason"]


def test_would_move_when_both_truths_present():
    r = evaluate(_opp(STAGE_ID_S10, BOTH_TRUTHS))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_S20
