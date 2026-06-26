"""Pure helpers to pull the opportunity/contact id out of the many GHL webhook shapes.

No I/O, no deps — like write_guard.py — so it's trivially unit-testable without importing
the FastAPI app (which pulls in sqlalchemy etc.).
"""
from __future__ import annotations

from typing import Any


def extract_opp_id(raw: dict[str, Any]) -> str | None:
    """Extract opportunity ID from the various GHL webhook payload shapes."""
    if not isinstance(raw, dict):
        return None

    # 1. Top-level opportunity_id (manual replay shape)
    v = raw.get("opportunity_id")
    if isinstance(v, str) and v.strip():
        return v.strip()

    # 2. Nested opportunity object with id
    opp = raw.get("opportunity")
    if isinstance(opp, dict) and isinstance(opp.get("id"), str) and opp["id"].strip():
        return opp["id"].strip()

    # 3. customData.opportunity_id (GHL webhook action with Custom Data)
    cd = raw.get("customData")
    if isinstance(cd, dict):
        for k in ("opportunity_id", "opp_id", "opportunityId"):
            v = cd.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

    # 4. raw.id when raw.type names an opportunity event
    if isinstance(raw.get("id"), str) and "opportunity" in str(raw.get("type", "")).lower():
        return raw["id"]

    # 5. GHL default custom-data webhook shape: opportunity fields live at the ROOT
    #    (opportunity_name, pipeline_id, pipeline_name, status, ... and the opp id is
    #    root `id`). There's no `type`/`opportunity_id`/`customData`, so steps 1-4 miss it.
    #    Only treat root `id` as the opp id when an opportunity-only marker is present
    #    alongside it, so we never mistake a contact-only payload's id for an opp.
    rid = raw.get("id")
    if isinstance(rid, str) and rid.strip() and (
        raw.get("pipeline_id") or raw.get("pipeline_name") or raw.get("opportunity_name")
    ):
        return rid.strip()

    return None


def extract_contact_id(raw: dict[str, Any]) -> str | None:
    """Extract contact ID — used as a fallback to look up opportunities."""
    if not isinstance(raw, dict):
        return None
    v = raw.get("contact_id")
    if isinstance(v, str) and v.strip():
        return v.strip()
    contact = raw.get("contact")
    if isinstance(contact, dict) and isinstance(contact.get("id"), str):
        return contact["id"]
    return None
