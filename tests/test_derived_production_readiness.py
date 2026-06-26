"""Unit tests for derived-production-readiness (sys_production_readiness rollup).

Covers the per-job-type prerequisite sets from handoff-to-production.md §6, the stricter
permit gate, unknown job type, and idempotency.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers import derived_production_readiness as h  # noqa: E402

SALES = "9KlQhUS34GzTN9q34WKF"
PROD = "88V9uYY6visCrtI9V0NR"


def _payload(pipeline=SALES, **fields):
    cfs = [{"fieldKey": k, "fieldValue": v} for k, v in fields.items()]
    return {"opportunity": {"pipelineId": pipeline, "customFields": cfs}}


# Minimal field sets that make each job type fully ready.
RETAIL_READY = dict(
    seg_job_type="Retail",
    dt_measurement_report_received="2026-06-26",
    amt_contract_value="15000",
    seg_permit_required="No",
    dt_estimate_presented="2026-06-26",
    dt_signed_contract_received="2026-06-26",
    dt_retail_deposit_proof_received="2026-06-26",
)
INSURANCE_READY = dict(
    seg_job_type="Insurance",
    dt_measurement_report_received="2026-06-26",
    amt_contract_value="15000",
    seg_permit_required="No",
    dt_insurance_scope_received="2026-06-26",
    dt_insurance_contract_signed="2026-06-26",
    dt_ins_acv_received="2026-06-26",
    dt_ins_deductible_received="2026-06-26",
    seg_insurance_carrier_name="State Farm",
    seg_insurance_claim_number="CLM-1",
)
HYBRID_READY = dict(
    seg_job_type="Hybrid",
    dt_measurement_report_received="2026-06-26",
    amt_contract_value="15000",
    seg_permit_required="No",
    dt_insurance_scope_received="2026-06-26",
    dt_estimate_presented="2026-06-26",
    dt_insurance_contract_signed="2026-06-26",
    dt_hybrid_upgrade_accepted="2026-06-26",
    dt_ins_acv_received="2026-06-26",
    dt_retail_deposit_proof_received="2026-06-26",
    dt_ins_deductible_received="2026-06-26",
    seg_insurance_carrier_name="State Farm",
    seg_insurance_claim_number="CLM-1",
)


def test_non_sales_pipeline_is_noop():
    d = h.evaluate(_payload(pipeline=PROD, **RETAIL_READY))
    assert d["decision"] == "no_op"


def test_retail_fully_ready_stamps_yes():
    d = h.evaluate(_payload(**RETAIL_READY))
    assert d["decision"] == "would_stamp"
    assert d["target_value"] == "Yes"


def test_retail_missing_deposit_stamps_no_and_names_it():
    fields = dict(RETAIL_READY)
    del fields["dt_retail_deposit_proof_received"]
    d = h.evaluate(_payload(**fields))
    assert d["decision"] == "would_stamp"
    assert d["target_value"] == "No"
    assert "retail deposit" in d["reason"]


def test_retail_missing_contract_value_stamps_no():
    fields = dict(RETAIL_READY)
    del fields["amt_contract_value"]
    d = h.evaluate(_payload(**fields))
    assert d["target_value"] == "No"
    assert "contract value" in d["reason"]


def test_insurance_fully_ready_stamps_yes():
    d = h.evaluate(_payload(**INSURANCE_READY))
    assert d["target_value"] == "Yes"


def test_insurance_missing_claim_number_stamps_no():
    fields = dict(INSURANCE_READY)
    del fields["seg_insurance_claim_number"]
    d = h.evaluate(_payload(**fields))
    assert d["target_value"] == "No"
    assert "claim number" in d["reason"]


def test_hybrid_fully_ready_stamps_yes():
    d = h.evaluate(_payload(**HYBRID_READY))
    assert d["target_value"] == "Yes"


def test_hybrid_missing_upgrade_accepted_stamps_no():
    fields = dict(HYBRID_READY)
    del fields["dt_hybrid_upgrade_accepted"]
    d = h.evaluate(_payload(**fields))
    assert d["target_value"] == "No"


def test_unknown_job_type_stamps_no():
    fields = dict(RETAIL_READY)
    fields["seg_job_type"] = "Commercial"
    d = h.evaluate(_payload(**fields))
    assert d["target_value"] == "No"
    assert "job type" in d["reason"]


# --- permit gate (stricter than closeout's) ---

def test_permit_unset_is_not_ready():
    fields = dict(RETAIL_READY)
    del fields["seg_permit_required"]  # unset => blocked
    d = h.evaluate(_payload(**fields))
    assert d["target_value"] == "No"
    assert "permit" in d["reason"]


def test_permit_required_yes_with_approval_is_ready():
    fields = dict(RETAIL_READY)
    fields["seg_permit_required"] = "Yes"
    fields["dt_permit_approved"] = "2026-06-26"
    d = h.evaluate(_payload(**fields))
    assert d["target_value"] == "Yes"


def test_permit_required_yes_without_approval_is_not_ready():
    fields = dict(RETAIL_READY)
    fields["seg_permit_required"] = "Yes"  # no dt_permit_approved
    d = h.evaluate(_payload(**fields))
    assert d["target_value"] == "No"
    assert "permit" in d["reason"]


# --- idempotency ---

def test_idempotent_when_already_yes():
    fields = dict(RETAIL_READY)
    fields["sys_production_readiness"] = "Yes"
    d = h.evaluate(_payload(**fields))
    assert d["decision"] == "skip_idempotent"


def test_idempotent_when_already_no():
    fields = dict(RETAIL_READY)
    del fields["amt_contract_value"]
    fields["sys_production_readiness"] = "No"
    d = h.evaluate(_payload(**fields))
    assert d["decision"] == "skip_idempotent"


def test_readiness_helper_returns_missing_list():
    ready, missing = h.production_readiness({"seg_job_type": "Retail"})
    assert ready is False
    assert "measurement report" in missing
    assert "estimate presented" in missing
