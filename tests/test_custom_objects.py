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
