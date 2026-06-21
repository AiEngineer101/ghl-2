"""Shadow handler for WF | Derived | Closeout Ready.

Spec source: workflow/02-derived/derived-closeout-ready.md  (CR-0003)
- Trigger (live): Opportunity Changed on any of the closeout input fields.
- IF (Pipeline=Production):
    completion_photos present
    AND coc present
    AND final_walkthrough present
    AND sys_closeout_cash_reconciled = Yes
    AND (seg_permit_required != Yes OR permit_approved present)
    AND (
       change_order_photo_pack empty
       OR (treatment present AND the chosen payer path is fully documented)
    )
  -> set sys_closeout_ready = Yes; else No
- Idempotent: only emit a write when the computed value differs from the current value

This is the gate the P40->P50 mover reads. Adds the Company/Vendor payer path per CR-0003.

Shadow-only for now (SUPPORTS_WRITE=False). Cut over once parity is confirmed AND the
live "Derived Closeout Ready" GHL workflow is set to Draft.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity, yes

HANDLER_ID = "derived-closeout-ready"
SUPPORTS_WRITE = False  # shadow-only until cutover

PIPELINE_ID_PROD = "88V9uYY6visCrtI9V0NR"
OUTPUT_FIELD = "sys_closeout_ready"

# Change-order treatment values (seg_change_order_treatment) and the doc each requires.
TREATMENT_CREW_CHARGEBACK = "No — Crew Chargeback (Crew Pays)"
TREATMENT_COMPANY_VENDOR = "No — Company/Vendor Pays (Internal)"
TREATMENT_BILLABLE = "Yes — Billable (Customer Pays)"


def _scalar(value: Any) -> Any:
    """Collapse list-form GHL values to their first element."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _change_order_resolved(custom: dict[str, Any]) -> bool:
    """True if no CO was initiated, or the initiated CO's payer path is fully documented."""
    if not truthy(custom.get("dt_change_order_photo_pack_uploaded")):
        return True  # no change order initiated

    treatment = _scalar(custom.get("seg_change_order_treatment"))
    if not truthy(treatment):
        return False  # CO initiated but payer path not yet chosen
    treatment = str(treatment).strip()

    if treatment == TREATMENT_CREW_CHARGEBACK:
        return truthy(custom.get("dt_crew_chargeback_doc_received"))
    if treatment == TREATMENT_COMPANY_VENDOR:
        return truthy(custom.get("dt_company_vendor_responsibility_doc_received"))
    if treatment == TREATMENT_BILLABLE:
        return truthy(custom.get("dt_change_order_signed_received")) and truthy(
            custom.get("dt_change_order_payment_received")
        )
    return False  # unknown treatment value — not resolved


def _is_ready(custom: dict[str, Any]) -> bool:
    if not truthy(custom.get("dt_completion_photos_received")):
        return False
    if not truthy(custom.get("dt_coc_received")):
        return False
    if not truthy(custom.get("dt_final_walkthrough_proof_received")):
        return False
    if not yes(custom.get("sys_closeout_cash_reconciled")):
        return False
    # Permit only required when seg_permit_required = Yes.
    if yes(custom.get("seg_permit_required")) and not truthy(custom.get("dt_permit_approved")):
        return False
    if not _change_order_resolved(custom):
        return False
    return True


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    custom = custom_field_map(opp)
    current = _scalar(custom.get(OUTPUT_FIELD))

    base = {
        "handler_id": HANDLER_ID,
        "target_field": OUTPUT_FIELD,
        "current_value": _to_str(current),
    }

    if pipeline_id != PIPELINE_ID_PROD:
        return {
            **base,
            "decision": "no_op",
            "reason": f"pipelineId {pipeline_id!r} is not Production ({PIPELINE_ID_PROD})",
        }

    computed = "Yes" if _is_ready(custom) else "No"

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
        "reason": f"closeout readiness recomputed — would set {OUTPUT_FIELD} = {computed}",
    }


def _to_str(v: Any) -> str | None:
    if isinstance(v, list):
        v = v[0] if v else None
    if v is None:
        return None
    return str(v)


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Set sys_closeout_ready (Yes/No) via the GHL writer."""
    from handlers._writers import stamp_custom_field
    return await stamp_custom_field(opp_data, decision, OUTPUT_FIELD)
