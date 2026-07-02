"""GHL write client.

Two-layer safety (see write_guard.is_write_allowed):
  1. settings.writes_enabled must be True (master switch)
  2. EITHER the opp's current pipeline_id is in the pipeline allowlist
     (settings.write_allowed_pipeline_id_set — Production AND Sales are both live),
     OR the specific opp_id is in the opp allowlist
     (settings.write_allowed_opp_id_set — scoped test opps),
     OR the writing handler is in the per-handler allowlist
     (settings.write_live_handler_set).

If the decision is "not allowed" the writer raises WriteNotAllowed and NO request is made.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings
from write_guard import is_write_allowed

log = logging.getLogger("shadow.writer")


class WriteNotAllowed(Exception):
    """Raised when a write is attempted while writes are disabled or out-of-scope."""


class GHLWriter:
    def __init__(self) -> None:
        self.base = settings.ghl_api_base
        self.headers = {
            "Authorization": f"Bearer {settings.ghl_pit}",
            "Version": settings.ghl_api_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _enforce(
        self,
        opp_id: str | None,
        current_pipeline_id: str | None,
        handler_id: str | None,
    ) -> None:
        allowed, reason = is_write_allowed(
            opp_id,
            current_pipeline_id,
            writes_enabled=settings.writes_enabled,
            allowed_pipelines=settings.write_allowed_pipeline_id_set,
            allowed_opps=settings.write_allowed_opp_id_set,
            handler_id=handler_id,
            allowed_handlers=settings.write_live_handler_set,
        )
        if not allowed:
            raise WriteNotAllowed(reason)

    async def add_contact_tags(
        self,
        contact_id: str,
        tags: list[str],
        current_pipeline_id: str | None = None,
        handler_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /contacts/{contactId}/tags — adds milestone tags to a contact.

        Uses the pipeline_id for the write-guard allowlist check (same opp pipeline).
        """
        self._enforce(None, current_pipeline_id, handler_id)
        log.info(
            "WRITE POST /contacts/%s/tags handler=%s tags=%s",
            contact_id,
            handler_id,
            tags,
        )
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{self.base}/contacts/{contact_id}/tags",
                headers=self.headers,
                json={"tags": tags},
            )
            r.raise_for_status()
            return r.json()

    async def update_opportunity(
        self,
        opp_id: str,
        current_pipeline_id: str | None,
        updates: dict[str, Any],
        handler_id: str | None = None,
    ) -> dict[str, Any]:
        """PUT /opportunities/{id} with the given updates.

        Args:
            opp_id: Opportunity ID to update.
            current_pipeline_id: Pipeline the opp is CURRENTLY in (for allowlist check).
            updates: Body dict — supports keys like pipelineId, pipelineStageId,
                     customFields (list of {id, field_value}).
            handler_id: ID of the calling handler (for the per-handler write allowlist).
        """
        self._enforce(opp_id, current_pipeline_id, handler_id)
        log.info(
            "WRITE PUT /opportunities/%s pipeline=%s update_keys=%s",
            opp_id,
            current_pipeline_id,
            sorted(updates.keys()),
        )
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.put(
                f"{self.base}/opportunities/{opp_id}",
                headers=self.headers,
                json=updates,
            )
            r.raise_for_status()
            return r.json()


writer = GHLWriter()
