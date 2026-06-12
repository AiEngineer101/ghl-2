"""Unit tests for the MaterialsVerified shadow handler."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.gate_materials_verified import (  # noqa: E402
    INPUT_FIELD,
    OUTPUT_FIELD,
    evaluate,
)


def _opp(ev_value: str = "", dt_value: str = "") -> dict:
    return {
        "opportunity": {
            "customFields": [
                {"fieldKey": INPUT_FIELD, "fieldValue": ev_value},
                {"fieldKey": OUTPUT_FIELD, "fieldValue": dt_value},
            ]
        }
    }


def test_no_op_when_evidence_absent():
    r = evaluate(_opp(ev_value="", dt_value=""))
    assert r["decision"] == "no_op"
    assert r["target_field"] == OUTPUT_FIELD


def test_would_stamp_when_evidence_present_and_dt_empty():
    r = evaluate(_opp(ev_value="https://files.example/materials.pdf", dt_value=""))
    assert r["decision"] == "would_stamp"
    assert r["target_field"] == OUTPUT_FIELD
    assert r["target_value"]  # an ISO date string


def test_skip_idempotent_when_dt_already_set():
    r = evaluate(_opp(ev_value="https://files.example/materials.pdf", dt_value="2026-05-30"))
    assert r["decision"] == "skip_idempotent"
    assert r["current_value"] == "2026-05-30"


def test_handles_unwrapped_payload():
    """Some payloads have the opp at the root rather than under .opportunity."""
    flat = {
        "customFields": [
            {"fieldKey": INPUT_FIELD, "fieldValue": "url"},
            {"fieldKey": OUTPUT_FIELD, "fieldValue": ""},
        ]
    }
    r = evaluate(flat)
    assert r["decision"] == "would_stamp"
