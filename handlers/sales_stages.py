"""Single source of truth for the Sales pipeline's stage identity.

Stage UUIDs were duplicated across every Sales mover; this module centralizes them
(plus the legacy stage-code map used for the sys_last_good_* audit fields) so the movers
and the drift enforcer cannot drift apart. The forward movers still import their own
STAGE_ID_* names for readability, but the code<->id mapping lives here.

Legacy codes (S10..S50 / PL_SALES) are deprecated as *stage identity* (CR-0022 — GHL IDs are
canonical), but the move specs' `fields_written` still record them in sys_last_good_stage_code
for audit/rewind bookkeeping, mirroring what the Production movers write (PL_PROD / P40 etc.).
"""
from __future__ import annotations

PIPELINE_ID_SALES = "9KlQhUS34GzTN9q34WKF"
LAST_GOOD_PIPELINE_CODE = "PL_SALES"

STAGE_ID_S10 = "7358ceec-e07a-405f-a3c6-f9597a1ddf0d"  # Inspection Booked
STAGE_ID_S20 = "f66b7a47-61a0-4527-8c23-0b9810e482bc"  # Inspection Complete
STAGE_ID_S30 = "846fb074-d25d-4e31-a76e-a38b23e4e09c"  # Scope Pending / Build Estimate
STAGE_ID_S40 = "d270f2b4-d14e-4bff-813f-ed02e9e21d10"  # Job Pending Approval
STAGE_ID_S45 = "7d1d1248-8de5-43f0-8876-c9bc23b3b51e"  # Approved — Funding Pending
STAGE_ID_S46 = "4ced8cf3-6088-4a6b-92f6-73a6f56a030f"  # Initial Funding Received
STAGE_ID_S50 = "ee57c6b2-0613-4a49-b5ea-0b2185a0b70c"  # Handoff To Production

# Ordered low -> high. The enforcer walks this; the index is the stage's rank.
SALES_STAGE_ORDER: list[tuple[str, str]] = [
    (STAGE_ID_S10, "S10"),
    (STAGE_ID_S20, "S20"),
    (STAGE_ID_S30, "S30"),
    (STAGE_ID_S40, "S40"),
    (STAGE_ID_S45, "S45"),
    (STAGE_ID_S46, "S46"),
    (STAGE_ID_S50, "S50"),
]

STAGE_CODE_BY_ID: dict[str, str] = {sid: code for sid, code in SALES_STAGE_ORDER}


def stage_code_for(stage_id: str | None) -> str | None:
    """Return the legacy S-code for a Sales stage id, or None if not a Sales stage."""
    if stage_id is None:
        return None
    return STAGE_CODE_BY_ID.get(stage_id)
