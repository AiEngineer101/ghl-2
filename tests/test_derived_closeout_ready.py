"""Unit tests for the Closeout Ready derived handler."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.derived_closeout_ready import (  # noqa: E402
    OUTPUT_FIELD,
    PIPELINE_ID_PROD,
    TREATMENT_BILLABLE,
    TREATMENT_COMPANY_VENDOR,
    TREATMENT_CREW_CHARGEBACK,
    evaluate,
)

# Base set of fields that satisfy the core (non-change-order, no-permit) readiness path.
BASE_READY = {
    "dt_completion_photos_received": "2026-06-20",
    "dt_coc_received": "2026-06-20",
    "dt_final_walkthrough_proof_received": "2026-06-20",
    "sys_closeout_cash_reconciled": "Yes",
}


def _opp(pipeline_id: str = PIPELINE_ID_PROD, current=None, **fields) -> dict:
    cf = [{"fieldKey": k, "fieldValue": v} for k, v in fields.items()]
    if current is not None:
        cf.append({"fieldKey": OUTPUT_FIELD, "fieldValue": current})
    return {"opportunity": {"pipelineId": pipeline_id, "customFields": cf}}


def test_no_op_when_not_in_production():
    assert evaluate(_opp(pipeline_id="other", **BASE_READY))["decision"] == "no_op"


def test_ready_when_core_conditions_met_no_co_no_permit():
    r = evaluate(_opp(**BASE_READY))
    assert r["decision"] == "would_stamp"
    assert r["target_value"] == "Yes"


def test_not_ready_when_completion_photos_missing():
    f = {**BASE_READY}
    del f["dt_completion_photos_received"]
    r = evaluate(_opp(**f))
    assert r["target_value"] == "No"


def test_not_ready_when_cash_not_reconciled():
    r = evaluate(_opp(**{**BASE_READY, "sys_closeout_cash_reconciled": "No"}))
    assert r["target_value"] == "No"


def test_permit_required_but_not_approved_blocks():
    r = evaluate(_opp(**{**BASE_READY, "seg_permit_required": "Yes"}))
    assert r["target_value"] == "No"


def test_permit_required_and_approved_ready():
    r = evaluate(_opp(**{
        **BASE_READY,
        "seg_permit_required": "Yes",
        "dt_permit_approved": "2026-06-20",
    }))
    assert r["target_value"] == "Yes"


def test_permit_not_required_ignored():
    r = evaluate(_opp(**{**BASE_READY, "seg_permit_required": "No"}))
    assert r["target_value"] == "Yes"


def test_change_order_initiated_without_treatment_blocks():
    r = evaluate(_opp(**{
        **BASE_READY,
        "dt_change_order_photo_pack_uploaded": "2026-06-20",
    }))
    assert r["target_value"] == "No"


def test_change_order_crew_chargeback_resolved():
    r = evaluate(_opp(**{
        **BASE_READY,
        "dt_change_order_photo_pack_uploaded": "2026-06-20",
        "seg_change_order_treatment": TREATMENT_CREW_CHARGEBACK,
        "dt_crew_chargeback_doc_received": "2026-06-20",
    }))
    assert r["target_value"] == "Yes"


def test_change_order_company_vendor_resolved():
    r = evaluate(_opp(**{
        **BASE_READY,
        "dt_change_order_photo_pack_uploaded": "2026-06-20",
        "seg_change_order_treatment": TREATMENT_COMPANY_VENDOR,
        "dt_company_vendor_responsibility_doc_received": "2026-06-20",
    }))
    assert r["target_value"] == "Yes"


def test_change_order_billable_requires_signed_and_payment():
    partial = evaluate(_opp(**{
        **BASE_READY,
        "dt_change_order_photo_pack_uploaded": "2026-06-20",
        "seg_change_order_treatment": TREATMENT_BILLABLE,
        "dt_change_order_signed_received": "2026-06-20",
    }))
    assert partial["target_value"] == "No"

    full = evaluate(_opp(**{
        **BASE_READY,
        "dt_change_order_photo_pack_uploaded": "2026-06-20",
        "seg_change_order_treatment": TREATMENT_BILLABLE,
        "dt_change_order_signed_received": "2026-06-20",
        "dt_change_order_payment_received": "2026-06-20",
    }))
    assert full["target_value"] == "Yes"


def test_skip_idempotent_when_already_yes():
    r = evaluate(_opp(current="Yes", **BASE_READY))
    assert r["decision"] == "skip_idempotent"
