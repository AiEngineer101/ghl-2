"""Unit tests for the Sales pay-ins-acv EV->DT gate."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.gate_pay_ins_acv import (  # noqa: E402
    INPUT_FIELD,
    OUTPUT_FIELD,
    PIPELINE_ID_SALES,
    evaluate,
)


def _opp(fields: dict | None = None, pipeline_id: str = PIPELINE_ID_SALES) -> dict:
    cf = [{"fieldKey": k, "fieldValue": v} for k, v in (fields or {}).items()]
    return {"opportunity": {"pipelineId": pipeline_id, "customFields": cf}}


def test_no_op_when_not_sales():
    r = evaluate(_opp({INPUT_FIELD: "http://acv.pdf"}, pipeline_id="88V9uYY6visCrtI9V0NR"))
    assert r["decision"] == "no_op"


def test_no_op_when_proof_empty():
    r = evaluate(_opp({}))
    assert r["decision"] == "no_op"


def test_would_stamp_when_proof_present_and_dt_empty():
    r = evaluate(_opp({INPUT_FIELD: "http://acv/proof.pdf"}))
    assert r["decision"] == "would_stamp"
    assert r["target_field"] == OUTPUT_FIELD
    assert r["target_value"] == date.today().isoformat()


def test_skip_idempotent_when_dt_already_set():
    r = evaluate(_opp({INPUT_FIELD: "http://acv/proof.pdf", OUTPUT_FIELD: "2026-06-20"}))
    assert r["decision"] == "skip_idempotent"
