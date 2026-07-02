"""Read an opportunity's associated custom-object records (Insurance Claim / Supplement /
Change Order). Thin async layer over ghl_client + the pure custom_objects helpers. READ-ONLY.

World A (confirmed 2026-07-02): GET /associations/relations/{oppId} returns the opp's links, and
each linked custom record is fetched by id. This is the foundation the future Insurance-path
readers / revenue rollup sit on — no writes, no mover wiring here (that waits on Bill's contract).
"""
from __future__ import annotations

from typing import Any

import custom_objects as co


async def get_records_for_opp(opp_id: str, schema_key: str) -> list[dict[str, Any]]:
    """Return the custom-object records of `schema_key` linked to the opp, as
    [{"id": <record_id>, "fields": {<key>: <value>}}]. Read-only; [] if none/unreadable."""
    from ghl_client import ghl

    relations = await ghl.get_record_relations(opp_id)
    ids = co.related_record_ids(relations, schema_key)
    out: list[dict[str, Any]] = []
    for rid in ids:
        rec = await ghl.get_object_record(schema_key, rid)
        out.append({"id": rid, "fields": co.record_fields(rec)})
    return out


async def get_claim_for_opp(opp_id: str) -> dict[str, Any] | None:
    """The opp's Insurance Claim (1 per job) as {"id","fields"}, or None."""
    recs = await get_records_for_opp(opp_id, co.SCHEMA_INSURANCE_CLAIM)
    return recs[0] if recs else None


async def get_change_orders_for_opp(opp_id: str) -> list[dict[str, Any]]:
    return await get_records_for_opp(opp_id, co.SCHEMA_CHANGE_ORDER)


async def get_supplements_for_opp(opp_id: str) -> list[dict[str, Any]]:
    return await get_records_for_opp(opp_id, co.SCHEMA_SUPPLEMENT)
