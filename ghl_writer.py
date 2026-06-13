"""GHL write client.

Two-layer safety:
  1. settings.writes_enabled must be True (master switch)
  2. The opportunity's current pipeline_id must be in the write allowlist
     (settings.write_allowed_pipeline_id_set) — defaults to Production pipeline only.

If either check fails the writer raises WriteNotAllowed and NO request is made.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings

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

    def _enforce(self, current_pipeline_id: str | None) -> None:
        if not settings.writes_enabled:
            raise WriteNotAllowed("WRITES_ENABLED=false — refuse to write")
        allowed = settings.write_allowed_pipeline_id_set
        if current_pipeline_id not in allowed:
            raise WriteNotAllowed(
                f"pipeline {current_pipeline_id!r} is not in write allowlist {sorted(allowed)}"
            )

    async def update_opportunity(
        self,
        opp_id: str,
        current_pipeline_id: str | None,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """PUT /opportunities/{id} with the given updates.

        Args:
            opp_id: Opportunity ID to update.
            current_pipeline_id: Pipeline the opp is CURRENTLY in (for allowlist check).
            updates: Body dict — supports keys like pipelineId, pipelineStageId,
                     customFields (list of {id, field_value}).
        """
        self._enforce(current_pipeline_id)
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
