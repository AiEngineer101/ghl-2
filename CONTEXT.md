# Smart Roofing AI — Project Context

> **Purpose of this file:** the single place that captures *what we are building, why, where things live, the current state, and what's next* — so context is never lost between sessions or people. Update it whenever something material changes.
>
> **Last updated:** 2026-06-24

---

## 1. What this project is

Smart Roofing AI is an all-in-one CRM **operating system** for roofing companies, built on top of GoHighLevel (GHL). Its defining idea: it's a **system of action**, not just a system of record — it tells you *what should happen next* and moves jobs automatically based on proof, instead of people dragging cards around.

**Core principle — jobs move only on proof.** A job advances a pipeline stage only when the evidence proves the new state is true. Three proof types (the "gates"):

| Type | Code | What it is | Example |
|------|------|-----------|---------|
| **Evidence** | `ev_*` → stamps `dt_*` | A file/photo is uploaded | Completion photos uploaded |
| **Truth** | `tf_*` | A human confirms "Yes" | "Work Completed = Yes" |
| **Date stamp** | `dt_*` | Auto-recorded date when something became true | `dt_work_completed = 2026-06-21` |
| **Derived** | `sys_*` | A value the system computes from the above | `sys_closeout_ready = Yes` |
| **Segment** | `seg_*` | A category/branch selector | `seg_permit_required = Yes` |

"Drift integrity" logic catches manual moves / missing evidence and walks the job back to the stage its evidence actually supports.

**Pipelines:** Leads → Sales → Production → Warranty.

**The big migration:** move all workflow logic *out of GHL's drag-and-drop workflows and into Python code*. GHL stays the data + UI layer; Python (this repo) is the brain. GHL emits one generic "Opportunity Changed" webhook → our service figures out what changed and acts.

---

## 2. Where everything lives (IMPORTANT — two different repos)

- **LIVE code repo:** `AiEngineer101/ghl-2`, branch **`main`**. This repo (code only — `app.py`, `handlers/`, etc. at the root). Auto-deploys to Render on every push to `main`.
  - Live service URL: **https://ghl-shadow.onrender.com** (the Render *service* is named "ghl-shadow"; the empty repo `AiEngineer101/ghl-shadow` is NOT used).
  - Local clone: `C:\Users\Dhruv\ghl-2`.
  - This repo is isolated under the `AiEngineer101` account on purpose, to keep the Render/GHL keys away from the client.
- **DOCS / context repo (read-only to us):** `dbsmartroof/smartroofing`. The original repo, branches `main` / `dhruv` / `Bill-Kimberlin`. We were given a **zip snapshot** at `C:\Users\Dhruv\Desktop\smartroofing_repo_2026-06-21.zip`.
  - The `Bill-Kimberlin-branch (docs)` folder is the **up-to-date spec/documentation** — our source of truth for *what to build*. **Never edit it.**
  - The zip's `dhruv` / `main` branches are stale — ignore for live work.
- **Meeting transcripts:** `C:\Users\Dhruv\Downloads\smart_roofing_meeting_notes (1).md` (7 meetings, 2026-06-01 → 06-19).

**Roles:** Greg/Bill (client; Bill owns the documentation), Steve (business). Dhruv (developer; `adityachauhan@aisolv.io`).

---

## 3. How the live engine works

```
GHL event (Opportunity Changed)  ──webhook──▶  POST /webhook/ghl
        │                                            │
        │   (a "| Py" bridge workflow in GHL          ▼
        │    forwards Production events)        1. save raw event
        │                                       2. fetch full opp from GHL (read-only GET)
        │                                       3. run every handler → record a Decision
        │                                       4. if writes ON & decision is would_* → PUT back to GHL
        ▼                                       5. return summary
   dashboard at /  shows the decision timeline
```

