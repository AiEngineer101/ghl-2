"""Unit tests for the P40->P50 Closeout Complete handler.

The mover recomputes closeout readiness from the raw proof (3 docs + cash-from-amounts +
permit + change order) in a single event, instead of reading the stored sys_closeout_ready
flag — so it moves the moment the last proof is present (no multi-hop propagation lag).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.move_prod_p40_p50_closeout_complete import (  # noqa: E402
    PIPELINE_ID_PROD,
    STAGE_ID_P40,
    STAGE_ID_P50,
    evaluate,
)

STAGE_ID_P30 = "96f19b6d-4d85-4e66-910f-4a4f071bf9c0"

# All closeout proof present: 3 docs + full payment (raw amounts), no permit, no change order.
READY = {
    "dt_completion_photos_received": "2026-07-01",
    "dt_coc_received": "2026-07-01",
    "dt_final_walkthrough_proof_received": "2026-07-01",
    "amt_contract_value": "1000",
    "amt_total_funds_received": "1000",
    "seg_permit_required": "No",
}


def _opp(stage_id, fields=None, pipeline_id=PIPELINE_ID_PROD):
    cf = [{"fieldKey": k, "fieldValue": v} for k, v in (fields or {}).items()]
    return {"opportunity": {"pipelineId": pipeline_id, "pipelineStageId": stage_id, "customFields": cf}}


def test_no_op_when_not_in_production_pipeline():
    assert evaluate(_opp(STAGE_ID_P40, READY, pipeline_id="other"))["decision"] == "no_op"


def test_skip_idempotent_when_already_at_p50():
    assert evaluate(_opp(STAGE_ID_P50, READY))["decision"] == "skip_idempotent"


def test_no_op_when_stage_not_p40():
    assert evaluate(_opp(STAGE_ID_P30, READY))["decision"] == "no_op"


def test_would_move_when_all_proof_present():
    r = evaluate(_opp(STAGE_ID_P40, READY))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_P50


def test_moves_from_raw_amounts_without_stored_cash_flag():
    """The fix: readiness passes from the raw amounts even though sys_closeout_cash_reconciled
    was never written — so the job closes in one event instead of stalling at Closeout Pending."""
    assert "sys_closeout_cash_reconciled" not in READY
    assert evaluate(_opp(STAGE_ID_P40, READY))["decision"] == "would_move"


def test_skip_when_no_proof():
    assert evaluate(_opp(STAGE_ID_P40, {}))["decision"] == "skip_condition_unmet"


def test_skip_when_a_document_missing():
    fields = dict(READY)
    del fields["dt_coc_received"]
    r = evaluate(_opp(STAGE_ID_P40, fields))
    assert r["decision"] == "skip_condition_unmet"
    assert "COC" in r["reason"] or "certificate" in r["reason"].lower()


def test_skip_when_payment_short():
    fields = dict(READY)
    fields["amt_total_funds_received"] = "500"
    assert evaluate(_opp(STAGE_ID_P40, fields))["decision"] == "skip_condition_unmet"
