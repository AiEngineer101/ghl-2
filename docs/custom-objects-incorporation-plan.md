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

## ⚠️ ARCHITECTURE FORK (discovered 07-02 — resolve before committing to a build)
The whole reader approach hinges on one unverified thing: **can our engine get from an Opportunity
to its associated Claim record via the GHL API?**
- ✅ **Reading a record by id is supported:** `GET /objects/:schemaKey/records/:id` (scope
  `objects/record.readonly`, path verified).
- ❌/❓ **Reading the opp→Claim *association* is UNVERIFIED.** The endpoint catalog only confirms
  `POST /associations/relations` (write/mirror, contact-based, object↔object unverified); a
  relations-*read* + a records-*search* endpoint are marked "exists — VERIFY path." The docs
  explicitly state **"Postgres owns the record-level relations"** and the engine "never reads it back"
  from GHL.

**Two possible worlds — the spike decides which:**
- **World A — GHL traversal works** (association-read or records-search by an opp/job property on the
  Claim). → Our current model (fetch opp per event → fetch its Claim) works; custom objects are a
  **reader add-on**. Small-ish.
- **World B — GHL traversal NOT reliably supported** (the doc's stated design). → The engine must own
  the **opp↔Claim linkage in its own store** (populated by ingestion / `capture-api`), i.e. the
  **§9 Postgres-graph architecture**. That is a **much larger lift** (a persistent relationship graph
  + ingestion feeding it) — NOT a small add-on, and it changes our infra (we're SQLite-shadow today).

**Implication:** "incorporate custom objects" may be a big architecture step, not a quick reader.
Do **not** commit an approach until the spike resolves the fork. This is the single most important
open question — bigger than the field-key/scope unknowns.

- `RecordCreate/RecordUpdate/RecordDelete` webhooks exist → child-record changes can trigger recompute (both worlds).
- ⚠️ Association/record scopes are flagged absent/VERIFY in `Scopes.md` — confirm on our PIT first.

## Party model (refined 07-02 — affects what we traverse)
Only **Adjuster** (Contact assoc "Adjuster on Claim") and **Carrier** (Company assoc) are real links to
read. **Insurance Agent + Mortgagee are plain reference fields on the policyholder Contact**
(`seg_insurance_agent_*`, `seg_mortgagee_name`, `seg_has_mortgagee`) — read them off the Contact, no
association traversal.

## STEP WE CAN DO NOW — the read spike (read-only, ungated) — RESOLVES THE FORK
A ~half-day read-only spike whose #1 job is to **decide World A vs World B**, and secondarily
capture scopes + live keys. Feeds Bill's Phase-1 contract.
1. `ghl_client` read methods (read-only): try, in order —
   (a) **association read** opp → related records (whatever the live path is);
   (b) **records search** for a Claim whose job/opp property == this opp id;
   (c) `GET /objects/:schemaKey/records/:id` on a known Claim id (baseline: proves record-read works).
2. A `/debug/opp-relations/{opp_id}` endpoint reporting: which of (a)/(b)/(c) succeeded, the scopes
   our PIT actually has, and the **live field keys** on the Claim (vs the doc).
3. Point it at a real Insurance opp **that has a Claim** in the build account.
**Deliverable / decision:** World A (traversal works → reader add-on) or World B (must build the
Postgres graph → escalate scope to Bill). Plus verified scopes + live keys for the Phase-1 contract.
This is the ONLY custom-objects build step that's safe before the contract exists — and it prevents
committing to the wrong architecture.

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
