# GHL Setup — DEFERRED

> **This document describes GHL configuration that has NOT been done yet.**
> No changes have been made to any existing GHL workflow as part of this service.
> When you're ready to put the shadow service on real GHL events, follow these steps.
> Each step is purely additive — none of them modify an existing live workflow's logic.

## Goal

Send GHL `Opportunity Changed` events to the shadow service so it can mirror what
the existing production workflows would do. The existing workflows continue running
exactly as today and remain the system of record.

## Prerequisites

- Shadow service deployed and `/healthz` returning 200
- The service URL (e.g., `https://ghl-shadow.onrender.com`)
- A strong `WEBHOOK_SECRET` set in Render's env vars (use `openssl rand -hex 32`)
- Admin access to the GHL sub-account (`SS: SmartRoofing AI v2.1`)

## Step 1 — Create the shadow listener workflow (additive, isolated)

This is a **brand new** workflow. It does not edit, replace, or interfere with any
existing workflow.

1. In GHL: Automations → Workflows → **Create New Workflow**
2. Name: `WF | Shadow | Opportunity Changed Bridge`
3. Trigger: **Opportunity Changed**
   - No filters (shadow service should see all opp changes; it filters internally)
4. Action: **Webhook**
   - URL: `https://<your-render-domain>/webhook/ghl`
   - Method: `POST`
   - Headers:
     - `X-Webhook-Secret: <the secret from Render env>`
     - `Content-Type: application/json`
   - Body (Custom JSON):
     ```json
     {
       "type": "OpportunityUpdate",
       "locationId": "{{location.id}}",
       "opportunity_id": "{{opportunity.id}}",
       "opportunity": {
         "id": "{{opportunity.id}}",
         "pipelineId": "{{opportunity.pipeline_id}}",
         "pipelineStageId": "{{opportunity.pipeline_stage_id}}"
       }
     }
     ```
     (The shadow service re-fetches the full opportunity via the GHL API, so this
     minimal payload is enough.)
5. Workflow Settings:
   - Allow Re-Entry: **ON**
   - Allow Multiple Opportunities: **ON**
   - Stop on Response: **OFF**
6. **Publish**.

Result: every opportunity change now fires this new workflow IN ADDITION TO the
existing production workflows. Both run in parallel, but only the existing ones
write to GHL. The shadow service receives a copy of the event, records what it
would have done, and never writes back.

## Step 2 — Verify with a real test opportunity

1. Create or use a known opportunity (preferably one of your own test contacts).
2. Update a custom field on it (e.g., add a `dt_install_scheduled` value).
3. Within ~10 seconds, check the shadow service:
   ```bash
   curl https://<your-render-domain>/events
   curl https://<your-render-domain>/decisions
   ```
4. Confirm the decisions match what the live GHL workflow actually did.

## Step 3 — Compare shadow vs. live for a week

For the first 5–7 days, just observe:

- The shadow service logs what it would have done for every opportunity event.
- The existing GHL workflows continue running and writing.
- You compare the two on a rolling basis — same decisions? Edge cases handled?

If you see a mismatch (shadow says "would_stamp" but live didn't, or vice versa),
the spec or the handler needs to be reconciled before promoting writes.

## Step 4 — (Future, not yet planned) Promote to active writes

When you're confident:

1. Add a `cfg_use_python_engine` Custom Field on Opportunity (default empty/No).
2. Add a `python_engine_enabled` Custom Value on the location (default `No`).
3. Add this Condition at the TOP of each existing workflow you want Python to take over
   (this is the **only** edit to a live workflow, and it's purely an early-exit guard):
   ```
   IF cfg_use_python_engine = "Yes" → END
   ELSE → continue (existing logic)
   ```
4. Update the shadow service: add write methods to a new `ghl_writer.py` module,
   gated by `MODE=active` AND the opp's `cfg_use_python_engine = Yes`.
5. Flip `cfg_use_python_engine = Yes` on one test opportunity. Verify.
6. Expand the cohort gradually.

**Until step 4, this service writes nothing to GHL. Real customers are not affected.**

## Rollback

If anything misbehaves at any stage:

1. **In GHL**: pause or unpublish `WF | Shadow | Opportunity Changed Bridge`. The
   shadow service stops receiving new events. The existing workflows are unaffected
   (they were never modified).
2. **In Render**: stop the service. No effect on GHL — the live workflows continue
   running exactly as today.

No customer-visible behavior changes from any of the above. The shadow is a
silent observer; pausing it does nothing to your CRM data.

## Notes on the GHL Workflow Output Contract

The new `WF | Shadow | Opportunity Changed Bridge` workflow above is documented
per the standards in `project-files/SmartRoofingAI_BuildInstruction_OutputContract_v1_4.md`.
When you build it in GHL, follow that contract's slot format so it can be audited
the same way as every other workflow.
