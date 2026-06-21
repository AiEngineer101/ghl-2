"""Unit tests for the Closeout Cash Reconciled derived handler."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.derived_closeout_cash_reconciled import (  # noqa: E402
    FIELD_CONTRACT_VALUE,
    FIELD_FUNDS_RECEIVED,
    OUTPUT_FIELD,
    evaluate,
)


def _opp(contract=None, funds=None, current=None) -> dict:
    fields = []
    if contract is not None:
        fields.append({"fieldKey": FIELD_CONTRACT_VALUE, "fieldValue": contract})
    if funds is not None:
        fields.append({"fieldKey": FIELD_FUNDS_RECEIVED, "fieldValue": funds})
    if current is not None:
        fields.append({"fieldKey": OUTPUT_FIELD, "fieldValue": current})
    return {"opportunity": {"customFields": fields}}


def test_skip_when_contract_missing():
    # No contract target -> can't determine reconciliation; leave the field alone.
    assert evaluate(_opp(funds="1000"))["decision"] == "skip_condition_unmet"


def test_not_reconciled_when_funds_blank():
    # The fix: contract present but funds cleared -> $0 received -> No (not stale Yes).
    r = evaluate(_opp(contract="1000"))
    assert r["decision"] == "would_stamp"
    assert r["target_value"] == "No"


def test_skip_condition_unmet_when_unparseable():
    assert evaluate(_opp(contract="abc", funds="100"))["decision"] == "skip_condition_unmet"


def test_would_stamp_yes_when_funds_cover_contract():
    r = evaluate(_opp(contract="10000", funds="10000"))
    assert r["decision"] == "would_stamp"
    assert r["target_value"] == "Yes"


def test_would_stamp_no_when_funds_short():
    r = evaluate(_opp(contract="10000", funds="9999"))
    assert r["decision"] == "would_stamp"
    assert r["target_value"] == "No"


def test_tolerates_currency_formatting():
    r = evaluate(_opp(contract="$10,000.00", funds="$12,500.00"))
    assert r["decision"] == "would_stamp"
    assert r["target_value"] == "Yes"


def test_handles_numeric_values():
    r = evaluate(_opp(contract=10000, funds=10000))
    assert r["target_value"] == "Yes"


def test_skip_idempotent_when_already_correct():
    assert evaluate(_opp(contract="100", funds="200", current="Yes"))["decision"] == "skip_idempotent"


def test_recomputes_when_current_stale():
    # Currently "No" but funds now cover contract -> should flip to Yes.
    r = evaluate(_opp(contract="100", funds="200", current="No"))
    assert r["decision"] == "would_stamp"
    assert r["target_value"] == "Yes"
