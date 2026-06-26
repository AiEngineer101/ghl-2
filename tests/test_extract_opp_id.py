"""Unit tests for webhook_payload.extract_opp_id across the GHL webhook payload shapes.

The default GHL custom-data webhook puts opportunity fields at the ROOT (opportunity id
is root `id`, with pipeline_id/pipeline_name alongside). Step 5 must catch that without
mistaking a contact-only payload's id for an opportunity id.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webhook_payload import extract_opp_id as _extract_opp_id  # noqa: E402

OPP = "rCZ51hZFEFO9EMaenXVZ"


def test_explicit_opportunity_id():
    assert _extract_opp_id({"opportunity_id": OPP}) == OPP


def test_nested_opportunity_object():
    assert _extract_opp_id({"opportunity": {"id": OPP}}) == OPP


def test_custom_data_opportunity_id():
    assert _extract_opp_id({"customData": {"opportunity_id": OPP}}) == OPP


def test_root_id_with_type_naming_opportunity():
    assert _extract_opp_id({"type": "OpportunityUpdate", "id": OPP}) == OPP


def test_ghl_default_custom_data_shape_root_id():
    """The real default payload: opp fields at root, no type/opportunity_id/customData."""
    payload = {
        "opportunity_name": "Test Deal",
        "status": "open",
        "pipeline_id": "9KlQhUS34GzTN9q34WKF",
        "pipeline_name": "Sales",
        "id": OPP,
        "first_name": "Jane",
        "location": {"id": "8aQHgJUX2bFYBHZ4Qizg"},
    }
    assert _extract_opp_id(payload) == OPP


def test_root_id_alone_without_opp_markers_is_not_an_opp():
    """A contact-only payload (root id, no pipeline/opp markers) must NOT match."""
    payload = {"id": "some-contact-id", "first_name": "Jane", "email": "j@x.com"}
    assert _extract_opp_id(payload) is None


def test_pipeline_id_marker_alone_promotes_root_id():
    assert _extract_opp_id({"id": OPP, "pipeline_id": "9KlQhUS34GzTN9q34WKF"}) == OPP


def test_empty_and_non_dict():
    assert _extract_opp_id({}) is None
    assert _extract_opp_id("nope") is None
