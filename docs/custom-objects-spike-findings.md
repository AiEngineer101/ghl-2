# Custom Objects — Read-Layer Spike Findings (Track B → feeds Bill's Phase-1 contract)

> **Purpose:** hand Bill the verified, live facts from the read spike so the SOP **Phase-1 engine
> contract** can be finalized ("Dhruv confirms buildable"). Everything here was probed **read-only**
> against the live SmartRoofing location (`8aQHgJUX2bFYBHZ4Qizg`) on **2026-07-02** via the
> `/debug/co-probe` endpoint. No writes were made.

## TL;DR — the architecture fork is resolved: **World A**
**Our engine CAN read an Opportunity's linked custom-object records directly from the GHL API.** So
custom-objects incorporation is a **reader add-on to the existing service**, *not* the larger
"engine owns the graph in Postgres" rebuild. Confirmed: `GET /associations/relations/{recordId}`
returns 200 with the opp's relations; each linked record is then fetched by id.

## Verified facts

### 1. PIT scopes work (read side)
| Probe | Endpoint | Result |
|---|---|---|
| List object schemas | `GET /objects/?locationId=` | **200** ✅ |
| List associations | `GET /associations/?locationId=` | **200** ✅ |
| Opp → relations | `GET /associations/relations/{oppId}?locationId=` | **200** ✅ |
| Record by id | `GET /objects/{schemaKey}/records/{id}?locationId=` | endpoint valid (pending a real record) |

*(No association/record READ scope error on our PIT — the `Scopes.md` gap flagged in
`ghl-api-capability-map.md` is not a blocker for reads.)*

### 2. Live custom-object schema keys (use these exact keys)
| Object | `schemaKey` | type |
|---|---|---|
| Insurance Claim | `custom_objects.insurance_claims` | USER_DEFINED |
| Supplement | `custom_objects.supplements` | USER_DEFINED |
| Change Order | `custom_objects.change_orders` | USER_DEFINED |
| Crew | `custom_objects.crews` | USER_DEFINED |

### 3. Live associations (with IDs) — the links exist and are readable
| Association key | Pair | Meaning |
|---|---|---|
| `job_insurance_claim` | opportunity ↔ insurance_claims | **the opp→Claim link** |
| `carrier_insurance_claims` | business ↔ insurance_claims | Carrier = Company |
| `policy_holder_insurance_claims` | contact ↔ insurance_claims | Policyholder |
| `adjuster_adjusted_claims` | contact ↔ insurance_claims | Adjuster |
| `supplements_claim` | insurance_claims ↔ supplements | Supplement→Claim |
| `supplements_job` | supplements ↔ opportunity | Supplement→Job |
| `change_orders_job` | change_orders ↔ opportunity | Change Order→Job |
| `change_orders_signer` | contact ↔ change_orders | CO signer |
| `assigned_crew_job`, `crews_employer`, `crews_crew_lead` | crews ↔ opp/business/contact | crew links |

Relation shape (each is an undirected pair): `{firstObjectKey, firstRecordId, secondObjectKey,
secondRecordId, associationId, ...}`. Our parser handles the target being on either side.

### 4. Read layer built against these facts (shipped, read-only)
- `ghl_client.get_record_relations(opp_id)`, `ghl_client.get_object_record(schema_key, id)`
- `custom_objects.py` (pure, unit-tested): schema/assoc keys + `related_record_ids()` + `record_fields()`
- `custom_object_reader.py`: `get_claim_for_opp()`, `get_change_orders_for_opp()`, `get_supplements_for_opp()`
- 9 unit tests; 240 total green.

## Still unverified (needs Bill / a real record)
1. **No Claim record exists yet** in the build account, so the **live record field shape + exact
   field keys are unconfirmed.** `record_fields()` is written tolerantly; it must be re-checked
   against a real Claim (measurement-report precedent: live keys have differed from spec before).
   → *Ask: create one Insurance Claim on a test opp (linked via `job_insurance_claim`) so we can
   lock the record shape + keys.*
2. **Relations pagination** — probed opp returned `total: 1`; behavior at many relations (limit/skip)
   not exercised.
3. **Write path** (create/update records) — out of scope for the reader; that's ingestion
   (`engine/capture-api/`).

## What we need from Bill to build the readers/movers (SOP Phase 1 + open decisions)
The read *mechanics* are proven; the **business contract** is what's missing. Blocking decisions
(from `clean-break-SOP.md`):
1. **Claim-contacts gate** — canonical completeness condition (`sys_claim_contacts_captured`?) + enforcement point.
2. **S30→S40 de-branch** — is the live mover uniform yet, or still retail-only?
3. **Carrier-scope entry guard** — exists or to be built?
4. **Per-mover read contract** — for each Insurance-path mover, *which* object field(s) it reads to
   decide the move (§9 currently covers identifiers/contacts; extend to all claim facts).

## Recommendation / next actions
- **Bill:** finalize the Phase-0 field-map + Phase-1 per-mover read contract and the 4 decisions above.
- **Us (unblocked now):** shadow claim-observer (log an opp's linked records per event) + shadow
  revenue-rollup (compute-only) — both log-only, no writes, safe against a design-input model.
- **Both, once a Claim exists:** live-validate the read layer → lock the record field keys.
- Remove `/debug/co-probe` after the record-shape validation (spike endpoint).
