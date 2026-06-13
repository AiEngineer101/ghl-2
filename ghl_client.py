"""Read-only GHL API client.

This module intentionally contains NO write methods (PUT/POST/PATCH/DELETE).
Shadow mode must not be able to mutate CRM state, even by mistake.
"""
from __future__ import annotations

from typing import Any

import httpx

from config import settings


class GHLReadOnlyClient:
    def __init__(self) -> None:
        self.base = settings.ghl_api_base
        self.headers = {
            "Authorization": f"Bearer {settings.ghl_pit}",
            "Version": settings.ghl_api_version,
            "Accept": "application/json",
        }

    async def get_opportunity(self, opp_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.base}/opportunities/{opp_id}", headers=self.headers)
            r.raise_for_status()
            return r.json()

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


ghl = GHLReadOnlyClient()
