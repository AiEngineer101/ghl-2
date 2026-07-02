"""Handler for WF | Gate | SignedContract | FallbackUpload (Sales).

Spec source: workflow/01-gates/ev-to-dt/gate-signed-contract-fallback-upload.md
- Trigger (live): Opportunity Changed, scoped to the Sales pipeline (Allow Re-Entry=Yes).
- IF: ev_signed_contract is not empty AND dt_signed_contract_received is empty
- DO: set dt_signed_contract_received = Today; AND if dt_estimate_presented is empty, also
      backfill dt_estimate_presented = Today (a signed contract implies the estimate was presented).
- Idempotent: dt_signed_contract_received is write-once.

Fallback-only path: a Retail contract signed OUTSIDE Documents & Contracts and uploaded to
ev_signed_contract. The PRIMARY path (signed in D&C) is gate-signed-contract-dc (Tier 3, needs
the D&C webhook bridge — still GHL-owned). Both stamp the same write-once date, so idempotent.

Retail-only truth path per spec: Hybrid uses dt_insurance_contract_signed instead, never this
Retail signed-contract date. We follow the spec's IF exactly (no job-type filter — matching the
live GHL gate); the Retail-only intent is a usage note, not a gate condition.

Feeds the S40->S45/S46 mover (universal contract truth) and production-readiness (Retail).

ACTIVE (SUPPORTS_WRITE=True; ev_signed_contract, dt_signed_contract_received, dt_estimate_presented
all verified live via /debug/field-keys). Idempotent overlap with the still-Published GHL gate
until it's Drafted.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "gate-signed-contract-fallback-upload"
SUPPORTS_WRITE = True  # ACTIVE; keys verified live via /debug/field-keys

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
INPUT_FIELD = "ev_signed_contract"
OUTPUT_FIELD = "dt_signed_contract_received"
BACKFILL_FIELD = "dt_estimate_presented"


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    custom = custom_field_map(opp)
    ev_value = custom.get(INPUT_FIELD)
    dt_current = custom.get(OUTPUT_FIELD)
    estimate_empty = not truthy(custom.get(BACKFILL_FIELD))

    base = {
        "handler_id": HANDLER_ID,
        "target_field": OUTPUT_FIELD,
        "current_value": _to_str(dt_current),
    }

    if pipeline_id != PIPELINE_ID_SALES:
        return {**base, "decision": "no_op",
                "reason": f"pipelineId {pipeline_id!r} is not Sales ({PIPELINE_ID_SALES})"}

    if not truthy(ev_value):
        return {**base, "decision": "no_op",
                "reason": f"{INPUT_FIELD} is empty; nothing to stamp"}

    if truthy(dt_current):
        return {**base, "decision": "skip_idempotent",
                "reason": f"{OUTPUT_FIELD} already set ({dt_current}); write-once enforced"}

    target = date.today().isoformat()
    backfill = " (+ backfill dt_estimate_presented)" if estimate_empty else ""
    return {
        **base,
        "decision": "would_stamp",
        "target_value": target,
        "backfill_estimate": estimate_empty,  # execute() reads this to also stamp dt_estimate_presented
        "reason": (f"{INPUT_FIELD} present and {OUTPUT_FIELD} empty — "
                   f"would set {OUTPUT_FIELD} = {target}{backfill}"),
    }


def _to_str(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Stamp dt_signed_contract_received, plus backfill dt_estimate_presented if it was empty.

    Two-field write in one PUT (both write-once dates). Resolves each field id via the key map.
    """
    from ghl_client import ghl
    from ghl_writer import writer

    if decision.get("decision") != "would_stamp":
        return {"executed": False, "reason": "decision is not would_stamp"}

    opp = unwrap_opportunity({"opportunity": opp_data})
    opp_id = opp.get("id")
    pipeline_id = opp.get("pipelineId")
    target = decision.get("target_value")
    if not opp_id or target is None:
        return {"executed": False, "reason": "missing opp_id or target_value"}

    id_to_key = await ghl.get_opportunity_field_key_map()
    key_to_id = {v: k for k, v in id_to_key.items()}

    fields = [OUTPUT_FIELD]
    if decision.get("backfill_estimate"):
        fields.append(BACKFILL_FIELD)

    custom_fields = []
    for key in fields:
        fid = key_to_id.get(key)
        if fid:
            custom_fields.append({"id": fid, "field_value": target})
    if not custom_fields:
        return {"executed": False, "reason": f"could not resolve field ids for {fields!r}"}

    updates = {"customFields": custom_fields}
    response = await writer.update_opportunity(opp_id, pipeline_id, updates, handler_id=HANDLER_ID)
    return {"executed": True, "response": response, "applied": updates}
