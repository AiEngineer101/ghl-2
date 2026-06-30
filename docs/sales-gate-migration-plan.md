# Sales Gate Migration Plan — move the input-stamping gates into code

> **Goal:** finish the Sales migration by moving the remaining *gates* (the EV/TF/D&C →
> `dt_*` stampers) from GHL into Python. Today the Sales **brain** (movers, readiness, drift
> enforcer, last-good) is fully code-owned; the **sensors** (most gates) are still GHL.
> End state: code owns every Sales gate it *can*, leaving only thin GHL forwarders for
> Documents & Contracts events (which have no native webhook). Matches Bill's blueprint
> (~94% native in code, D&C via thin-workflow) and the Production hybrid.

## Current state (2026-06-27)

**In code (active):** `gate-front-home-photo`, `gate-inspection-complete`, `gate-insurance-scope`
(`gate-inspection-complete`'s GHL twin is Drafted = sole owner; the other two still have their
GHL gate Published = harmless idempotent double-write).

**In code (SHADOW — built, awaiting validation + cutover):** Tier-1 Sales gates
`gate-pay-retail-deposit`, `gate-pay-ins-deductible`, `gate-pay-ins-acv`, `gate-measurement-report`
(all `SUPPORTS_WRITE=False`; registered before the movers; 4 tests each). Validate on `/decisions`
(would_stamp + key resolves) on a Sales test opp, then flip to `True` and Draft the matching GHL gate.

**Excluded from Sales (Production-scoped):** `gate-permit-approved` — Bill's spec says *In Pipeline:
Production Pipeline*, so it is NOT a Sales gate. (Seam to raise with Bill: `derived-production-readiness`
is a Sales handler that *reads* `dt_permit_approved`, but the stamping gate lives in Production. No
Sales-side change needed today — most Sales deals resolve permit via `seg_permit_required = No`.)

**Still GHL-only** — the D&C-sourced `dt_*` (Tier 3) plus any fallback-upload twins (Tier 2).

## The build pattern (every gate follows the existing 3)

Each EV→DT gate is the same shape as `handlers/gate_front_home_photo.py`:
1. New handler `handlers/gate_<name>.py` — `evaluate()` returns `would_stamp` when `ev_* present
   AND dt_* empty` (write-once), `skip_idempotent` if already set, `no_op` otherwise. Scope to
   the Sales pipeline. `execute()` → `stamp_custom_field(opp_data, decision, OUTPUT_FIELD)`.
2. Register in `app.py` HANDLERS (with the other Sales gates, before the movers).
3. Unit tests `tests/test_gate_<name>.py` (present/empty/idempotent/non-Sales).
4. **Per-gate cutover discipline** (same as everything so far): ship `SUPPORTS_WRITE=False`
   (shadow) → validate via replay/webhook on a test opp (`would_stamp` + key resolves) →
   flip to `True` → **Draft the matching GHL gate** (one owner per spec).
5. Standalone `customFields` PUT already used by `stamp_custom_field` — no combined-PUT issue.

> **Tags:** many GHL gates also flip `Has|/Milestone|/Missing|` tags (see webhook-event-contract
> §4a). Our movers/readiness key on `dt_*` dates, **not** tags, so tag-flipping is **optional /
> phase 2**. Decide per gate whether to replicate; if skipped, leave that gate's GHL workflow
> Published *or* accept tags go stale (low impact today).

---

## Tier 1 — Simple EV→DT Sales gates (LOW effort, do first)

Direct copies of the existing pattern. These feed S45/S46 + production-readiness, so they're the
highest-value.

| New handler | Input `ev_*` | Stamps `dt_*` | Feeds |
|---|---|---|---|
| `gate-pay-retail-deposit` | `ev_retail_deposit_proof` | `dt_retail_deposit_proof_received` | S45→S46, readiness (Retail/Hybrid) |
| `gate-pay-ins-deductible` | (ins deductible proof) | `dt_ins_deductible_received` | S45→S46, readiness (Ins/Hybrid) |
| `gate-pay-ins-acv` | (ACV proof) | `dt_ins_acv_received` | readiness (Ins/Hybrid) |
| `gate-permit-approved` | `ev_permit_approved_doc` | `dt_permit_approved` | readiness (permit branch) |
| `gate-measurement-report` | `ev_measurement_report` | **`_measurement_report_received_date`** (LIVE key, not the spec `dt_measurement_report_received` — corrected 2026-06-29 to match the field derived-readiness reads) | readiness (global) ⚠️ lowercase em-dash tag quirk (R9 §6.3) |

