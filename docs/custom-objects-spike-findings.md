# Custom Objects — Read Spike: Facts + Asks (2026-07-02)

Read-only probe of the live location (`8aQHgJUX2bFYBHZ4Qizg`). No writes.

## Result: the engine CAN read the graph via the GHL API (World A)
`GET /associations/relations/{oppId}` → 200; linked records fetched by id. So this is a **reader
add-on to the existing service, not a Postgres-graph rebuild.** PIT read scopes work (objects +
associations both 200).

## Verified live facts
- **Schema keys:** `custom_objects.insurance_claims` · `custom_objects.supplements` ·
  `custom_objects.change_orders` · `custom_objects.crews`
- **Key association:** `job_insurance_claim` (opportunity ↔ insurance_claims); also
  `carrier_insurance_claims`, `policy_holder_insurance_claims`, `adjuster_adjusted_claims`,
  `supplements_job`, `change_orders_job`.
- **Shipped (read-only):** client read methods + `custom_objects.py` parser + `custom_object_reader.py`
  (`get_claim_for_opp`, …), 9 unit tests.

## Still unverified
- **No Claim record exists yet** → live field keys/record shape unconfirmed (code is tolerant; must
  re-check against a real Claim — live keys have differed from spec before).

## Asks (to unblock the reader/mover build — SOP Phase 1)
1. Create **one Insurance Claim on a test opp** (linked via `job_insurance_claim`) so we can lock the record shape + field keys.
2. **Claim-contacts gate** — completeness condition + where enforced?
3. **S30→S40** — de-branched (uniform) yet, or still retail-only?
4. **Carrier-scope entry guard** — exists or to build?
5. **Per-mover read contract** — for each Insurance-path mover, which object field(s) decide the move.

Mechanics are proven; #2–#5 are the business contract we need before wiring readers into movers.
