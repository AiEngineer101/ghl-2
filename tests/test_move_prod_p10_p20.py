"""Unit tests for the P10->P20 Work Started shadow handler."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.move_prod_p10_p20_work_started import (  # noqa: E402
    INPUT_FIELD_STOP_WORK,
    INPUT_FIELD_WORK_STARTED,
    PIPELINE_ID_PROD,
    STAGE_ID_P05,
    STAGE_ID_P10,
    STAGE_ID_P20,
    evaluate,
)


def _opp(
    stage_id: str,
    work_started: object = None,
    stop_work: object = None,
    pipeline_id: str = PIPELINE_ID_PROD,
) -> dict:
    fields = []
    if work_started is not None:
        fields.append({"fieldKey": INPUT_FIELD_WORK_STARTED, "fieldValue": work_started})
    if stop_work is not None:
        fields.append({"fieldKey": INPUT_FIELD_STOP_WORK, "fieldValue": stop_work})
    return {
        "opportunity": {
            "pipelineId": pipeline_id,
            "pipelineStageId": stage_id,
            "customFields": fields,
        }
    }


def test_no_op_when_not_in_production_pipeline():
    r = evaluate(_opp(STAGE_ID_P10, work_started="Yes", pipeline_id="other"))
    assert r["decision"] == "no_op"


def test_skip_idempotent_when_already_at_p20():
    r = evaluate(_opp(STAGE_ID_P20, work_started="Yes"))
    assert r["decision"] == "skip_idempotent"


def test_no_op_when_stage_not_eligible():
    # P30 — past P20, but stage check would have caught it as idempotent.
    # Use an arbitrary non-PROD-prod stage ID that isn't in any of our sets.
    r = evaluate(_opp("not-a-known-stage", work_started="Yes"))
    assert r["decision"] == "no_op"


def test_skip_condition_unmet_when_work_not_started_at_p10():
    r = evaluate(_opp(STAGE_ID_P10, work_started=""))
    assert r["decision"] == "skip_condition_unmet"


def test_skip_condition_unmet_when_work_started_field_missing():
    r = evaluate(_opp(STAGE_ID_P10))  # no work_started field at all
    assert r["decision"] == "skip_condition_unmet"


def test_would_move_from_p10():
    r = evaluate(_opp(STAGE_ID_P10, work_started="Yes"))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_P20


def test_would_move_from_p05_jump():
    """Spec allows P05 -> P20 directly when work_started fires."""
    r = evaluate(_opp(STAGE_ID_P05, work_started="Yes"))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_P20


def test_accepts_list_form_yes():
    """GHL Yes/No fields often come through as ['Yes']."""
    r = evaluate(_opp(STAGE_ID_P10, work_started=["Yes"]))
    assert r["decision"] == "would_move"


def test_blocked_when_stop_work_active():
    r = evaluate(_opp(STAGE_ID_P10, work_started="Yes", stop_work="Active — Materials Mismatch"))
    assert r["decision"] == "skip_blocked"
    assert "stop_work" in r["reason"].lower() or "seg_stop_work" in r["reason"].lower()


def test_not_blocked_when_stop_work_clear():
    r = evaluate(_opp(STAGE_ID_P10, work_started="Yes", stop_work="Clear — Work Can Proceed"))
    assert r["decision"] == "would_move"


def test_not_blocked_when_stop_work_resolved():
    r = evaluate(_opp(STAGE_ID_P10, work_started="Yes", stop_work="Resolved — Work Can Proceed"))
    assert r["decision"] == "would_move"


def test_not_blocked_when_stop_work_empty():
    r = evaluate(_opp(STAGE_ID_P10, work_started="Yes", stop_work=""))
    assert r["decision"] == "would_move"
