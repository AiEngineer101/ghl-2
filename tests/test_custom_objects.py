"""Unit tests for the pure custom-object helpers (custom_objects.py).

Uses the real relation shape observed via /debug/co-probe (2026-07-02). Async fetches
(custom_object_reader) are I/O and not unit-tested; the parsing/selection here is.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import custom_objects as co  # noqa: E402

OPP = "fNhW9oCAO0chbsIgayKh"
CLAIM = "CLAIM-123"


def _relations(*rels):
    return {"relations": list(rels), "total": len(rels), "traceId": "t"}


# --- related_record_ids ---

def test_claim_on_first_side():
    body = _relations(
        {"firstObjectKey": "custom_objects.insurance_claims", "firstRecordId": CLAIM,
         "secondObjectKey": "opportunity", "secondRecordId": OPP, "associationId": "job_insurance_claim"},
    )
    assert co.related_record_ids(body, co.SCHEMA_INSURANCE_CLAIM) == [CLAIM]


def test_claim_on_second_side():
    body = _relations(
        {"firstObjectKey": "opportunity", "firstRecordId": OPP,
         "secondObjectKey": "custom_objects.insurance_claims", "secondRecordId": CLAIM,
         "associationId": "job_insurance_claim"},
    )
    assert co.related_record_ids(body, co.SCHEMA_INSURANCE_CLAIM) == [CLAIM]


def test_ignores_unrelated_relations():
    body = _relations(
        {"firstObjectKey": "opportunity", "firstRecordId": OPP,
         "secondObjectKey": "contact", "secondRecordId": "C1",
         "associationId": "OPPORTUNITIES_CONTACTS_ASSOCIATION"},
    )
    assert co.related_record_ids(body, co.SCHEMA_INSURANCE_CLAIM) == []


def test_multiple_and_dedupe():
    body = _relations(
        {"firstObjectKey": "opportunity", "firstRecordId": OPP,
         "secondObjectKey": "custom_objects.change_orders", "secondRecordId": "CO1"},
        {"firstObjectKey": "custom_objects.change_orders", "firstRecordId": "CO2",
         "secondObjectKey": "opportunity", "secondRecordId": OPP},
        {"firstObjectKey": "opportunity", "firstRecordId": OPP,
         "secondObjectKey": "custom_objects.change_orders", "secondRecordId": "CO1"},  # dup
    )
    assert co.related_record_ids(body, co.SCHEMA_CHANGE_ORDER) == ["CO1", "CO2"]


def test_empty_and_malformed():
    assert co.related_record_ids({}, co.SCHEMA_INSURANCE_CLAIM) == []
    assert co.related_record_ids(None, co.SCHEMA_INSURANCE_CLAIM) == []
    assert co.related_record_ids({"relations": [None, "x", {}]}, co.SCHEMA_INSURANCE_CLAIM) == []


# --- record_fields (tolerant of unverified live shape) ---

def test_properties_container():
    body = {"record": {"id": CLAIM, "properties": {"claim_number": "0123-AB", "amt_acv": "5000"}}}
    assert co.record_fields(body) == {"claim_number": "0123-AB", "amt_acv": "5000"}


def test_properties_without_record_wrapper():
    body = {"properties": {"claim_number": "X"}}
    assert co.record_fields(body) == {"claim_number": "X"}


def test_top_level_fallback_strips_system_keys():
    body = {"record": {"id": CLAIM, "locationId": "loc", "createdAt": "t", "claim_number": "Y"}}
    assert co.record_fields(body) == {"claim_number": "Y"}


def test_record_fields_non_dict():
    assert co.record_fields(None) == {}
    assert co.record_fields("nope") == {}


# --- claim_identity_fields (spec-based mapping; keys unverified live) ---

def test_claim_identity_maps_number_and_scope():
    out = co.claim_identity_fields({"claim_number": "0123-AB", "dt_insurance_scope_received": "2026-07-01"})
    assert out == {"seg_insurance_claim_number": "0123-AB", "dt_insurance_scope_received": "2026-07-01"}


def test_claim_identity_skips_blank_and_non_dict():
    assert co.claim_identity_fields({"claim_number": "", "dt_insurance_scope_received": None}) == {}
    assert co.claim_identity_fields(None) == {}


def test_claim_identity_excludes_carrier_and_payment():
    # carrier (association) + payment/contract (rollup) are intentionally NOT mapped here
    out = co.claim_identity_fields({"claim_number": "X", "amt_acv": "5000", "amt_deductible": "1000"})
    assert out == {"seg_insurance_claim_number": "X"}


# --- revenue_rollup (data-model §9) ---

def _supp(approved=0, received=0):
    return {"id": "s", "fields": {"amt_supplement_approved": approved, "amt_supplement_received": received}}


def _co(amount=0, treatment="Customer Pays (Billable)"):
    return {"id": "c", "fields": {"amt_change_order_approved": amount, "seg_change_order_treatment": treatment}}


def test_rollup_sums_supplements_and_billable_cos():
    r = co.revenue_rollup(
        [_supp(approved=1000, received=600), _supp(approved="2,000", received="$500")],
        [_co(amount=300), _co(amount=999, treatment="Crew Chargeback")],  # non-billable excluded
    )
    assert r["supplements_approved_total"] == 3000.0
    assert r["supplements_received_total"] == 1100.0
    assert r["billable_change_orders_total"] == 300.0
    assert r["rollup_contract_value_contribution"] == 3300.0
    assert r["rollup_funds_received_contribution"] == 1100.0


def test_rollup_empty_inputs():
    r = co.revenue_rollup(None, None)
    assert r["supplements_count"] == 0 and r["rollup_contract_value_contribution"] == 0.0


def test_rollup_ignores_non_numeric_money():
    r = co.revenue_rollup([_supp(approved="n/a", received="")], [])
    assert r["supplements_approved_total"] == 0.0
