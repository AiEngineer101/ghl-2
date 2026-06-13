"""Shared helpers for opportunity payload parsing."""
from __future__ import annotations

from typing import Any


def unwrap_opportunity(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the opportunity object regardless of whether the payload wraps it."""
    if isinstance(payload, dict) and isinstance(payload.get("opportunity"), dict):
        return payload["opportunity"]
    return payload


def custom_field_map(opp: dict[str, Any]) -> dict[str, Any]:
    """Map GHL customFields list -> {field_key: value}.

    GHL payloads vary: items can use `fieldKey`, `key`, `name`, or `id`. We try each.
    """
    fields = opp.get("customFields") or opp.get("custom_fields") or []
    out: dict[str, Any] = {}
    for f in fields:
        if not isinstance(f, dict):
            continue
        key = f.get("fieldKey") or f.get("key") or f.get("name") or f.get("id")
        if not key:
            continue
        key = str(key).split(".")[-1]
        out[key] = f.get("fieldValue") or f.get("value")
    return out


def truthy(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str) and v.strip() == "":
        return False
    if isinstance(v, list) and len(v) == 0:
        return False
    return True


def yes(value: Any) -> bool:
    """Return True if a truth-flag (tf_*) field equals Yes.

    GHL stores Yes/No fields variably: as the string "Yes", as the list ["Yes"], or
    sometimes case-shifted. Be tolerant.
    """
    if value is None:
        return False
    if isinstance(value, list):
        return any(yes(v) for v in value)
    return str(value).strip().lower() == "yes"
