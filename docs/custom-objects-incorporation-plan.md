# Custom Objects — Incorporation Plan (how our engine reads & rolls up the new objects)

> **Goal:** teach the service to read an Opportunity's associated custom-object records
> (Insurance Claim, Change Orders, Supplements) and feed the relocated values to our handlers —
> without breaking anything, following Bill's rollup pattern, and strictly gated on the LOCKED
> sequencing law. Source model: `_bill_docs/docs/ghl-native/custom-objects-data-model.md`.

## Gate before ANY build (do not skip)
- The custom-objects model is **DESIGN INPUT, not controlled doctrine** — build only after Bill
  promotes it to the SOT (Charter §11/§12).
- Objects + associations **are** built in the live SmartRoofing account (confirmed 2026-06-30),
  but per the **LOCKED sequencing law**: *define contract → build engine reader → verify in the
  build account → THEN retire legacy Opportunity fields.* Never assume an Opp field is gone.
- **Verify the association API scope string on our PIT** — flagged as absent from `Scopes.md`
  (`ghl-api-capability-map.md`). This is the #1 unknown; test it in Phase 1 before designing on it.

## What the API gives us (from `ghl-api-capability-map.md`)
- **Read** custom-object records (GET), and **read** an opp's links via
  `GET all-relations-by-record-id` → then GET each associated record. (Association *creation* via
  REST is contact-only — irrelevant; we only read.)
- **`RecordCreate/RecordUpdate/RecordDelete` webhooks exist** for custom objects → a child-record
  change can trigger our engine (today we only get `Opportunity Changed`).

## Design — a read + enrich/rollup layer (two modes)

**Read layer** (`ghl_client`, read-only, cached per event):
- `get_opp_relations(opp_id)` → associated record ids by label ("Job Claim", "Job Change Order", …)
- `get_custom_record(object_key, record_id)` → that record's fields

**Mode A — in-memory enrichment (identity/scope). RECOMMENDED for the read-side.**
After fetching the opp, fetch its **Job-Claim** record and inject its values into the opp's
`custom_field_map` **under the keys handlers already expect**, e.g.:
`Claim.claim_number → seg_insurance_claim_number`, `Claim.dt_insurance_scope_received →
dt_insurance_scope_received`, `Carrier association → seg_insurance_carrier_name`.
→ **Handlers stay unchanged**, read-only, fully reversible. A thin adapter, no writes.

**Mode B — rollup writes (money). Matches Bill's Track B.**
A new derived handler (`derived-revenue-rollup`) sums child amounts (Σ approved Supplements,
Σ billable Change Orders) + resolves payment/CO `dt_*`, and **writes** the Opportunity rollup gate
fields (`amt_contract_value`, `amt_total_funds_received`, `dt_ins_*_received`, change-order-resolved
truth). Closeout/readiness then read the Opp unchanged. Use the **standalone customFields PUT**
(combined-with-stage PUTs drop customFields — our 06-27 lesson; not an issue here since no stage move).

> Use **A** for identity/scope (claim #, carrier, scope date) and **B** for money that already
> lives as Opp gate fields. Don't duplicate the funding *truth* — roll it up once.

**Triggering (important):** a change to a *child* record won't fire an Opportunity webhook, so our
rollup wouldn't recompute. Fix with a **custom-object webhook bridge** (`RecordUpdate` → our
service) — mirrors the Opportunity bridge — plus the **reconciliation poll** (Bill §8.5) as backstop.

## Phased rollout (each phase reversible; retirement gated on the sequencing law)

| Phase | What | Risk |
|---|---|---|
| **0 — Prereqs** | Bill promotes doc to SOT; confirm objects/labels exist; **verify association API scope on the PIT** | none (research) |
| **1 — Read/inspect (shadow)** | `ghl_client` read methods + a `/debug` endpoint to dump an opp's Claim/CO/Supplement records. Prove we can read the graph. No behavior change. | none (read-only) |
| **2 — Enrich identity/scope (Mode A)** | Map Claim fields into the snapshot; confirm Insurance-path handlers see the SAME values from the Claim as from the (still-present) Opp fields, on a test opp with a claim | low (read-only; dual-source) |
| **3 — Money rollups (Mode B)** | Build `derived-revenue-rollup` (Supplements + COs → Opp gate fields); validate against manual values | med (writes) |
| **4 — Trigger on child changes** | Custom-object webhook bridge (`RecordUpdate`) + poll backstop | med |
| **5 — Retire legacy Opp fields (WITH Bill)** | Per field: reader verified → Bill drafts/removes the legacy Opp claim/CO/supplement field → flip handler to source solely from the new path | coordinated |
| **6 — End-state (§9 clean break)** | Claim-exists / production-readiness decided **in-engine from the Postgres graph** (`sys_production_readiness` becomes display-only, not a gate input) | larger arch |

## Affected handlers (what changes, and when)
| Handler | Reads today | Migrates to | Phase |
|---|---|---|---|
| `gate-insurance-scope` | `ev_insurance_scope_doc` / `dt_insurance_scope_received` on Opp | EV/DT on the **Claim** object | 2 / 5 |
| `derived-production-readiness` | `seg_insurance_claim_number`, `seg_insurance_carrier_name`, `dt_insurance_scope_received` | Claim `claim_number` / Carrier assoc / Claim scope DT; eventually claim-exists in-engine | 2 → 6 |
| `move-sales-s20-s30`, `s30-s40` (Insurance branch) | `dt_insurance_scope_received` | Claim scope DT (via Mode A) | 2 |
| `derived-closeout-ready` (+ change-order logic) | Opp change-order/supplement `dt_*`, `seg_change_order_treatment`, payer docs | **Change Order / Supplement** objects (Mode B rollup) | 3 |

## Guardrails
- **Dual-source during transition:** read the new source but keep the old Opp field as fallback
  (same tolerant pattern as the measurement-report dual-key fix) — never hard-cut a field before
  Phase 5 for it.
- **Rate limits:** +1–3 GETs/event for associated records; cache per event; fine at roofing volume.
- **Everything gated on Phase 0** — don't build against DESIGN INPUT before SOT promotion + scope
  verification.

## Suggested first step
Phase 1 only: add the read methods + a `/debug/opp-relations/{opp_id}` probe and confirm we can
actually pull an opp's Insurance Claim record (and that the PIT has the association scope). That
single test de-risks the whole plan — everything else depends on it.