- **Shadow-state diff:** GHL only says "something changed," not *what*. The service compares against stored state to find the change and stay idempotent (no echo loops).
- **Shadow vs active:** each handler has `SUPPORTS_WRITE`. `False` = watch-only (logs "would do X" but doesn't touch GHL). `True` = active (actually writes). New handlers are added shadow-first, validated on the dashboard, then "cut over" to active **at the same time as** the matching GHL workflow is set to Draft (so they don't double-drive).
- **Write safety (defense in depth):** writes only happen if `WRITES_ENABLED=true` AND the opp's pipeline is in the allowlist (currently **Production only**, `88V9uYY6visCrtI9V0NR`).
- **Decision types:** `would_move`, `would_stamp`, `would_rewind`, `skip_idempotent`, `skip_condition_unmet`, `skip_blocked`, `no_op`.

**Useful read-only endpoints (open GET, no secret):** `/healthz`, `/events?limit=N`, `/events/{id}`, `/decisions?limit=N`, `/` (dashboard).
**Secrets (in Render env, NOT shared with us):** `GHL_PIT` (GHL Private Integration Token), `WEBHOOK_SECRET`.

---

## 4. Current state of the build (2026-06-21)

**Production pipeline is now FULLY in code and live (active writes).** 11 handlers registered, all active:

| Handler | Role | Stage / field |
|---|---|---|
| `gate-materials-verified` | gate (EV→DT) | stamps `dt_materials_verified` |
| `gate-work-started` | gate (TF→DT) | stamps `dt_work_started` |
| `gate-work-completed` | gate (TF→DT) | stamps `dt_work_completed` |
| `derived-closeout-cash-reconciled` | derived | sets `sys_closeout_cash_reconciled` |
| `derived-closeout-ready` | derived | sets `sys_closeout_ready` (the P50 gate) |
| `move-prod-p05-p10-install-scheduled` | mover | Ready for Materials → Production Scheduled |
| `move-prod-p10-p20-work-started` | mover | Production Scheduled → Job In Progress |
| `move-prod-p20-p30-work-completed` | mover | Job In Progress → Job Completed |
| `move-prod-p30-p40-closeout-pending` | mover | Job Completed → Closeout Pending |
| `move-prod-p40-p50-closeout-complete` | mover | Closeout Pending → Closeout Complete |
| `enforce-stage-truth-invariant` | enforcer | rewinds drifted stages (P05–P30 only) |

**Cut over to active today (2026-06-21):** the four closeout handlers (`p30-p40`, `p40-p50`, `closeout-cash-reconciled`, `closeout-ready`). Their matching GHL workflows were set to **Draft** by the client: *Move Prod P30→P40*, *Move Prod P40→P50*, *Derived Closeout Ready* (+ a "Needs Review Dup"), *Derived Closeout Cash Reconciled*. (The earlier P05–P30 set was cut over before this session; `WF | Gate | MaterialsVerified` is Draft, `…| Py` is the published webhook bridge.)

**Verified live today (end-to-end on test job "Dhruv Singh"):**
- ✅ Full climb Ready for Materials → Closeout Complete, driven by proof, no manual dragging.
- ✅ At Closeout Pending it correctly **refuses to close** while any proof is missing.
- ✅ It only closed once all 3 docs + full payment were present.
- ✅ Drift: clearing work flags rewound the job to the correct earlier stage.
- ✅ "Closed stays closed" — the system never auto-reopens a Closeout Complete job.

**Bug fixed today:** `derived-closeout-cash-reconciled` used to *skip* (no write) when an amount was blank, leaving a stale `Yes`. Now a missing/blank payment counts as $0 → `No`. (Requires a contract value to be present; if not, it still skips to avoid spurious writes.)

**Test coverage:** 88 unit tests, all passing (`python -m pytest tests/`).

---

## 5. The closeout logic (P40 → P50), in detail

`sys_closeout_ready = Yes` only when ALL of:
1. `dt_completion_photos_received` present
2. `dt_coc_received` present
3. `dt_final_walkthrough_proof_received` present
4. `sys_closeout_cash_reconciled = Yes`  (= `amt_total_funds_received >= amt_contract_value`)
5. permit OK: `seg_permit_required != Yes` OR `dt_permit_approved` present
6. change-order resolved: no CO initiated, OR the chosen payer path is fully documented
   (crew chargeback / company-vendor / billable customer — each needs its own doc(s))

When `sys_closeout_ready` flips to Yes, `move-prod-p40-p50` moves the job to Closeout Complete.

---

