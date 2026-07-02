# Custom Objects — Incorporation Plan (Track B / engine reader side)

> **Goal:** teach our engine to read the new GHL custom objects (Insurance Claim, Change Orders,
> Supplements) and drive the Insurance/closeout logic off them instead of Opportunity fields —
> per Bill's clean-break migration. **Reconciled 2026-07-02** to Bill's authoritative runbook
> `_bill_docs/docs/code-project/migration/clean-break-SOP.md` and the custom-objects data model.

## How this plan sits under Bill's SOP (READ FIRST)
Bill's SOP splits the work into **Track A (Bill + doc-agent)** and **Track B (us / Dhruv = engine)**:

| SOP Phase | Owner | Our involvement |
|---|---|---|
| 0 — Freeze & inventory (legacy field → new home map) | Track A | consume the map |
| 1 — Define the **engine contract** (what the engine reads off which object per mover) | Track A authors, **Dhruv confirms buildable** | **our input required** |
| 2 — Re-point Layer-1 / registry / tags to the model | Track A | consume |
| 3 — Controlled-source CR reconciliation | Track A | — |
| **4 — Engine build** (ingestion + readers/movers via GHL API) | **Track B = us** | **our core work** |
| **5 — Cutover & retire** legacy Opp fields | Track B + A | our work + Bill sign-off |
| **6 — Verify & sign-off** (Retail/Ins/Hybrid × every stage) | both | our work |

**Hard gate:** SOP Phase 4 (our build) is **gated on Phases 0–1** — we do not build readers/movers
until the field-map + engine contract exist and Bill approves them. **What we CAN do now** is the
**read spike** (below): it's read-only, de-risks the API, discovers live keys, and *feeds* Bill's
Phase-1 contract ("Dhruv confirms buildable"). Everything past the spike waits on the contract.

## Clean-break principles that reshape the original plan
- **No dual-path / no permanent Opportunity mirror for claim data.** The engine reads the **object**
  and drives moves via the GHL API; the legacy Opportunity claim fields **retire**. My earlier
  "Mode B: write rollups back onto the Opportunity" is **NOT** the end state for *claim identity/scope*
  — those retire. Money aggregates that are genuinely Opportunity-level (`amt_contract_value`,
  `amt_total_funds_received`) may stay as **engine-written rollups on the Opportunity** (the spine
  still holds job money); claim-specific capture (claim #, carrier, scope, per-record supplement/CO
  data) moves to the objects and retires from the Opportunity.
- **No live customers → atomic cutover.** Everything is built + tested in the **build account**, then
  the account is **cloned**. So there's no long dual-running window; the "dual-source read-fallback"
  is only a *test convenience during the build*, not a shipped behavior.
- **Sequencing law (LOCKED):** never retire an Opportunity field before its engine reader is live
  AND verified in the build account.

## What our engine READS vs what it WRITES (boundary)
- **Reads (our movers/readiness/closeout):** Insurance Claim record (claim #, carrier assoc, scope
  DT, ACV/deductible), Change Order records, Supplement records — via the associations from the opp.
- **Writes the object records = INGESTION (`engine/capture-api/`, separate component).** Doc-intake
  / manual entry creates the Claim/Supplement/CO records. Our reader engine should NOT own record
  creation — draw the line at "we read the graph + drive moves; capture-api writes the graph."
- **Money rollups:** a `derived-revenue-rollup` handler (ours) may sum child amounts → write the
  Opportunity `amt_*` rollups (the one place we still write UP to the Opportunity). Standalone
  customFields PUT (combined-with-stage PUTs drop customFields — 06-27 lesson).

## API reality (from `ghl-api-capability-map.md`, verify in the spike)
- Read: `GET all-relations-by-record-id` (opp → associated Claim/CO/Supplement ids) → record GETs. ✅ documented
- `RecordCreate/RecordUpdate/RecordDelete` webhooks exist → child-record changes can trigger recompute.
- ⚠️ **Association API scope is NOT in `Scopes.md`** — the #1 thing the spike must confirm on our PIT.
- Association *creation* via REST is contact-only (irrelevant — we only read).

## Party model (refined 07-02 — affects what we traverse)
Only **Adjuster** (Contact assoc "Adjuster on Claim") and **Carrier** (Company assoc) are real links to
read. **Insurance Agent + Mortgagee are plain reference fields on the policyholder Contact**
(`seg_insurance_agent_*`, `seg_mortgagee_name`, `seg_has_mortgagee`) — read them off the Contact, no
association traversal.

## STEP WE CAN DO NOW — the read spike (read-only, ungated)
A ~half-day spike that turns the biggest unknowns into facts and feeds Bill's Phase-1 contract:
1. `ghl_client` read methods: `get_opp_relations(opp_id)`, `get_custom_record(object_key, id)` (read-only).
2. A `/debug/opp-relations/{opp_id}` endpoint dumping an opp's associated Claim/CO/Supplement records + their live field keys.
3. Point it at a real Insurance opp that has a Claim in the build account. Capture: does our **PIT have the association scope**? what are the **live field keys** (vs the doc)? what's the relation/record JSON shape?
**Deliverable:** a short findings note → hands Bill's Phase-1 contract concrete, verified facts.
This is the ONLY custom-objects build step that's safe before the contract exists.

## After the contract (SOP Phase 4+, our core work — gated)
| Step | What | Depends on |
|---|---|---|
| Reader layer | fetch + normalize Claim/CO/Supplement per opp event (cache per event) | spike |
| Enrich Insurance-path handlers | movers/readiness/scope-gate read claim data from the object (via enrichment adapter), Opp fields retired | Phase-1 contract; open decisions below |
| `derived-revenue-rollup` | Σ Supplements/COs → Opp `amt_*` rollups | contract |
| Child-record trigger | custom-object `RecordUpdate` webhook bridge + reconciliation poll backstop | contract |
| Cutover + retire | build-account verify → Bill drafts legacy Opp fields → clone | Phases 4 green |

## Blocking open decisions (owed by Bill, per SOP)
These gate the Insurance-path mover rebuild — flag them, don't guess:
1. **Claim-contacts gate** — canonical completeness condition (`sys_claim_contacts_captured`?) + where enforced.
2. **S30→S40 de-branch** — is the live mover uniform yet or still retail-only?
3. **Carrier-scope entry guard** — exists or to be built?
4. **Sales draft docs** — fold into Phase 2 (recommended) vs regenerate.

## Guardrails
- Gate everything past the spike on Bill's Phase 0–1 contract + the 4 open decisions.
- Verify live field keys in the spike before coding (measurement-report precedent).
- Rate limits: +1–3 GETs/event for associated records; cache per event.
- Read-side spike is safe now; writes/retirement are build-account-first, Bill-gated.

## Suggested first step
**Build the read spike.** It's read-only, unblocks the biggest unknowns (scope + live keys), and is
exactly the "Dhruv confirms buildable" input Bill's SOP Phase 1 asks for. Do not build readers/movers
against the objects until the contract + open decisions land.
