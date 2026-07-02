"""Read-only GHL API client.

This module intentionally contains NO write methods (PUT/POST/PATCH/DELETE).
Shadow mode must not be able to mutate CRM state, even by mistake.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings

log = logging.getLogger("shadow.ghl")


class GHLReadOnlyClient:
    def __init__(self) -> None:
        self.base = settings.ghl_api_base
        self.headers = {
            "Authorization": f"Bearer {settings.ghl_pit}",
            "Version": settings.ghl_api_version,
            "Accept": "application/json",
        }
        # Cache: {field_id: short_field_key}  for opportunity custom fields
        self._field_key_cache: dict[str, str] = {}

    async def get_opportunity(self, opp_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.base}/opportunities/{opp_id}", headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def probe(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read-only diagnostic GET that never raises — returns status + body snippet.

        Used only by /debug custom-object spikes to discover which GHL endpoints/scopes
        actually work with our PIT. Read-only; safe.
        """
        url = f"{self.base}{path}"
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(url, headers=self.headers, params=params or {})
            ctype = r.headers.get("content-type", "")
            body: Any = r.json() if "application/json" in ctype else r.text[:600]
            return {"path": path, "status": r.status_code, "ok": r.is_success, "body": body}
        except Exception as exc:  # noqa: BLE001 — diagnostic, report everything
            return {"path": path, "status": None, "ok": False, "error": repr(exc)}

    async def get_pipelines(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{self.base}/opportunities/pipelines",
                headers=self.headers,
                params={"locationId": settings.ghl_location_id},
            )
            r.raise_for_status()
            return r.json().get("pipelines", [])

    async def get_location(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.base}/locations/{settings.ghl_location_id}", headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def search_opportunities_by_contact(self, contact_id: str, limit: int = 5) -> list[dict[str, Any]]:
        """Read-only search: find opportunities for a contact, most recent first."""
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{self.base}/opportunities/search",
                headers=self.headers,
                params={
                    "location_id": settings.ghl_location_id,
                    "contact_id": contact_id,
                    "limit": limit,
                },
            )
            r.raise_for_status()
            return r.json().get("opportunities", [])

    async def get_opportunity_field_key_map(self) -> dict[str, str]:
        """Return {field_id: short_field_key} for opportunity custom fields.

        The /opportunities/{id} response returns customFields keyed by opaque ID,
        not by the human-readable fieldKey (e.g. 'dt_install_scheduled'). Handlers
        look up by fieldKey, so we need this translation table.

        Cached for the life of the process; restart the service to refresh.
        """
        if self._field_key_cache:
            return self._field_key_cache
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    f"{self.base}/locations/{settings.ghl_location_id}/customFields",
                    headers=self.headers,
                    params={"model": "opportunity"},
                )
                r.raise_for_status()
                fields = r.json().get("customFields", [])
        except Exception as exc:
            log.warning("failed to fetch opp custom-field definitions: %s", exc)
            return {}
        m: dict[str, str] = {}
        for f in fields:
            fid = f.get("id")
            key = f.get("fieldKey", "")
            if fid and key:
                # Strip "opportunity." / "contact." prefix
                m[fid] = key.split(".")[-1]
        self._field_key_cache = m
        log.info("loaded %d opportunity custom-field mappings", len(m))
        return m


ghl = GHLReadOnlyClient()
