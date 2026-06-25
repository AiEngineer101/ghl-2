# Sales Pipeline — How It Works

> Generated diagrams of the code-driven Sales pipeline (Smart Roofing AI / ghl-2).
> Open in VSCode Markdown preview (with a Mermaid extension) or on GitHub to render.

---

## 1. Architecture — how one event flows

```mermaid
flowchart TD
    GHL["GHL Sales opportunity<br/>(something changed)"]
    GHL -->|"webhook<br/>POST /webhook/ghl"| REC

    subgraph SVC["Your service (app.py)"]
        REC["1. record raw event<br/>_record_event"]
        SNAP["2. GET full opp from GHL (read-only)<br/>enrich customFields with fieldKeys<br/>_maybe_snapshot"]
        RUN["3. run EVERY handler -> Decision<br/>gates first, then movers<br/>_run_handlers"]
        EXEC["4. if writes ON & decision is would_*<br/>call handler.execute()<br/>_maybe_execute"]
        REC --> SNAP --> RUN --> EXEC
    end

    EXEC -->|"PUT /opportunities/{id}<br/>(only if write-guard allows)"| GHL
    RUN --> DASH["Dashboard at /<br/>decision timeline"]

    classDef ghl fill:#fde68a,stroke:#b45309,color:#000;
    classDef svc fill:#bfdbfe,stroke:#1d4ed8,color:#000;
    class GHL,DASH ghl;
    class REC,SNAP,RUN,EXEC svc;
```

---

## 2. The write-safety guard (why live deals are never touched)

```mermaid
flowchart TD
    D["A mover decides: would_move"] --> Q1{"writes_enabled?"}
    Q1 -->|No| BLOCK["BLOCKED<br/>WriteNotAllowed"]
    Q1 -->|Yes| Q2{"opp's pipeline in<br/>pipeline-allowlist?<br/>(Production only)"}
    Q2 -->|Yes| WRITE["WRITE to GHL ✓"]
    Q2 -->|No| Q3{"opp_id in<br/>opp-allowlist?<br/>(test opps only)"}
    Q3 -->|Yes| WRITE
    Q3 -->|No| BLOCK

    classDef ok fill:#bbf7d0,stroke:#15803d,color:#000;
    classDef no fill:#fecaca,stroke:#b91c1c,color:#000;
    class WRITE ok;
    class BLOCK no;
```

*Result: a Production opp writes via the pipeline rule; a Sales **test** opp writes via the opp rule; every other live Sales deal only gets a logged "would move…" and is never PUT.*

---

## 3. The Sales pipeline state machine (proof gates + job-type forks)

```mermaid
flowchart TD
    S10["S10<br/>Inspection Booked"]
    S20["S20<br/>Inspection Complete"]
    S30["S30<br/>Scope Pending /<br/>Build Estimate"]
    S40["S40<br/>Job Pending Approval"]
    S45["S45<br/>Approved —<br/>Funding Pending"]
    S46["S46<br/>Initial Funding<br/>Received"]
    S50["S50<br/>Handoff To<br/>Production"]
    P05["Production / P05<br/>Ready for Materials"]

    S10 -->|"dt_inspection_completed<br/>AND dt_front_of_home<br/>..._photo_received"| S20

    S20 -->|"Retail: immediately"| S30
    S20 -->|"Insurance / Hybrid:<br/>dt_insurance_scope_received"| S30

    S30 -->|"Retail: dt_estimate_presented<br/>Insurance: dt_insurance_scope_received<br/>Hybrid: both"| S40

    S40 -->|"dt_signed_contract_received<br/>(no funding yet)"| S45
    S40 -.->|"dt_signed_contract_received<br/>+ funding already in<br/>(skip)"| S46

    S45 -->|"first funding:<br/>dt_retail_deposit_proof_received<br/>OR dt_ins_deductible_received"| S46

    S46 -->|"sys_production_readiness = Yes"| S50

    S50 ==>|"sys_production_readiness = Yes<br/>CROSS-PIPELINE:<br/>sets pipelineId + stageId"| P05

    classDef sales fill:#dbeafe,stroke:#1d4ed8,color:#000;
    classDef prod fill:#dcfce7,stroke:#15803d,color:#000;
    class S10,S20,S30,S40,S45,S46,S50 sales;
    class P05 prod;
```

---

## 4. Gate vs Mover (the two handler types)

```mermaid
flowchart LR
    subgraph GATE["GATE handler (ev_* / tf_* -> dt_*)"]
        G1["file uploaded / human says Yes"] --> G2["stamp a permanent date<br/>would_stamp<br/>(write-once)"]
    end
    subgraph MOVER["MOVER handler (stage -> stage)"]
        M1["durable date(s) present"] --> M2["advance the stage<br/>would_move"]
    end
    G2 -.->|"next event<br/>(one-event lag)"| M1

    classDef g fill:#fef9c3,stroke:#a16207,color:#000;
    classDef m fill:#e0e7ff,stroke:#4338ca,color:#000;
    class G1,G2 g;
    class M1,M2 m;
```

*A gate stamps the date on **this** event; the mover that depends on it fires on the **next** event. Movers key off durable date stamps, never raw file presence.*
