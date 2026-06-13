"""Unit tests for the P20->P30 Work Completed shadow handler."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.move_prod_p20_p30_work_completed import (  # noqa: E402
    INPUT_FIELD_WORK_COMPLETED,
    PIPELINE_ID_PROD,
    STAGE_ID_P10,
    STAGE_ID_P20,
    STAGE_ID_P30,
    evaluate,
)


def _opp(
    stage_id: str,
    work_completed: object = None,
    pipeline_id: str = PIPELINE_ID_PROD,
) -> dict:
    fields = []
    if work_completed is not None:
        fields.append({"fieldKey": INPUT_FIELD_WORK_COMPLETED, "fieldValue": work_completed})
    return {
        "opportunity": {
            "pipelineId": pipeline_id,
            "pipelineStageId": stage_id,
            "customFields": fields,
        }
    }


def test_no_op_when_not_in_production_pipeline():
    r = evaluate(_opp(STAGE_ID_P20, work_completed="Yes", pipeline_id="other"))
    assert r["decision"] == "no_op"


def test_skip_idempotent_when_already_at_p30():
    r = evaluate(_opp(STAGE_ID_P30, work_completed="Yes"))
    assert r["decision"] == "skip_idempotent"


def test_skip_idempotent_when_past_p30():
    p40 = "bb84bafb-5266-4063-b1f6-bc1ef21a0790"
    r = evaluate(_opp(p40, work_completed="Yes"))
    assert r["decision"] == "skip_idempotent"


def test_no_op_when_stage_not_eligible():
    p05 = "c98f59ed-7b38-4dd6-ae64-01c5a6537894"
    r = evaluate(_opp(p05, work_completed="Yes"))
    assert r["decision"] == "no_op"


def test_skip_condition_unmet_when_work_completed_empty():
    r = evaluate(_opp(STAGE_ID_P20, work_completed=""))
    assert r["decision"] == "skip_condition_unmet"


def test_skip_condition_unmet_when_field_missing():
    r = evaluate(_opp(STAGE_ID_P20))
    assert r["decision"] == "skip_condition_unmet"


def test_would_move_from_p20():
    r = evaluate(_opp(STAGE_ID_P20, work_completed="Yes"))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_P30


def test_would_move_from_p10_jump():
    """Spec allows P10 -> P30 directly when work_completed fires."""
    r = evaluate(_opp(STAGE_ID_P10, work_completed="Yes"))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_P30


def test_accepts_list_form_yes():
    r = evaluate(_opp(STAGE_ID_P20, work_completed=["Yes"]))
    assert r["decision"] == "would_move"
