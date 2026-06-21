"""Unit tests for the P40->P50 Closeout Complete shadow handler."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.move_prod_p40_p50_closeout_complete import (  # noqa: E402
    INPUT_FIELD_CLOSEOUT_READY,
    PIPELINE_ID_PROD,
    STAGE_ID_P40,
    STAGE_ID_P50,
    evaluate,
)

STAGE_ID_P30 = "96f19b6d-4d85-4e66-910f-4a4f071bf9c0"


def _opp(stage_id: str, closeout_ready: object = None, pipeline_id: str = PIPELINE_ID_PROD) -> dict:
    fields = []
    if closeout_ready is not None:
        fields.append({"fieldKey": INPUT_FIELD_CLOSEOUT_READY, "fieldValue": closeout_ready})
    return {
        "opportunity": {
            "pipelineId": pipeline_id,
            "pipelineStageId": stage_id,
            "customFields": fields,
        }
    }


def test_no_op_when_not_in_production_pipeline():
    assert evaluate(_opp(STAGE_ID_P40, "Yes", pipeline_id="other"))["decision"] == "no_op"


def test_skip_idempotent_when_already_at_p50():
    assert evaluate(_opp(STAGE_ID_P50, "Yes"))["decision"] == "skip_idempotent"


def test_no_op_when_stage_not_p40():
    assert evaluate(_opp(STAGE_ID_P30, "Yes"))["decision"] == "no_op"


def test_skip_condition_unmet_when_closeout_ready_not_yes():
    assert evaluate(_opp(STAGE_ID_P40, "No"))["decision"] == "skip_condition_unmet"


def test_skip_condition_unmet_when_field_missing():
    assert evaluate(_opp(STAGE_ID_P40))["decision"] == "skip_condition_unmet"


def test_would_move_from_p40_when_ready():
    r = evaluate(_opp(STAGE_ID_P40, "Yes"))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_P50


def test_accepts_list_form_yes():
    assert evaluate(_opp(STAGE_ID_P40, ["Yes"]))["decision"] == "would_move"
