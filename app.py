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
    derived_production_readiness,
    enforce_sales_stage_truth_invariant,
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
    move_sales_s40_s45_funding_pending,
    move_sales_s45_s46_initial_funding,
    move_sales_s46_s50_handoff_to_production,
    move_sales_s50_production_pipeline,
)
from models import Decision, Event, Snapshot
from webhook_payload import extract_contact_id as _extract_contact_id
from webhook_payload import extract_opp_id as _extract_opp_id

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
    # --- Sales pipeline (ACTIVE — all handlers SUPPORTS_WRITE=True; Sales is pipeline-live via
    #     the writer's pipeline-allowlist, so writes apply to EVERY Sales opp) ---
    gate_front_home_photo,
    gate_inspection_complete,
    gate_insurance_scope,
    derived_production_readiness,
    move_sales_s10_s20_inspection_complete,
    move_sales_s20_s30_scope_pending,
    move_sales_s30_s40_job_pending_approval,
    move_sales_s40_s45_funding_pending,
    move_sales_s45_s46_initial_funding,
    move_sales_s46_s50_handoff_to_production,
    move_sales_s50_production_pipeline,
    # Enforcer runs LAST (post-mover) so it only rewinds genuine Sales drift, never a
    # legitimate forward move (which it sees as the still-pre-move snapshot stage).
    enforce_sales_stage_truth_invariant,
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


@app.get("/debug/field-keys")
async def debug_field_keys(contains: str = "") -> dict[str, Any]:
    """Read-only: dump the opportunity custom-field key map (GHL field id -> short key).

    Diagnostic for write-resolution issues (e.g. is 'sys_last_good_stage_code' a real key?).
    Optional ?contains= filters to keys containing the substring.
    """
    id_to_key = await ghl.get_opportunity_field_key_map()
    keys = sorted(id_to_key.values())
    if contains:
        keys = [k for k in keys if contains.lower() in k.lower()]
    return {"total": len(id_to_key), "matched": len(keys), "keys": keys}


@app.get("/debug/test-write-lastgood/{opp_id}")
async def debug_test_write_lastgood(opp_id: str, value: str = "DBG-TEST") -> dict[str, Any]:
    """DIAGNOSTIC (temporary): write `value` to sys_last_good_stage_code, then read it back.

    Definitively answers whether that field is writable via the API (before != after) or
    silently rejected (before == after). Uses the normal writer (guard applies).
    """
    from handlers._common import custom_field_map
    from ghl_writer import writer

    async def _read() -> tuple[str | None, str | None]:
        full = await ghl.get_opportunity(opp_id)
        opp = full.get("opportunity", full)
        id_to_key = await ghl.get_opportunity_field_key_map()
        for cf in opp.get("customFields", []) or []:
            if isinstance(cf, dict) and not cf.get("fieldKey"):
                cf["fieldKey"] = id_to_key.get(cf.get("id"), "")
        return opp.get("pipelineId"), custom_field_map(opp).get("sys_last_good_stage_code")

    from handlers._writers import _last_good_custom_fields

    pipeline_id, before = await _read()
    # EXACT replica of move_stage's second PUT: both sys_last_good_* fields together.
    cfs = await _last_good_custom_fields(value, "PL_SALES")
    resp = await writer.update_opportunity(opp_id, pipeline_id, {"customFields": cfs})
    wrote_resp_keys = sorted(resp.keys()) if isinstance(resp, dict) else str(type(resp))
    _, after = await _read()
    return {
        "sent_customFields": cfs,
        "before": before,
        "wrote": value,
        "after": after,
        "write_persisted": before != after and after == value,
        "write_response_keys": wrote_resp_keys,
    }


@app.get("/debug/opp-fields/{opp_id}")
async def debug_opp_fields(opp_id: str, contains: str = "") -> dict[str, Any]:
    """Read-only: dump an opp's custom fields (key -> value) as our code sees them.

    Confirms what GHL actually persisted (e.g. did sys_last_good_stage_code take our write?).
    Optional ?contains= filters keys by substring.
    """
    from handlers._common import custom_field_map

    full = await ghl.get_opportunity(opp_id)
    opp = full.get("opportunity", full)
    try:
        id_to_key = await ghl.get_opportunity_field_key_map()
        for cf in opp.get("customFields", []) or []:
            if isinstance(cf, dict) and not cf.get("fieldKey"):
                cf["fieldKey"] = id_to_key.get(cf.get("id"), "")
    except Exception:
        pass
    fields = custom_field_map(opp)
    if contains:
        fields = {k: v for k, v in fields.items() if contains.lower() in k.lower()}
    return {
        "opp_id": opp_id,
        "pipelineId": opp.get("pipelineId"),
        "pipelineStageId": opp.get("pipelineStageId"),
        "fields": fields,
    }


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": settings.mode,
        "writes_enabled": settings.writes_enabled,
        "write_allowed_pipelines": sorted(settings.write_allowed_pipeline_id_set),
        "write_allowed_opps": sorted(settings.write_allowed_opp_id_set),
        "write_live_handlers": sorted(settings.write_live_handler_set),
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


def _stringify(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)
