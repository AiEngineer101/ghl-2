"""Handler for WF | Derived | Production Readiness (Sales).

Spec source: docs/code-project/pipelines/sales/handoff-to-production.md §6

Computes sys_production_readiness (Yes/No) — the derived rollup that authorizes the
Sales -> Production handoff. The S46->S50 mover and the S50->Production cross both gate on
this field; until now our code only READ it (the live GHL derived workflow computed it —
the "DERIVED GAP"). This handler computes it ourselves so Sales can be fully migrated.

sys_production_readiness = Yes requires ALL prerequisites for the job type (§6):
  - Global (all):     dt_measurement_report_received, amt_contract_value,
                      (seg_permit_required = No OR dt_permit_approved)
  - Retail (adds):    dt_estimate_presented, dt_signed_contract_received,
                      dt_retail_deposit_proof_received
  - Insurance (adds): dt_insurance_scope_received, dt_insurance_contract_signed,
                      dt_ins_acv_received, dt_ins_deductible_received,
                      seg_insurance_carrier_name, seg_insurance_claim_number
  - Hybrid (adds):    dt_insurance_scope_received, dt_estimate_presented,
                      dt_insurance_contract_signed, dt_hybrid_upgrade_accepted,
                      dt_ins_acv_received, dt_retail_deposit_proof_received,
                      dt_ins_deductible_received, seg_insurance_carrier_name,
                      seg_insurance_claim_number

Permit is stricter than closeout's: readiness requires seg_permit_required to be
ANSWERED — `No` (not required) OR an approval date. An UNSET permit question is "blocked —
permit requirement unset" (§1), i.e. NOT ready.

Scoped to the Sales pipeline (readiness drives the handoff out of Sales). Once the job
crosses into Production, the Production-side Block-Production-Entry guard re-verifies it.

Idempotent: only emits a write when the computed value differs from the stored value.

ACTIVE — opp-scoped (writer enforces the per-opp/pipeline allowlist). When cut over for real
deals, the live GHL production-readiness workflow must be set to Draft so they don't
double-drive.
"""
from __future__ import annotations

from typing import Any

from handlers._common import custom_field_map, truthy, unwrap_opportunity

HANDLER_ID = "derived-production-readiness"
SUPPORTS_WRITE = True  # active, writer enforces the per-opp/pipeline allowlist

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
OUTPUT_FIELD = "sys_production_readiness"

JOB_TYPE_FIELD = "seg_job_type"
JOB_TYPE_RETAIL = "retail"
JOB_TYPE_INSURANCE = "insurance"
JOB_TYPE_HYBRID = "hybrid"

# (field_key, human label) prerequisite sets.
GLOBAL_DTS = [
    ("dt_measurement_report_received", "measurement report"),
    ("amt_contract_value", "contract value"),
]
RETAIL_ADDS = [
    ("dt_estimate_presented", "estimate presented"),
    ("dt_signed_contract_received", "signed contract"),
    ("dt_retail_deposit_proof_received", "retail deposit"),
]
INSURANCE_ADDS = [
    ("dt_insurance_scope_received", "insurance scope"),
    ("dt_insurance_contract_signed", "insurance contract signed"),
    ("dt_ins_acv_received", "ACV received"),
    ("dt_ins_deductible_received", "deductible received"),
    ("seg_insurance_carrier_name", "insurance carrier name"),
    ("seg_insurance_claim_number", "insurance claim number"),
]
HYBRID_ADDS = [
    ("dt_insurance_scope_received", "insurance scope"),
    ("dt_estimate_presented", "estimate presented"),
    ("dt_insurance_contract_signed", "insurance contract signed"),
    ("dt_hybrid_upgrade_accepted", "hybrid upgrade accepted"),
    ("dt_ins_acv_received", "ACV received"),
    ("dt_retail_deposit_proof_received", "retail deposit"),
    ("dt_ins_deductible_received", "deductible received"),
    ("seg_insurance_carrier_name", "insurance carrier name"),
    ("seg_insurance_claim_number", "insurance claim number"),
]

_ADDS_BY_TYPE = {
    JOB_TYPE_RETAIL: RETAIL_ADDS,
    JOB_TYPE_INSURANCE: INSURANCE_ADDS,
    JOB_TYPE_HYBRID: HYBRID_ADDS,
}


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _job_type(value: Any) -> str:
    value = _scalar(value)
    if value is None:
        return ""
    return str(value).strip().lower()


def _permit_ok(custom: dict[str, Any]) -> bool:
    """Permit gate: an explicit 'No' (not required) OR an approval date.

    An UNSET permit question is NOT ok ('blocked — permit requirement unset', §1).
    """
    if truthy(custom.get("dt_permit_approved")):
        return True
    req = _scalar(custom.get("seg_permit_required"))
    return req is not None and str(req).strip().lower() == "no"


def production_readiness(custom: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (is_ready, list_of_missing_items) for the opp's job type.

    Single source of truth for "is this job ready to hand off to Production?".
    """
    missing: list[str] = []

    for key, label in GLOBAL_DTS:
        if not truthy(custom.get(key)):
            missing.append(label)
    if not _permit_ok(custom):
        missing.append("permit (No or approved; unset counts as missing)")

    job_type = _job_type(custom.get(JOB_TYPE_FIELD))
    adds = _ADDS_BY_TYPE.get(job_type)
    if adds is None:
        missing.append(f"job type (seg_job_type unrecognized: {job_type!r})")
    else:
        for key, label in adds:
            if not truthy(custom.get(key)):
                missing.append(label)

    return (not missing, missing)


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    opp = unwrap_opportunity(payload)
    pipeline_id = opp.get("pipelineId")
    custom = custom_field_map(opp)
    current = _scalar(custom.get(OUTPUT_FIELD))

    base = {
        "handler_id": HANDLER_ID,
        "target_field": OUTPUT_FIELD,
        "current_value": _to_str(current),
    }

    if pipeline_id != PIPELINE_ID_SALES:
        return {
            **base,
            "decision": "no_op",
            "reason": f"pipelineId {pipeline_id!r} is not Sales ({PIPELINE_ID_SALES})",
        }

    ready, missing = production_readiness(custom)
    computed = "Yes" if ready else "No"
    detail = "all production prerequisites present" if ready else f"missing: {', '.join(missing)}"

    if _to_str(current) == computed:
        return {
            **base,
            "decision": "skip_idempotent",
            "reason": f"{OUTPUT_FIELD} already {computed} ({detail})",
        }

    return {
        **base,
        "decision": "would_stamp",
        "target_value": computed,
        "reason": f"would set {OUTPUT_FIELD} = {computed} ({detail})",
    }


def _to_str(v: Any) -> str | None:
    if isinstance(v, list):
        v = v[0] if v else None
    if v is None:
        return None
    return str(v)


async def execute(opp_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Set sys_production_readiness (Yes/No) via the GHL writer."""
    from handlers._writers import stamp_custom_field
    return await stamp_custom_field(opp_data, decision, OUTPUT_FIELD)
