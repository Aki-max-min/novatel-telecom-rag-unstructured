# Diagnosing 'No Service' After a SIM Swap

**Document ID:** KB_C05_sim_swap_troubleshooting  
**Category:** C05 — SIM Card Services  
**Department:** Customer Care  
**Last Updated:** 2026-08-06  
**Version:** 1.0  
**Source Authority:** Internal Knowledge Base

---

## Purpose

Step-by-step diagnostic flow for a SIM that shows no network after insertion.

## Diagnostic Flow

```mermaid
flowchart TD
A[No Service after SIM insert] --> B{Restarted device?}
B -- No --> C[Restart device]
B -- Yes --> D{Correct network mode?}
D -- No --> E[Set to Auto/4G+5G]
D -- Yes --> F{Persists after 30 min?}
F -- Yes --> G[Escalate: possible IMSI re-registration issue]
F -- No --> H[Resolved]
```

## When to Escalate

If the flow reaches step G, log a ticket per SOP_C05_SIM_REPLACEMENT and flag for provisioning-team review.