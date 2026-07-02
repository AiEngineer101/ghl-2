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
