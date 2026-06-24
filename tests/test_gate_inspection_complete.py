"""Unit tests for the Sales inspection-complete TF->DT gate."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.gate_inspection_complete import (  # noqa: E402
    INPUT_FIELD,
    OUTPUT_FIELD,
    PHOTO_FIELD,
    PIPELINE_ID_SALES,
    evaluate,
)


def _opp(fields: dict | None = None, pipeline_id: str = PIPELINE_ID_SALES) -> dict:
    cf = [{"fieldKey": k, "fieldValue": v} for k, v in (fields or {}).items()]
    return {"opportunity": {"pipelineId": pipeline_id, "customFields": cf}}


def test_no_op_when_not_sales():
    r = evaluate(_opp({INPUT_FIELD: "Yes", PHOTO_FIELD: "http://p"}, pipeline_id="other"))
    assert r["decision"] == "no_op"


def test_no_op_when_tf_not_yes():
    r = evaluate(_opp({PHOTO_FIELD: "http://p"}))
    assert r["decision"] == "no_op"


def test_skip_condition_unmet_when_photo_missing():
    """tf=Yes but no proof photo -> truth not earned yet (Edge 3 of inspection-booked)."""
    r = evaluate(_opp({INPUT_FIELD: "Yes"}))
    assert r["decision"] == "skip_condition_unmet"


def test_would_stamp_when_tf_yes_and_photo_present():
    r = evaluate(_opp({INPUT_FIELD: "Yes", PHOTO_FIELD: "http://p"}))
    assert r["decision"] == "would_stamp"
    assert r["target_field"] == OUTPUT_FIELD
    assert r["target_value"] == date.today().isoformat()


def test_tolerates_list_form_yes():
    r = evaluate(_opp({INPUT_FIELD: ["Yes"], PHOTO_FIELD: "http://p"}))
    assert r["decision"] == "would_stamp"


def test_skip_idempotent_when_dt_already_set():
    r = evaluate(_opp({INPUT_FIELD: "Yes", PHOTO_FIELD: "http://p", OUTPUT_FIELD: "2026-06-20"}))
    assert r["decision"] == "skip_idempotent"
