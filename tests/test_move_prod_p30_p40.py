"""Unit tests for the P30->P40 Closeout Pending shadow handler."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.move_prod_p30_p40_closeout_pending import (  # noqa: E402
    PIPELINE_ID_PROD,
    STAGE_ID_P30,
    STAGE_ID_P40,
    STAGE_ID_P50,
    evaluate,
)

STAGE_ID_P20 = "ebef66b1-a570-412c-93b3-1be988d6a33f"


def _opp(stage_id: str, pipeline_id: str = PIPELINE_ID_PROD) -> dict:
    return {"opportunity": {"pipelineId": pipeline_id, "pipelineStageId": stage_id}}


def test_no_op_when_not_in_production_pipeline():
    assert evaluate(_opp(STAGE_ID_P30, pipeline_id="other"))["decision"] == "no_op"


def test_skip_idempotent_when_already_at_p40():
    assert evaluate(_opp(STAGE_ID_P40))["decision"] == "skip_idempotent"


def test_skip_idempotent_when_past_p40():
    assert evaluate(_opp(STAGE_ID_P50))["decision"] == "skip_idempotent"


def test_no_op_when_stage_not_p30():
    assert evaluate(_opp(STAGE_ID_P20))["decision"] == "no_op"


def test_would_move_from_p30():
    r = evaluate(_opp(STAGE_ID_P30))
    assert r["decision"] == "would_move"
    assert r["target_value"] == STAGE_ID_P40
