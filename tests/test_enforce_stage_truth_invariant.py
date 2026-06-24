"""Unit tests for the stage-truth invariant enforcer."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.enforce_stage_truth_invariant import (  # noqa: E402
    PIPELINE_ID_PROD,
    STAGE_ID_P05,
    STAGE_ID_P10,
    STAGE_ID_P20,
    STAGE_ID_P30,
    STAGE_ID_P40,
    STAGE_ID_P50,
    evaluate,
)


def _opp(stage_id: str, fields: dict | None = None, pipeline_id: str = PIPELINE_ID_PROD) -> dict:
    cf = []
    for k, v in (fields or {}).items():
        cf.append({"fieldKey": k, "fieldValue": v})
    return {
        "opportunity": {
            "pipelineId": pipeline_id,
            "pipelineStageId": stage_id,
            "customFields": cf,
        }
    }


def test_no_op_when_not_production():
    r = evaluate(_opp(STAGE_ID_P30, pipeline_id="other"))
    assert r["decision"] == "no_op"


def test_no_op_at_p40_no_entry_gate():
    """P40 (Closeout Pending) is a valid resting stage — never touched by the enforcer."""
    r = evaluate(_opp(STAGE_ID_P40))
    assert r["decision"] == "no_op"
    # Even with closeout proof entirely absent, P40 is left alone.
    r2 = evaluate(_opp(STAGE_ID_P40, {"dt_completion_photos_received": ""}))
    assert r2["decision"] == "no_op"


# --- P50 (Closeout Complete) readiness guardrail ---

# Minimal field set that makes closeout_readiness() return ready (no permit, no change order).
CLOSEOUT_READY = {
    "dt_completion_photos_received": "2026-06-22",
    "dt_coc_received": "2026-06-22",
    "dt_final_walkthrough_proof_received": "2026-06-22",
    "sys_closeout_cash_reconciled": "Yes",
}


def test_p50_no_op_when_closeout_ready():
    """A legitimately-closed job stays at P50."""
    r = evaluate(_opp(STAGE_ID_P50, CLOSEOUT_READY))
    assert r["decision"] == "no_op"


def test_p50_bounces_to_p40_when_no_proof():
    """Manual drag to Closeout Complete with nothing done → bounce back to P40."""
    r = evaluate(_opp(STAGE_ID_P50))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_P40


def test_p50_bounces_to_p40_when_one_proof_breaks():
    """Proof later broke (e.g. COC date cleared) → bounce back and name the missing item."""
    fields = {**CLOSEOUT_READY}
    del fields["dt_coc_received"]
    r = evaluate(_opp(STAGE_ID_P50, fields))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_P40
    assert "COC" in r["reason"] or "completion" in r["reason"].lower()


def test_p50_bounces_when_cash_not_reconciled():
    r = evaluate(_opp(STAGE_ID_P50, {**CLOSEOUT_READY, "sys_closeout_cash_reconciled": "No"}))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_P40


def test_p50_recomputes_readiness_ignoring_stale_flag():
    """The guardrail must NOT trust a stale stored sys_closeout_ready=Yes when proof is gone."""
    r = evaluate(_opp(STAGE_ID_P50, {"sys_closeout_ready": "Yes"}))  # flag set, but no proof
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_P40


def test_no_op_at_p05_with_no_truth():
    """P05 has no entry req — anything goes."""
    r = evaluate(_opp(STAGE_ID_P05))
    assert r["decision"] == "no_op"


def test_no_op_when_all_truth_satisfied_at_p30():
    r = evaluate(_opp(STAGE_ID_P30, {
        "dt_install_scheduled": "2026-06-20",
        "tf_work_started": ["Yes"],
        "tf_work_completed": ["Yes"],
    }))
    assert r["decision"] == "no_op"


def test_rewind_p30_to_p05_when_everything_cleared():
    """The Dhruv case: at P30 with all truth fields empty → rewind all the way."""
    r = evaluate(_opp(STAGE_ID_P30))  # no truth fields set
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_P05


def test_rewind_p30_to_p20_when_only_work_completed_cleared():
    r = evaluate(_opp(STAGE_ID_P30, {
        "dt_install_scheduled": "2026-06-20",
        "tf_work_started": "Yes",
        # tf_work_completed empty
    }))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_P20


def test_rewind_p30_to_p10_when_work_started_and_completed_missing():
    r = evaluate(_opp(STAGE_ID_P30, {
        "dt_install_scheduled": "2026-06-20",
        # tf_work_started, tf_work_completed both empty
    }))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_P10


def test_rewind_p20_to_p10_when_work_started_cleared():
    r = evaluate(_opp(STAGE_ID_P20, {
        "dt_install_scheduled": "2026-06-20",
        # tf_work_started empty
    }))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_P10


def test_rewind_p20_to_p05_when_install_and_work_started_both_missing():
    r = evaluate(_opp(STAGE_ID_P20))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_P05


def test_rewind_p10_to_p05_when_install_cleared():
    r = evaluate(_opp(STAGE_ID_P10))
    assert r["decision"] == "would_rewind"
    assert r["target_value"] == STAGE_ID_P05


def test_tolerates_list_form_yes():
    """tf_* fields often arrive as ['Yes'] — should still be honored."""
    r = evaluate(_opp(STAGE_ID_P30, {
        "dt_install_scheduled": "2026-06-20",
        "tf_work_started": ["Yes"],
        "tf_work_completed": ["Yes"],
    }))
    assert r["decision"] == "no_op"


def test_does_not_advance_only_rewinds():
    """If at P05 with full truth, the enforcer must NOT advance — only rewind."""
    r = evaluate(_opp(STAGE_ID_P05, {
        "dt_install_scheduled": "2026-06-20",
        "tf_work_started": "Yes",
        "tf_work_completed": "Yes",
    }))
    assert r["decision"] == "no_op"  # would_advance is the movers' job, not this handler's
