"""Unit tests for the WorkStarted (TF→DT) shadow gate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.gate_work_started import INPUT_FIELD, OUTPUT_FIELD, evaluate  # noqa: E402


def _opp(tf_value: object = None, dt_value: object = None) -> dict:
    fields = []
    if tf_value is not None:
        fields.append({"fieldKey": INPUT_FIELD, "fieldValue": tf_value})
    if dt_value is not None:
        fields.append({"fieldKey": OUTPUT_FIELD, "fieldValue": dt_value})
    return {"opportunity": {"customFields": fields}}


def test_no_op_when_tf_empty():
    r = evaluate(_opp(tf_value=""))
    assert r["decision"] == "no_op"


def test_no_op_when_tf_missing():
    r = evaluate(_opp())
    assert r["decision"] == "no_op"


def test_no_op_when_tf_no():
    r = evaluate(_opp(tf_value="No"))
    assert r["decision"] == "no_op"


def test_would_stamp_when_tf_yes_and_dt_empty():
    r = evaluate(_opp(tf_value="Yes"))
    assert r["decision"] == "would_stamp"
    assert r["target_field"] == OUTPUT_FIELD


def test_accepts_list_form_yes():
    r = evaluate(_opp(tf_value=["Yes"]))
    assert r["decision"] == "would_stamp"


def test_skip_idempotent_when_dt_already_set():
    r = evaluate(_opp(tf_value="Yes", dt_value="2026-06-13"))
    assert r["decision"] == "skip_idempotent"