*Confirm each exact `ev_*` key against `_bill_docs/reference/field-registry.md` before coding.*

**Effort:** ~1 handler + test file each; a few hours total. No infra.

---

## Tier 2 — EV fallback-upload twins for the D&C dates (MED effort)

These let code own the **"doc uploaded manually"** path for the contract/estimate dates even
before a D&C bridge exists. They're EV→DT (Native), so buildable now.

| New handler | Stamps | Notes |
|---|---|---|
| `gate-estimate-presented-fallback-archive` | `dt_estimate_presented` | simple EV→DT |
| `gate-signed-contract-fallback-upload` | `dt_signed_contract_received` (+ backfill `dt_estimate_presented`, Retail-only) | small branch |
| `gate-insurance-contract-fallback-upload` | `dt_insurance_contract_signed` (+ Route B hybrid backfill: estimate/acceptance/job_type) | **complex — multi-field route, do last** |
| `gate-hybrid-upgrade-accepted-fallback-upload` | `dt_hybrid_upgrade_accepted` (+ backfill estimate, status=Accepted, job_type=Hybrid) | multi-field |

**Note:** the fallback only covers manual upload. The *primary* "Sent/Signed in D&C" path still
needs Tier 3. So Tier 2 reduces—but doesn't remove—the dependency on the GHL D&C gates.

---

## Tier 3 — D&C primary gates (needs a Documents & Contracts webhook bridge)

The 4 `dc-to-dt` gates fire on **Documents & Contracts events**, which have **no native GHL
webhook** — our service never sees them. This is the only part that genuinely cannot be
pure-code without new plumbing.

**Sub-project: D&C bridge**
1. **GHL side:** one thin workflow per D&C gate — trigger = Documents & Contracts (with the
   template/status/recipient filter, which *must* live in the GHL trigger) → Webhook action →
   our service. (4 workflows; mirrors the `Opportunity Changed Bridge`.)
2. **Service side:** an ingestion path for the D&C payload shape (different from OpportunityUpdate);
   resolve to the opp; run the D&C gate handler.
3. **Handlers:** `gate-estimate-presented-dc`, `gate-signed-contract-dc`,
   `gate-insurance-contract-dc`, `gate-hybrid-upgrade-accepted-dc`.

**Until Tier 3 is built, KEEP the 4 GHL D&C gates Published.** Even after, the *thin forwarder*
workflows stay in GHL (they're event plumbing, not logic — consistent with the doctrine).

---

## Not gates (handle separately)
- `seg_insurance_carrier_name`, `seg_insurance_claim_number` — manual/segment inputs (readiness
  reads them); no gate to build. Confirm they're captured upstream.
- `amt_contract_value` — set manually / by `sync-opportunity-value`; readiness reads it.

---

## Suggested sequence
1. **Tier 1** (5 EV gates) — quick wins; start with `pay-retail-deposit` + `pay-ins-deductible`
   (they directly feed the S45→S46 move you just validated).
2. **Tier 2** simple twins (`estimate-presented-fallback-archive`, `signed-contract-fallback-upload`).
3. **Tier 3** D&C bridge sub-project (scope + decide with Bill — it's the one infra piece).
4. **Tier 2 complex** (`insurance-contract` / `hybrid-upgrade` fallbacks) alongside/after Tier 3.

## Definition of done
Every Sales `dt_*` input is stamped by code; matching GHL gates Drafted; only the 4 D&C
thin-forwarder workflows remain in GHL (event plumbing). Sales is then ~fully in code, sensors
included — the same bar Bill's webhook-event-contract sets.

## Guardrails (lessons already learned — don't re-discover)
- **Verify field keys resolve** before trusting a write (re-add the `/debug/field-keys` probe if needed).
- **Standalone `customFields` PUT** for stamps (combined-with-stage PUTs drop customFields — but
  gates don't move stages, so they're fine).
- **One owner per spec:** flip Python active *and* Draft the GHL gate together; never both live
  (except the intentional idempotent overlap during validation).
- **Watch for double-driver workflows** (like the seed) via the GHL workflows API, not the UI.
