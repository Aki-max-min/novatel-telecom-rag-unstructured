# Understanding Plan Validity and Expiry

**Document ID:** KB_C02_plan_expiry
**Category:** C02 — Plans & Subscriptions
**Department:** Product
**Customer Scope:** all
**Last Updated:** 2026-04-13
**Version:** 1.0
**Source Authority:** Internal Knowledge Base

---
## Summary

This article explains how plans & subscriptions issues in this area are diagnosed and resolved, and what customers and front-line agents should check before escalating.

## Symptoms

- Customer reports the feature or service is not behaving as expected.
- The issue is intermittent and not consistently reproducible.
- The customer has already attempted the standard steps without success.

## Preconditions

- Customer identity has been verified (registered number and, where applicable, OTP).
- The account is active and not under a fraud, legal, or compliance hold.

## Cause

This most commonly occurs when a related account change (plan change, SIM swap, KYC update) has not yet fully propagated across systems.

## Resolution — Step by Step

| Step | Action | Expected Result | If Failed |
|---|---|---|---|
| 1 | Confirm the reported issue | Issue resolved / status updated | Proceed to next step or escalate |
| 2 | Check system status | Issue resolved / status updated | Proceed to next step or escalate |
| 3 | Apply the standard fix | Issue resolved / status updated | Proceed to next step or escalate |
| 4 | Confirm resolution with the customer | Issue resolved / status updated | Proceed to next step or escalate |

1. **Confirm the reported issue.** Ask the customer for the exact screen/message and time it occurred.
2. **Check system status.** Verify the relevant backend status (billing, provisioning, network, payment) for the account.
3. **Apply the standard fix.** Retry the action, refresh the record, or trigger the relevant backend re-sync as documented for this scenario.
4. **Confirm resolution with the customer.** Ask the customer to verify the fix on their end before closing.

## Validation

Confirm the account reflects the expected state (e.g. correct balance, plan, status, or setting) before closing the interaction.

## Exceptions

- Cases linked to suspected fraud are routed to the Fraud & Security Response team instead of standard resolution.
- Enterprise/bulk accounts may require coordination with the assigned account manager rather than the standard consumer flow.

## Escalation Criteria

- If the standard steps above do not resolve the issue, escalate with reference to: FAQ_C02_001.
- Where first-line steps do not resolve the issue within the stated timeframe, the case is escalated to the next tier with full interaction history attached, and the customer is informed of the new reference and expected timeline.

## Related Issues

- Repeated occurrences for the same customer may indicate an upstream system issue and should be flagged to the relevant platform team.

## Related Documents

Related documents: FAQ_C02_001.
