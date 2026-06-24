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
from handlers import (
    derived_closeout_cash_reconciled,
    derived_closeout_ready,
    enforce_stage_truth_invariant,
    gate_front_home_photo,
    gate_inspection_complete,
    gate_insurance_scope,
    gate_materials_verified,
    gate_work_completed,
    gate_work_started,
    move_prod_p05_p10,
    move_prod_p10_p20_work_started,
    move_prod_p20_p30_work_completed,
    move_prod_p30_p40_closeout_pending,
    move_prod_p40_p50_closeout_complete,
    move_sales_s10_s20_inspection_complete,
    move_sales_s20_s30_scope_pending,
    move_sales_s30_s40_job_pending_approval,
)
from models import Decision, Event, Snapshot

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("shadow")

# Order matters: gates stamp first, derived truths compute next, movers advance after,
# enforcer runs LAST so it sees the post-mover state and only rewinds if invariants
# are still broken.
HANDLERS = [
    gate_materials_verified,
    gate_work_started,
    gate_work_completed,
    derived_closeout_cash_reconciled,
    derived_closeout_ready,
    move_prod_p05_p10,
    move_prod_p10_p20_work_started,
    move_prod_p20_p30_work_completed,
    move_prod_p30_p40_closeout_pending,
    move_prod_p40_p50_closeout_complete,
    enforce_stage_truth_invariant,
    # --- Sales pipeline (SHADOW / watch-only — SUPPORTS_WRITE=False until a test harness exists) ---
    gate_front_home_photo,
    gate_inspection_complete,
    gate_insurance_scope,
    move_sales_s10_s20_inspection_complete,
    move_sales_s20_s30_scope_pending,
    move_sales_s30_s40_job_pending_approval,
]


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
        "writes_enabled": settings.writes_enabled,
        "write_allowed_pipelines": sorted(settings.write_allowed_pipeline_id_set),
        "write_allowed_opps": sorted(settings.write_allowed_opp_id_set),
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


@app.post("/admin/replay-opp/{opp_id}")
async def admin_replay_opp(
    opp_id: str,
    db: Session = Depends(get_session),
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
) -> dict[str, Any]:
    """Synthetic event for a specific opportunity.

    Fetches the opp from GHL, runs all handlers, and (if WRITES_ENABLED) executes
    any would_move/would_stamp decisions whose handler implements execute().
    """
    _check_secret(x_webhook_secret)
    payload = {"type": "AdminReplay", "opportunity_id": opp_id}
    return await _process(db, payload, source="admin")


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

    # If no opp_id in the payload, try contact_id fallback (GHL contact-centric webhooks)
    if not event.opp_id:
        contact_id = _extract_contact_id(raw)
        if contact_id and settings.ghl_pit:
            try:
                opps = await ghl.search_opportunities_by_contact(contact_id)
            except Exception as exc:
                log.warning("contact->opp lookup failed for contact_id=%s: %s", contact_id, exc)
                opps = []
            if opps:
                # Use most-recently-updated opportunity
                opps.sort(key=lambda o: o.get("updatedAt", ""), reverse=True)
                event.opp_id = opps[0].get("id")
                log.info("resolved opp via contact_id=%s -> opp_id=%s", contact_id, event.opp_id)
                db.flush()

    snapshot, opp_data = await _maybe_snapshot(db, event, raw)
    decisions = _run_handlers(db, event, snapshot, opp_data)
    if settings.writes_enabled:
        await _maybe_execute(db, decisions, opp_data)
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

    # Enrich customFields with fieldKey so handlers can look them up by name.
    # GHL's opp API returns customFields keyed by ID only.
    try:
        id_to_key = await ghl.get_opportunity_field_key_map()
        for cf in opp_obj.get("customFields", []) or []:
            if isinstance(cf, dict) and not cf.get("fieldKey"):
                cf["fieldKey"] = id_to_key.get(cf.get("id"), "")
    except Exception as exc:
        log.warning("could not enrich custom field keys: %s", exc)
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


async def _maybe_execute(
    db: Session, decisions: list[Decision], opp_data: dict[str, Any]
) -> None:
    """For each decision whose handler supports writes and asked to act, call execute()."""
    decision_dicts = {d.handler_id: d for d in decisions}
    for h in HANDLERS:
        if not getattr(h, "SUPPORTS_WRITE", False):
            continue
        handler_id = getattr(h, "HANDLER_ID", h.__name__)
        d = decision_dicts.get(handler_id)
        if not d:
            continue
        # Only execute on "active" decisions (would_move / would_stamp). Skip no_op etc.
        if not str(d.decision).startswith("would_"):
            continue
        try:
            result = await h.execute(opp_data, d.details or {})
            d.executed = bool(result.get("executed"))
            # Trim the GHL response (can be large) — keep just the applied diff.
            trimmed = {
                "executed": result.get("executed"),
                "applied": result.get("applied"),
                "reason": result.get("reason"),
            }
            existing_details = dict(d.details or {})
            existing_details["execution"] = trimmed
            d.details = existing_details
            log.info(
                "EXECUTED handler=%s opp_id=%s decision=%s executed=%s",
                handler_id,
                opp_data.get("id"),
                d.decision,
                result.get("executed"),
            )
        except Exception as exc:
            log.exception("execute failed for handler %s", handler_id)
            existing_details = dict(d.details or {})
            existing_details["execution_error"] = repr(exc)
            d.details = existing_details
            d.executed = False
    db.flush()


def _check_secret(provided: str | None) -> None:
    if not settings.webhook_secret:
        return
    if provided != settings.webhook_secret:
        raise HTTPException(401, "invalid webhook secret")


def _extract_opp_id(raw: dict[str, Any]) -> str | None:
    """Extract opportunity ID from various GHL webhook payload shapes."""
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

    return None


def _extract_contact_id(raw: dict[str, Any]) -> str | None:
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


def _stringify(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)
