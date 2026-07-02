"""Pure helpers for GHL custom objects (Insurance Claim / Supplement / Change Order / Crew).

No I/O — parsing + selection only, so it's unit-testable like write_guard.py / webhook_payload.py.
The async fetches live in custom_object_reader.py (which uses ghl_client + these helpers).

Live facts confirmed via the /debug/co-probe spike (2026-07-02, "World A"):
  - schema keys below are the real GHL keys (from GET /objects/).
  - opp->record links are readable via GET /associations/relations/{recordId}; each relation is an
    undirected pair {firstObjectKey/firstRecordId, secondObjectKey/secondRecordId, associationId}.
  - The custom-object RECORD field shape is not yet verified against a live Claim (none created yet);
    record_fields() is written tolerantly and must be re-checked against a real record.
"""
from __future__ import annotations

from typing import Any

# Live schema keys (GET /objects/, 2026-07-02)
SCHEMA_INSURANCE_CLAIM = "custom_objects.insurance_claims"
SCHEMA_SUPPLEMENT = "custom_objects.supplements"
SCHEMA_CHANGE_ORDER = "custom_objects.change_orders"
SCHEMA_CREW = "custom_objects.crews"

# Live association keys (GET /associations/, 2026-07-02) — informational (relations carry these).
ASSOC_JOB_CLAIM = "job_insurance_claim"          # opportunity <-> insurance_claims
ASSOC_CARRIER_CLAIM = "carrier_insurance_claims"  # business    <-> insurance_claims
ASSOC_POLICYHOLDER_CLAIM = "policy_holder_insurance_claims"  # contact <-> insurance_claims
ASSOC_ADJUSTER_CLAIM = "adjuster_adjusted_claims"  # contact    <-> insurance_claims
ASSOC_CHANGE_ORDER_JOB = "change_orders_job"       # change_orders <-> opportunity
ASSOC_SUPPLEMENT_JOB = "supplements_job"           # supplements   <-> opportunity


def related_record_ids(relations_body: Any, object_key: str) -> list[str]:
    """From a GET /associations/relations/{id} body, return the record ids linked to `object_key`.

    Relations are undirected pairs — the target may be on either side. De-dupes, preserves order.
    """
    out: list[str] = []
    rels = relations_body.get("relations", []) if isinstance(relations_body, dict) else []
    for r in rels:
        if not isinstance(r, dict):
            continue
        if r.get("firstObjectKey") == object_key and r.get("firstRecordId"):
            rid = r["firstRecordId"]
        elif r.get("secondObjectKey") == object_key and r.get("secondRecordId"):
            rid = r["secondRecordId"]
        else:
            continue
        if rid not in out:
            out.append(rid)
    return out


def _present(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, list):
        return len(v) > 0
    return True


def _money(v: Any) -> float:
    """Parse a monetary field to float; non-numeric/blank -> 0.0."""
    if v is None:
        return 0.0
    try:
        return float(str(v).replace(",", "").replace("$", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


# The Opportunity keys our EXISTING Insurance-path handlers read today, and where they come from
# on the new objects. ⚠️ Spec-based (data-model §3) — LIVE KEYS UNVERIFIED (no Claim record exists
# yet). Re-check against a real Claim before this is wired into any live handler.
def claim_identity_fields(claim_fields: dict[str, Any]) -> dict[str, Any]:
    """Map an Insurance Claim record -> the Opportunity-equivalent keys handlers currently read.

    ONLY the unambiguous 1:1 identity/scope fields. NOT included (by design):
      - carrier name -> comes from the Carrier *Company association*, not a claim field
      - payment-truth DTs / contract value -> these are ROLLUPS (see revenue_rollup), not 1:1
    """
    out: dict[str, Any] = {}
    if not isinstance(claim_fields, dict):
        return out
    if _present(claim_fields.get("claim_number")):
        out["seg_insurance_claim_number"] = claim_fields["claim_number"]
    if _present(claim_fields.get("dt_insurance_scope_received")):
        out["dt_insurance_scope_received"] = claim_fields["dt_insurance_scope_received"]
    return out


def revenue_rollup(
    supplements: list[dict[str, Any]] | None,
    change_orders: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Compute money rollups from child records, per data-model §9.

    Inputs are lists of {"id", "fields"} (as custom_object_reader returns). Pure/computational
    and shadow-only — this does NOT write to the Opportunity. §9 maps:
      Σ amt_supplement_approved  + Σ billable amt_change_order_approved -> amt_contract_value
      Σ amt_supplement_received                                        -> amt_total_funds_received
    (§9 lists 'approved' for funds too; we surface both approved and received transparently.)
    """
    supps = supplements or []
    cos = change_orders or []

    def f(rec: dict[str, Any], key: str) -> float:
        return _money((rec.get("fields") or {}).get(key))

    supp_approved = sum(f(s, "amt_supplement_approved") for s in supps)
    supp_received = sum(f(s, "amt_supplement_received") for s in supps)
    billable_co = sum(
        f(c, "amt_change_order_approved")
        for c in cos
        # data-model §5: seg_change_order_treatment "Customer Pays (Billable)" is the billable path
        if str((c.get("fields") or {}).get("seg_change_order_treatment", "")).strip().lower().startswith("customer pays")
    )
    return {
        "supplements_count": len(supps),
        "change_orders_count": len(cos),
        "supplements_approved_total": supp_approved,
        "supplements_received_total": supp_received,
        "billable_change_orders_total": billable_co,
        "rollup_contract_value_contribution": supp_approved + billable_co,
        "rollup_funds_received_contribution": supp_received,
    }


def record_fields(record_body: Any) -> dict[str, Any]:
    """Flatten a GET /objects/{key}/records/{id} response to {field_key: value}.

    Tolerant of the response wrapper (`record`) and the field container (`properties`), since the
    live record shape isn't verified yet. Falls back to top-level scalars minus system keys.
    """
    if not isinstance(record_body, dict):
        return {}
    rec = record_body.get("record") if isinstance(record_body.get("record"), dict) else record_body
    props = rec.get("properties")
    if isinstance(props, dict):
        return dict(props)
    system = {"id", "owner", "followers", "locationId", "createdAt", "updatedAt", "objectKey"}
    return {k: v for k, v in rec.items() if k not in system}