## 6. KEY GOTCHA — files vs. date stamps (caused real confusion during testing)

**Uploading a file and the "received date" stamp are two different things.**
- When a file is uploaded, the EV→DT gate stamps a date like `dt_completion_photos_received` and that date is **write-once / permanent**.
- **Deleting the uploaded file does NOT clear the date stamp.** The closeout logic reads the **date stamp**, not whether a file is attached.
- The three closeout date stamps live in the opportunity's **"System – Derived (Do Not Edit)"** section (field-registry folder "System / Automation"), with UI labels:
  - 🗓️ Completion Photos Received Date
  - 🗓️ COC Received Date
  - 🗓️ Final Walkthrough Proof Date

**To truly reset a job for testing:** clear those date fields (in the System – Derived section) AND blank/lower the payment, then move the Stage back manually. Removing files alone does nothing. That section is "Do Not Edit" in normal operation, but clearing it manually is fine for a test reset.

---

## 7. Reference data

**Location ID:** `8aQHgJUX2bFYBHZ4Qizg`

**Pipelines:**
| Pipeline | ID |
|---|---|
| Leads | `9VqvEN51waGkTKuVSAmn` |
| Sales | `9KlQhUS34GzTN9q34WKF` |
| Production | `88V9uYY6visCrtI9V0NR` |
| Warranty | `gAYzyAUrhsmthp8mNtUk` |

**Production stages (legacy code → name → GHL stage ID):**
| Code | Name | Stage ID | Entry proof |
|---|---|---|---|
| P05 | Ready for Materials | `c98f59ed-7b38-4dd6-ae64-01c5a6537894` | (base) |
| P10 | Production Scheduled | `7a4f2d75-f033-4971-8eed-8ca4285e639e` | `dt_install_scheduled` |
| P20 | Job In Progress | `ebef66b1-a570-412c-93b3-1be988d6a33f` | `tf_work_started=Yes` |
| P30 | Job Completed | `96f19b6d-4d85-4e66-910f-4a4f071bf9c0` | `tf_work_completed=Yes` |
| P40 | Closeout Pending | `bb84bafb-5266-4063-b1f6-bc1ef21a0790` | (auto from P30) |
| P50 | Closeout Complete | `de0bc542-b6a0-4885-b991-18ed02b19fe7` | `sys_closeout_ready=Yes` |

**To climb Production by hand (test cheat sheet):** set 🗓️ Install Scheduled → Work Started=Yes → Work Completed=Yes → (auto to Closeout Pending) → upload 3 docs + set funds ≥ contract → Closeout Complete.

---

## 8. Open questions / known gaps

1. **Should an invalid Closeout Complete bounce back?** — **ANSWERED by Bill (06-23).** Yes: `closeout-complete.md` §5 specs a **readiness guardrail** — if a job reaches Closeout Complete while `sys_closeout_ready` ≠ Yes, the Code OS bounces it back to Closeout Pending and surfaces the missing item. **Not yet built in our code** (see §11 / §9). Note: this is about *invalid* entries, not auto-reopening a legitimately-closed job.
2. **"Photos at their own step?"** — **ANSWERED by Bill.** `job-completed.md` confirms completion photos / COC / final walkthrough are **context-only** at Job Completed and **enforced at Closeout Pending** (intentional). Job Completed just auto-advances. Our build matches.
3. **Document content validation** (is the file genuine?) — still **deferred** to a future AI/OCR feature; human confirmation is today's validator.

---

## 9. Next steps

1. **Production:** done + verified. Remaining polish: decide on the open questions above (esp. closed-reopen and enforcer extension).
2. **Sales pipeline:** the next build target. ⚠️ **Do NOT touch live Sales** — it's live with no test harness. Need a safe test setup first. The newest Sales→Production handoff + NEXT-tag specs are in the Bill-Kimberlin docs.
3. **Leads** and **Warranty** pipelines: not started.
4. **Document intake** (SMS / email / upload auto-routed to the right job): the strategic moat. Build after the core pipelines are stable.
5. **AccuLynx adapter:** first external-CRM integration (adapter-layer pattern; core logic unchanged, thin per-CRM adapter).

---

