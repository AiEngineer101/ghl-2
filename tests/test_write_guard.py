"""Unit tests for the per-opp write authorization guard.

This is the safety-critical gate that lets a scoped Sales TEST opp receive active writes
while every other live Sales opportunity stays protected. Test the full matrix.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from write_guard import is_write_allowed  # noqa: E402

PROD = "88V9uYY6visCrtI9V0NR"
SALES = "9KlQhUS34GzTN9q34WKF"
TEST_OPP = "U970gIvE6Q31JKTCGVNw"
LIVE_HANDLER = "move-sales-s10-s20-inspection-complete"
PIPELINES = {PROD}          # Production-only pipeline allowlist (the live default)
OPPS = {TEST_OPP}           # one scoped Sales test opp


def _allowed(opp, pipeline, writes=True, handler=None, handlers=None):
    ok, _ = is_write_allowed(
        opp,
        pipeline,
        writes_enabled=writes,
        allowed_pipelines=PIPELINES,
        allowed_opps=OPPS,
        handler_id=handler,
        allowed_handlers=handlers,
    )
    return ok


def test_blocked_when_writes_disabled_even_if_allowlisted():
    assert _allowed(TEST_OPP, SALES, writes=False) is False
    assert _allowed("any", PROD, writes=False) is False


def test_production_opp_allowed_by_pipeline():
    assert _allowed("any-prod-opp", PROD) is True


def test_scoped_test_opp_allowed_despite_non_allowlisted_pipeline():
    """The whole point: U970 is in Sales (not pipeline-allowlisted) but is opp-allowlisted."""
    assert _allowed(TEST_OPP, SALES) is True


def test_other_sales_opp_blocked():
    """Any OTHER live Sales deal must stay protected."""
    assert _allowed("some-other-sales-opp", SALES) is False


def test_unknown_opp_in_unknown_pipeline_blocked():
    assert _allowed("random", "random-pipeline") is False


def test_reason_is_informative_when_blocked():
    ok, reason = is_write_allowed(
        "x", SALES, writes_enabled=True, allowed_pipelines=PIPELINES, allowed_opps=OPPS
    )
    assert ok is False
    assert "not writable" in reason


# --- Per-handler "pipeline-live" allowlist (the Sales cutover knob) ---

def test_handler_allowlist_lets_any_sales_opp_write_for_that_handler():
    """A live handler may write to ANY (non-test) Sales opp — this is the cutover unit."""
    assert _allowed("some-other-sales-opp", SALES, handler=LIVE_HANDLER,
                    handlers={LIVE_HANDLER}) is True


def test_other_handler_still_blocked_for_same_sales_opp():
    """Only the allowlisted handler goes live; a different mover still can't write that opp."""
    assert _allowed("some-other-sales-opp", SALES, handler="move-sales-s20-s30-scope-pending",
                    handlers={LIVE_HANDLER}) is False


def test_handler_allowlist_still_respects_master_switch():
    assert _allowed("some-other-sales-opp", SALES, writes=False, handler=LIVE_HANDLER,
                    handlers={LIVE_HANDLER}) is False


def test_empty_handler_allowlist_is_a_no_op():
    """Default (no handlers listed) leaves behaviour exactly as the pipeline/opp rules dictate."""
    assert _allowed("some-other-sales-opp", SALES, handler=LIVE_HANDLER, handlers=set()) is False
    assert _allowed("some-other-sales-opp", SALES, handler=LIVE_HANDLER, handlers=None) is False


def test_handler_none_does_not_match_allowlist():
    """A write with no handler_id can't be authorized by the handler rule."""
    assert _allowed("some-other-sales-opp", SALES, handler=None, handlers={LIVE_HANDLER}) is False
