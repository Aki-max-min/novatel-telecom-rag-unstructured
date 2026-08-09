# Troubleshooting Failed Recharge Transactions

**Document ID:** KB_C03_recharge_failures  
**Category:** C03 — Recharge & Payments  
**Department:** Finance  
**Last Updated:** 2026-08-08  
**Version:** 1.0  
**Source Authority:** Internal Knowledge Base

---

## Purpose

Guidance for diagnosing a recharge that was debited but not credited to the account.

## Step-by-Step Diagnosis

1. Confirm the debit in the payment app/bank statement.
2. Check **Recharge History** in My NovaTel for a 'Pending' status.
3. Wait 60 minutes for auto-reconciliation.
4. If still pending after 24 hours, raise a ticket referencing SOP_C03_RECHARGE_FAILURE.

## Common Root Causes

- Gateway timeout after debit confirmation
- Bank-side delay in settlement file transfer
- Duplicate transaction ID collision (rare)

## Escalation

Unresolved cases beyond 48 hours should be escalated per SOP_C03_RECHARGE_FAILURE Step 5.