## 10. Operational notes (this dev machine)

- **TLS-inspecting proxy:** `git`, `curl`, and `pip` need the Windows CA bundle at `C:\Users\Dhruv\windows_ca_bundle.pem`.
  - git: `git -c http.sslCAInfo=C:/Users/Dhruv/windows_ca_bundle.pem …`
  - curl: `curl --cacert C:/Users/Dhruv/windows_ca_bundle.pem …`
  - pip: `pip install --cert C:/Users/Dhruv/windows_ca_bundle.pem …`
- **Deploy:** push to `main` → Render auto-deploys (~1–2 min). The `/healthz` handler list is a quick sanity check.
- **Auth:** GitHub access is via a per-session PAT on the `AiEngineer101` account (not stored in-repo). We do **not** have the GHL key, so we cannot write to GHL directly from a dev machine — only the deployed service can (via its `GHL_PIT`).
- **Checking what happened to a job:** query `/decisions?limit=N` or `/events/{id}` against the live URL — every handler decision is logged with an `executed` flag.

---

## 11. June 24 sync — Bill's docs update (snapshot `smartroofing_repo_2026-06-24.zip`, commit 99787f1, 2026-06-23)

**What changed in Bill's docs and how it affects us:**

- **CR-0026 — final stage renamed `Closed Won` → `Closeout Complete`.** Stage ID **unchanged** (`de0bc542…`), so our handlers (which key on the ID) are functionally unaffected. We updated the **display labels** in our code + this doc to match. ⚠️ Bill still needs to rename the **live GHL stage display** (it currently still reads "Closed Won"); Stage ID is the binding identifier in the interim.
- **CR-0024 — final-walkthrough field key confirmed** as `ev_final_walkthrough_proof` / `dt_final_walkthrough_proof_received`. **Our code already uses the correct key.** ✅
- **CR-0025 — COC required for ALL job types** (was mis-tagged Insurance/Hybrid-only). Mechanic unchanged (`dt_coc_received` not empty). **Our code already requires it for all.** ✅ (COC evidence field is `ev_coc_document`.)
- **CR-0022 — invented stage codes (P05/S10/PL_*) deprecated**; names + GHL IDs are canonical. We already resolve by Stage ID. ✅ (Note: our movers still *write* `sys_last_good_stage_code = P50` etc. — that's the legacy last-good tracking per the move spec's `fields_written`, not stage identity.)
- **CR-0027 — code-first build doctrine LOCKED** into the Charter (Musk Algorithm: question → delete → simplify → accelerate → automate-last; build in code, not the platform, by default). Reinforces our approach.
- **The closeout Layer-1 stage docs now EXIST** (`job-completed.md`, `closeout-pending.md`, `closeout-complete.md`) — the gap we flagged. **Verified: our closeout logic matches** the written Definition of Done (photos + COC + final walkthrough + permit-if-required + cash reconciled).
- **New (Sales):** Layer-1 docs for `inspection-booked` + `inspection-complete` — for when we build Sales.
- **New area:** a **work-order control layer** (`docs/code-project/work-order/`, `docs/ghl-native/work-order-control-layer.md`) — not yet reviewed for code impact.

**NEW build items this update surfaced (NOT yet in our code):**

1. **Closeout Complete readiness guardrail** (`closeout-complete.md` §5, Edge 7) — if a job reaches Closeout Complete while `sys_closeout_ready` ≠ Yes (e.g. manual/owner drag, or proof later breaks), bounce it back to Closeout Pending and surface the specific missing item. This is the spec'd answer to "should an invalid close bounce back?" Buildable now (extends the enforcer to P50). **Behavior change to the live writer — confirm before building.**
2. **Revenue Adjustments Subsystem** (Change Orders + Supplements) — `closeout-pending.md` §2 conditions 6 & 7 want derived rollups `sys_change_orders_resolved` / `sys_supplements_resolved` (both `[NEW FIELD — to be created]`). Each repeats up to 8×/job (~25% of revenue) and needs **repeating child records**, not opportunity-level single-stamp fields. **Future build** (see Bill's `backlog.md`). Our current code uses the interim CR-0003 change-order logic and does **not** handle Supplements yet.
