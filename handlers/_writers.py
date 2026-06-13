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
    response = await writer.update_opportunity(opp_id, pipeline_id, updates)
    return {"executed": True, "response": response, "applied": updates}


async def move_stage(
    opp_data: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    """PUT pipelineStageId to the decision's target_value. Used by movers."""
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

    updates = {"pipelineStageId": target_stage_id}
    response = await writer.update_opportunity(opp_id, pipeline_id, updates)
    return {"executed": True, "response": response, "applied": updates}
