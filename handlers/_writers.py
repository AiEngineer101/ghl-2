"""Shared execute helpers for handler write paths."""
from __future__ import annotations

from typing import Any

from handlers._common import unwrap_opportunity


async def stamp_custom_field(
    opp_data: dict[str, Any],
    decision: dict[str, Any],
    field_key: str,
) -> dict[str, Any]:
    """PUT a single customField value to GHL. Used by TF/EV→DT gate handlers.

    The decision must be 'would_stamp' with a target_value string. Looks up
    the field's GHL ID via the field_key_map cache, then issues a PUT.
    """
    from ghl_client import ghl
    from ghl_writer import writer

    if decision.get("decision") != "would_stamp":
        return {"executed": False, "reason": "decision is not would_stamp"}

    opp = unwrap_opportunity({"opportunity": opp_data})
    opp_id = opp.get("id")
    pipeline_id = opp.get("pipelineId")
    target_value = decision.get("target_value")
    if not opp_id or target_value is None:
        return {"executed": False, "reason": "missing opp_id or target_value"}

    id_to_key = await ghl.get_opportunity_field_key_map()
    key_to_id = {v: k for k, v in id_to_key.items()}
    fid = key_to_id.get(field_key)
    if not fid:
        return {
            "executed": False,
            "reason": f"could not resolve field id for {field_key!r}",
        }

    updates = {
        "customFields": [{"id": fid, "field_value": target_value}],
    }
    response = await writer.update_opportunity(
        opp_id, pipeline_id, updates, handler_id=decision.get("handler_id")
    )
    return {"executed": True, "response": response, "applied": updates}


async def _last_good_custom_fields(
    stage_code: str | None, pipeline_code: str | None
) -> list[dict[str, Any]]:
    """Resolve the sys_last_good_* audit fields to GHL id-keyed customField entries.

    Returns the entries that resolve (silently drops any whose field id can't be found,
    matching the Production movers' best-effort behavior).
    """
    from ghl_client import ghl

    id_to_key = await ghl.get_opportunity_field_key_map()
    key_to_id = {v: k for k, v in id_to_key.items()}
    out: list[dict[str, Any]] = []
    for key, value in (
        ("sys_last_good_pipeline_code", pipeline_code),
        ("sys_last_good_stage_code", stage_code),
    ):
        if value is None:
            continue
        fid = key_to_id.get(key)
        if fid:
            out.append({"id": fid, "field_value": value})
    return out


async def move_stage(
    opp_data: dict[str, Any],
    decision: dict[str, Any],
    *,
    last_good_stage_code: str | None = None,
    last_good_pipeline_code: str | None = None,
) -> dict[str, Any]:
    """PUT pipelineStageId to the decision's target_value. Used by movers and the enforcer.

    If last_good_stage_code is given, also stamp the sys_last_good_* audit fields — but in a
    SEPARATE PUT, issued AFTER the move.

    Why two writes: GHL silently drops `customFields` when they're combined with a
    `pipelineStageId` change in the same PUT. Verified 2026-06-27 — an opp climbed
    S10->S20->S30->S40 (three combined-PUT moves) yet sys_last_good_stage_code stayed at its
    S10 seed the whole time. A standalone customFields PUT *does* persist (the exact path the
    EV/TF gates use, proven when the inspection gate stamp landed). So: move first, audit second.
    The move is the must-have; the audit write is best-effort and never blocks the move.
    """
    from ghl_writer import writer

    accepted = ("would_move", "would_rewind")
    if decision.get("decision") not in accepted:
        return {"executed": False, "reason": f"decision is not in {accepted}"}

    opp = unwrap_opportunity({"opportunity": opp_data})
    opp_id = opp.get("id")
    pipeline_id = opp.get("pipelineId")
    target_stage_id = decision.get("target_value")
    if not opp_id or not target_stage_id:
        return {"executed": False, "reason": "missing opp_id or target_value"}

    handler_id = decision.get("handler_id")

    # 1) The stage move (must-have, top-level field — this one IS honored in a move PUT).
    move_updates: dict[str, Any] = {"pipelineStageId": target_stage_id}
    response = await writer.update_opportunity(
        opp_id, pipeline_id, move_updates, handler_id=handler_id
    )
    applied: dict[str, Any] = dict(move_updates)

    # 2) The sys_last_good_* audit fields, as a SEPARATE customFields PUT (see docstring).
    if last_good_stage_code is not None:
        cfs = await _last_good_custom_fields(last_good_stage_code, last_good_pipeline_code)
        if cfs:
            await writer.update_opportunity(
                opp_id, pipeline_id, {"customFields": cfs}, handler_id=handler_id
            )
            applied["customFields"] = cfs

    return {"executed": True, "response": response, "applied": applied}
