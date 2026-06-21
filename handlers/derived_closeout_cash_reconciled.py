"""Shadow handler for WF | Derived | Closeout Cash Reconciled.

Spec source: workflow/02-derived/derived-closeout-cash-reconciled.md
- Trigger (live): Opportunity Changed, "Custom field updated: amt_total_funds_received
  OR amt_contract_value"
- IF: amt_contract_value is present (the payment target). Missing/blank funds count
  as $0 received.
- DO: set sys_closeout_cash_reconciled = Yes if funds >= contract, else No
- Idempotent: only emit a write when the computed value differs from the current value
- Clearing the payment flips the flag back to No (does not leave a stale Yes).

Deterministic system truth. Feeds `derived-closeout-ready`.

ACTIVE writer (cut over 2026-06-21). The live "Derived Closeout Cash Reconciled" GHL
workflow must be set to Draft so the two don't double-drive.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, unwrap_opportunity

HANDLER_ID = "derived-closeout-cash-reconciled"
SUPPORTS_WRITE = True  # ACTIVE (cut over 2026-06-21)

FIELD_CONTRACT_VALUE = "amt_contract_value"
FIELD_FUNDS_RECEIVED = "amt_total_funds_received"
OUTPUT_FIELD = "sys_closeout_cash_reconciled"


def _to_float(value: Any) -> float | None:
    """Parse a GHL amount field to float. Tolerates strings, lists, and currency noise."""
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("$", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    custom = custom_field_map(opp)
    contract_raw = custom.get(FIELD_CONTRACT_VALUE)
    funds_raw = custom.get(FIELD_FUNDS_RECEIVED)
    current = custom.get(OUTPUT_FIELD)

    base = {
        "handler_id": HANDLER_ID,
        "target_field": OUTPUT_FIELD,
        "current_value": _to_str(current),
    }

    contract = _to_float(contract_raw)
    if contract is None:
        # No contract value yet -> the payment target is unknown; leave the field alone.
        return {
            **base,
            "decision": "skip_condition_unmet",
            "reason": (
                f"{FIELD_CONTRACT_VALUE} missing/unparseable (contract={contract_raw!r}); "
                f"cannot determine payment target"
            ),
        }

    # Missing, blank, or unparseable funds = $0 received -> not reconciled.
    # (Fix: clearing/removing the payment now correctly flips the flag back to No,
    # instead of leaving a stale 'Yes'. This deviates from the spec's "both fields
    # present" guard, which left the field unchanged when funds were cleared.)
    funds = _to_float(funds_raw)
    if funds is None:
        funds = 0.0

    computed = "Yes" if funds >= contract else "No"

    if _to_str(current) == computed:
        return {
            **base,
            "decision": "skip_idempotent",
            "reason": f"{OUTPUT_FIELD} already {computed}",
        }

    return {
        **base,
        "decision": "would_stamp",
        "target_value": computed,
        "reason": (
            f"funds {funds} {'>=' if computed == 'Yes' else '<'} contract {contract} — "
            f"would set {OUTPUT_FIELD} = {computed}"
        ),
    }


def _to_str(v: Any) -> str | None:
    if isinstance(v, list):
        v = v[0] if v else None
    if v is None:
        return None
    return str(v)


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Set sys_closeout_cash_reconciled (Yes/No) via the GHL writer."""
    from handlers._writers import stamp_custom_field
    return await stamp_custom_field(opp_data, decision, OUTPUT_FIELD)
