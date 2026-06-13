"""GHL Shadow Service.

Receives event payloads (webhook or manual replay), reads the current opportunity
state from GHL, runs each registered handler in shadow mode, and persists what
the handler WOULD have done. Never writes to GHL.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from config import settings
from db import get_session, init_db
from ghl_client import ghl
from handlers import gate_materials_verified, move_prod_p05_p10
from models import Decision, Event, Snapshot

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("shadow")

HANDLERS = [gate_materials_verified, move_prod_p05_p10]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    log.info(
        "shadow service ready (mode=%s, location=%s, db=%s, handlers=%d)",
        settings.mode,
        settings.ghl_location_id,
        settings.database_url.split("://", 1)[0],
        len(HANDLERS),
    )
    yield


app = FastAPI(title="GHL Shadow Service", version="0.1.0", lifespan=lifespan)

_DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"


# ---------- Endpoints ----------

@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(_DASHBOARD_PATH, media_type="text/html")


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": settings.mode,
        "writes_enabled": False,
        "location_id": settings.ghl_location_id,
        "handlers": [getattr(h, "HANDLER_ID", h.__name__) for h in HANDLERS],
    }


@app.post("/webhook/ghl")
async def webhook_ghl(
    req: Request,
    db: Session = Depends(get_session),
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
) -> dict[str, Any]:
    """Inbound webhook endpoint for GHL. Validates shared secret (if configured)."""
    _check_secret(x_webhook_secret)
    raw = await req.json()
    return await _process(db, raw, source="webhook")


@app.post("/webhook/replay")
async def webhook_replay(req: Request, db: Session = Depends(get_session)) -> dict[str, Any]:
    """Replay endpoint for local testing — no secret required."""
    raw = await req.json()
    return await _process(db, raw, source="replay")


@app.get("/events")
async def list_events(limit: int = 50, db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = db.query(Event).order_by(Event.id.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "received_at": e.received_at.isoformat(),
            "event_type": e.event_type,
            "opp_id": e.opp_id,
            "source": e.source,
        }
        for e in rows
    ]


@app.get("/decisions")
async def list_decisions(limit: int = 50, db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = db.query(Decision).order_by(Decision.id.desc()).limit(limit).all()
    return [
        {
            "id": d.id,
            "event_id": d.event_id,
            "handler": d.handler_id,
            "decision": d.decision,
            "target_field": d.target_field,
            "current_value": d.current_value,
            "target_value": d.target_value,
            "reason": d.reason,
            "decided_at": d.decided_at.isoformat(),
            "executed": d.executed,
        }
        for d in rows
    ]


@app.get("/events/{event_id}")
async def get_event(event_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
    e = db.get(Event, event_id)
    if not e:
        raise HTTPException(404, "event not found")
    return {
        "id": e.id,
        "received_at": e.received_at.isoformat(),
        "event_type": e.event_type,
        "opp_id": e.opp_id,
        "source": e.source,
        "raw_payload": e.raw_payload,
        "decisions": [
            {
                "id": d.id,
                "handler": d.handler_id,
                "decision": d.decision,
                "target_field": d.target_field,
                "current_value": d.current_value,
                "target_value": d.target_value,
                "reason": d.reason,
            }
            for d in e.decisions
        ],
    }


# ---------- Core processing ----------

async def _process(db: Session, raw: dict[str, Any], source: str) -> dict[str, Any]:
    event = _record_event(db, raw, source)
    snapshot, opp_data = await _maybe_snapshot(db, event, raw)
    decisions = _run_handlers(db, event, snapshot, opp_data)
    db.commit()
    log.info(
        "event_id=%s opp_id=%s source=%s decisions=%s",
        event.id,
        event.opp_id,
        source,
        [(d.handler_id, d.decision) for d in decisions],
    )
    return {
        "event_id": event.id,
        "opp_id": event.opp_id,
        "snapshot_id": snapshot.id if snapshot else None,
        "decisions": [
            {
                "handler": d.handler_id,
                "decision": d.decision,
                "target_field": d.target_field,
                "current_value": d.current_value,
                "target_value": d.target_value,
                "reason": d.reason,
            }
            for d in decisions
        ],
    }


def _record_event(db: Session, raw: dict[str, Any], source: str) -> Event:
    e = Event(
        event_type=raw.get("type") or raw.get("event_type"),
        opp_id=_extract_opp_id(raw),
        source=source,
        raw_payload=raw,
    )
    db.add(e)
    db.flush()
    return e


async def _maybe_snapshot(
    db: Session, event: Event, raw: dict[str, Any]
) -> tuple[Snapshot | None, dict[str, Any]]:
    """Try to pull a fresh snapshot from GHL. Fall back to the inline payload."""
    inline_opp = raw.get("opportunity") if isinstance(raw.get("opportunity"), dict) else raw
    if not event.opp_id or not settings.ghl_pit:
        return None, inline_opp

    try:
        full = await ghl.get_opportunity(event.opp_id)
    except Exception as exc:
        log.warning("snapshot fetch failed for opp_id=%s: %s — using inline payload", event.opp_id, exc)
        return None, inline_opp

    opp_obj = full.get("opportunity", full)
    snap = Snapshot(
        event_id=event.id,
        opp_id=event.opp_id,
        pipeline_id=opp_obj.get("pipelineId"),
        stage_id=opp_obj.get("pipelineStageId"),
        opp_data=full,
    )
    db.add(snap)
    db.flush()
    return snap, opp_obj


def _run_handlers(
    db: Session, event: Event, snapshot: Snapshot | None, opp_data: dict[str, Any]
) -> list[Decision]:
    wrapped = {"opportunity": opp_data}
    decisions: list[Decision] = []
    for h in HANDLERS:
        try:
            result = h.evaluate(wrapped)
        except Exception:
            log.exception("handler %s crashed", getattr(h, "HANDLER_ID", h.__name__))
            continue
        d = Decision(
            event_id=event.id,
            snapshot_id=snapshot.id if snapshot else None,
            handler_id=result.get("handler_id", "unknown"),
            decision=result.get("decision", "unknown"),
            target_field=result.get("target_field"),
            target_value=_stringify(result.get("target_value")),
            current_value=_stringify(result.get("current_value")),
            reason=result.get("reason"),
            details=result,
            executed=False,
        )
        db.add(d)
        decisions.append(d)
    db.flush()
    return decisions


def _check_secret(provided: str | None) -> None:
    if not settings.webhook_secret:
        return
    if provided != settings.webhook_secret:
        raise HTTPException(401, "invalid webhook secret")


def _extract_opp_id(raw: dict[str, Any]) -> str | None:
    if not isinstance(raw, dict):
        return None
    if isinstance(raw.get("opportunity_id"), str):
        return raw["opportunity_id"]
    opp = raw.get("opportunity")
    if isinstance(opp, dict) and isinstance(opp.get("id"), str):
        return opp["id"]
    if isinstance(raw.get("id"), str) and "opportunity" in str(raw.get("type", "")).lower():
        return raw["id"]
    return None


def _stringify(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)
