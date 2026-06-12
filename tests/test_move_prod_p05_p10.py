"""Unit tests for the P05->P10 Install Scheduled shadow handler."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.move_prod_p05_p10 import (  # noqa: E402
    INPUT_FIELD,
    PIPELINE_ID_PROD,
    STAGE_ID_P05,
    STAGE_ID_P10,
    evaluate,
)


def _opp(stage_id: str, install_value: str = "", pipeline_id: str = PIPELINE_ID_PROD) -> dict:
    return {
        "opportunity": {
            "pipelineId": pipeline_id,
            "pipelineStageId": stage_id,
            "customFields": [{"fieldKey": INPUT_FIELD, "fieldValue": install_value}],
        }
    }


def test_no_op_when_not_in_production_pipeline():
    r = evaluate(_opp(STAGE_ID_P05, install_value="2026-06-20", pipeline_id="some-other-pipeline"))
    assert r["decision"] == "no_op"


def test_skip_idempotent_when_already_at_p10():
    r = evaluate(_opp(STAGE_ID_P10, install_value="2026-06-20"))
    assert r["decision"] == "skip_idempotent"


def test_skip_idempotent_when_past_p10():
    # Use P20 stage id
    p20 = "ebef66b1-a570-412c-93b3-1be988d6a33f"
    r = evaluate(_opp(p20, install_value="2026-06-20"))
    assert r["decision"] == "skip_idempotent"


def test_skip_when_install_not_scheduled():
    r = evaluate(_opp(STAGE_ID_P05, install_value=""))
    assert r["decision"] == "skip_condition_unmet"


def test_would_move_when_at_p05_and_install_scheduled():
    r = evaluate(_opp(STAGE_ID_P05, install_value="2026-06-20"))
    assert r["decision"] == "would_move"
    assert r["target_field"] == "pipelineStageId"
    assert r["target_value"] == STAGE_ID_P10
    assert r["current_value"] == STAGE_ID_P05
