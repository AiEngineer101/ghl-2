"""Unit tests for the Sales measurement-report EV->DT gate."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.gate_measurement_report import (  # noqa: E402
    INPUT_FIELD,
    OUTPUT_FIELD,
    PIPELINE_ID_SALES,
    evaluate,
)


def _opp(fields: dict | None = None, pipeline_id: str = PIPELINE_ID_SALES) -> dict:
    cf = [{"fieldKey": k, "fieldValue": v} for k, v in (fields or {}).items()]
    return {"opportunity": {"pipelineId": pipeline_id, "customFields": cf}}


def test_no_op_when_not_sales():
    r = evaluate(_opp({INPUT_FIELD: "http://measure.pdf"}, pipeline_id="88V9uYY6visCrtI9V0NR"))
    assert r["decision"] == "no_op"


def test_no_op_when_report_empty():
    r = evaluate(_opp({}))
    assert r["decision"] == "no_op"


def test_would_stamp_targets_the_live_key():
    r = evaluate(_opp({INPUT_FIELD: "http://measure/report.pdf"}))
    assert r["decision"] == "would_stamp"
    # Must write the LIVE (malformed) key so the PUT resolves to a real GHL field.
    assert r["target_field"] == OUTPUT_FIELD == "_measurement_report_received_date"
    assert r["target_value"] == date.today().isoformat()


def test_skip_idempotent_when_live_key_already_set():
    r = evaluate(_opp({INPUT_FIELD: "http://measure/report.pdf", OUTPUT_FIELD: "2026-06-20"}))
    assert r["decision"] == "skip_idempotent"


def test_skip_idempotent_when_spec_key_already_set():
    """Tolerate the spec key dt_measurement_report_received as 'already received' too."""
    r = evaluate(_opp({
        INPUT_FIELD: "http://measure/report.pdf",
        "dt_measurement_report_received": "2026-06-20",
    }))
    assert r["decision"] == "skip_idempotent"
