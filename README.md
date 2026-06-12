# GHL Shadow Service

A read-only Python service that mirrors selected GHL workflows. It listens to event
payloads, evaluates each handler against the current opportunity state, and records
**what it would have done**. It never writes to GHL.

> **Authority.** This service is a derived execution layer. Specs in `workflow/` are
> the source of truth. If a handler disagrees with its spec, the spec wins.

## What's in the box (v0.1)

Two shadow handlers covering production-phase workflows:

| Handler | Mirrors | Spec |
|---|---|---|
| `gate-materials-verified` | `WF \| Gate \| MaterialsVerified` | `workflow/01-gates/ev-to-dt/gate-materials-verified.md` |
| `move-prod-p05-p10-install-scheduled` | `WF \| Move \| Prod \| P05→P10 Install Scheduled` | `workflow/03-move/production/move-prod-p05-p10-install-scheduled.md` |

Each handler returns one of these decisions:

| Decision | Meaning |
|---|---|
| `would_stamp` | Gate would write a date field |
| `would_move` | Mover would change the pipeline stage |
| `skip_idempotent` | Target already set — write-once enforced |
| `skip_condition_unmet` | Preconditions not all true |
| `no_op` | Trigger doesn't apply to this opportunity |

The `executed` column on every persisted decision is **always `False`** in shadow mode.

## Architecture

```
  GHL event (or replay)
      │
      ▼
  POST /webhook/ghl     (validates X-Webhook-Secret if configured)
      │
      ▼
  1. Save raw event              ─► events table
  2. Fetch opp from GHL API      ─► snapshots table   (read-only HTTP call)
  3. Run each handler            ─► decisions table   (executed=False)
  4. Return summary JSON
```

The GHL client (`ghl_client.py`) contains **only GET methods**. PUT/POST/PATCH are
not implemented. Even an accidental "write" call would fail at import time.

## Local development

### 1. Install

```bash
cd engine/service
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: paste your GHL_PIT (read-only is sufficient)
```

### 2. Run

```bash
uvicorn app:app --reload --port 8000
# health check: http://localhost:8000/healthz
# OpenAPI docs: http://localhost:8000/docs
```

### 3. Replay a captured payload (no GHL changes anywhere)

```bash
curl -X POST http://localhost:8000/webhook/replay \
  -H "Content-Type: application/json" \
  -d @test_payloads/opp_changed_materials_present.json | python -m json.tool
```

You'll see something like:

```json
{
  "event_id": 1,
  "opp_id": "REPLACE_WITH_REAL_OPP_ID",
  "decisions": [
    {
      "handler": "gate-materials-verified",
      "decision": "would_stamp",
      "target_field": "dt_materials_verified",
      "current_value": null,
      "target_value": "2026-06-12",
      "reason": "ev_materials_verified_photos is present and dt_materials_verified is empty — would set dt_materials_verified = 2026-06-12"
    },
    {
      "handler": "move-prod-p05-p10-install-scheduled",
      "decision": "skip_condition_unmet",
      "target_field": "pipelineStageId",
      "current_value": "c98f59ed-...",
      "target_value": null,
      "reason": "dt_install_scheduled is empty; cannot advance to P10"
    }
  ]
}
```

### 4. Inspect history

```bash
curl http://localhost:8000/events     | python -m json.tool
curl http://localhost:8000/decisions  | python -m json.tool
curl http://localhost:8000/events/1   | python -m json.tool
```

### 5. Tests

```bash
cd engine/service
python -m pytest tests/ -v
```

## Deploy to Render

The included `render.yaml` is an Infrastructure-as-Code blueprint. To deploy:

1. **Create a new Blueprint** in Render → New → Blueprint.
2. Connect this repo, point at `engine/service/render.yaml`.
3. Render reads the blueprint and provisions:
   - A web service (Docker, free tier)
   - A Postgres database (free tier, 90-day) — auto-wired via `DATABASE_URL`
4. **In the dashboard**, set the two secret env vars (these are intentionally NOT in the YAML):
   - `GHL_PIT` — your Private Integration Token
   - `WEBHOOK_SECRET` — a strong random string (use `openssl rand -hex 32`)
5. Deploy. The health check `/healthz` will turn green when ready.

The service URL will be something like `https://ghl-shadow.onrender.com`.

## What this service does NOT do

- ❌ Does not write to GHL (no PUT/POST/PATCH client methods exist)
- ❌ Does not modify any existing GHL workflow
- ❌ Does not require any GHL config changes to run (uses replay payloads)
- ❌ Does not require `cfg_use_python_engine` or any routing flag (yet)

## What this service WILL do later

When you're ready to put it on real events:

1. Read [GHL-SETUP-DEFERRED.md](./GHL-SETUP-DEFERRED.md) for the GHL-side wiring.
2. Add a single outbound webhook trigger in GHL (does not modify any existing workflow).
3. Continue running in shadow until you decide to enable writes.
4. Enabling writes is a *separate, future* PR that adds write methods to a new
   `ghl_writer.py` module — keeping the read-only client unchanged.

## Adding a new handler

1. Read the spec in `workflow/.../<id>.md`.
2. Create `engine/service/handlers/<spec_id>.py`. Follow the pattern in
   `gate_materials_verified.py`:
   - `HANDLER_ID = "<spec id>"`
   - `def evaluate(payload: dict) -> dict:` that returns a decision dict
3. Register it in `app.py`'s `HANDLERS` list.
4. Add unit tests in `tests/test_<spec_id>.py`.
5. (Optional) Add a representative payload in `test_payloads/`.

## File layout

```
engine/service/
├── app.py                  FastAPI app, event processing
├── config.py               Pydantic Settings (env vars)
├── db.py                   SQLAlchemy engine + session
├── models.py               Event, Snapshot, Decision tables
├── ghl_client.py           Read-only GHL API client
├── handlers/
│   ├── _common.py          payload-parsing helpers
│   ├── gate_materials_verified.py
│   └── move_prod_p05_p10.py
├── tests/                  unit tests
├── test_payloads/          sample payloads for /webhook/replay
├── Dockerfile              container for Render
├── render.yaml             IaC blueprint
├── requirements.txt
├── .env.example
├── README.md               this file
└── GHL-SETUP-DEFERRED.md   future GHL-side wiring (NOT yet done)
```
