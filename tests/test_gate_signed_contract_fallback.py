"""Unit tests for the Sales signed-contract fallback-upload EV->DT gate (+ estimate backfill)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.gate_signed_contract_fallback import (  # noqa: E402
    BACKFILL_FIELD,
    INPUT_FIELD,
    OUTPUT_FIELD,
    PIPELINE_ID_SALES,
    evaluate,
)


def _opp(fields: dict | None = None, pipeline_id: str = PIPELINE_ID_SALES) -> dict:
    cf = [{"fieldKey": k, "fieldValue": v} for k, v in (fields or {}).items()]
    return {"opportunity": {"pipelineId": pipeline_id, "customFields": cf}}


def test_no_op_when_not_sales():
    r = evaluate(_opp({INPUT_FIELD: "http://contract.pdf"}, pipeline_id="88V9uYY6visCrtI9V0NR"))
    assert r["decision"] == "no_op"


def test_no_op_when_ev_empty():
    r = evaluate(_opp({}))
    assert r["decision"] == "no_op"


def test_would_stamp_and_backfills_estimate_when_estimate_empty():
    r = evaluate(_opp({INPUT_FIELD: "http://contract/signed.pdf"}))
    assert r["decision"] == "would_stamp"
    assert r["target_field"] == OUTPUT_FIELD == "dt_signed_contract_received"
    assert r["target_value"] == date.today().isoformat()
    assert r["backfill_estimate"] is True  # estimate empty -> backfill


def test_would_stamp_without_backfill_when_estimate_already_set():
    r = evaluate(_opp({INPUT_FIELD: "http://contract/signed.pdf", BACKFILL_FIELD: "2026-06-15"}))
    assert r["decision"] == "would_stamp"
    assert r["backfill_estimate"] is False  # estimate already present -> no backfill


def test_skip_idempotent_when_contract_date_already_set():
    r = evaluate(_opp({INPUT_FIELD: "http://contract/signed.pdf", OUTPUT_FIELD: "2026-06-20"}))
    assert r["decision"] == "skip_idempotent"
