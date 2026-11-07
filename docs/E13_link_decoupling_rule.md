# E13 link decoupling - pre-declared rule (committed BEFORE any code or experiment)

Background: the incident-link trace (`docs/E13_incident_link_trace.md`) showed that the gate gives graph weight 0.0 to four of the five
incident questions, and weight 0.0 excludes the whole graph list - resolved RELATED_TO links included - from fusion. So links currently
cannot help on exactly the questions where they would matter. IL1 is a different failure: a reranker miss (the CrossEncoder ranked the partner
9 of 9); it is recorded as such and the reranker is not changed here.

## Change under test

Resolved RELATED_TO neighbours form their **own ranked list** in `hybrid/fusion.py`, independent of the gate's graph weight. The
concept-candidate list keeps using the gate and `GRAPH_ENABLED` exactly as now.

- Seeds for links: the **top 3 vector documents only**.
- Cap: **at most 2** linked documents added.
- Fusion weight of the link list: `w_link` in {0.15, 0.30, 0.50}. Same document-level RRF formula and k as the rest of fusion
  (`w_link / (k + rank)`, k = 60); a document in several lists sums its contributions.
- **3 cells + the links-off baseline.**

## Dev sets and baseline

Dev sets: main 29, mini 9, validation 14 - the same sets as the hardening evaluation (`docs/E13_kg_hardening_rule.md`); **not** Person A's
42 questions, which must not be used for tuning.

Baseline = the current default: graph off (`GRAPH_ENABLED = False`), links off. All cells use the same pipeline, gate and default rerank
mode; only the link list differs.

Per question, on document-level Recall@3, exactly as in the hardening rule: **win** = baseline missed the expected document in the top 3 and
the cell hits it; **loss** = the reverse. Secondary metrics per cell, not used for selection: R@1 and MRR@5 (R@3 and R@5 are reported too).

## Selection

Among the three cells choose the highest pooled (wins - losses); ties broken by the smaller `w_link`.

## Adoption rule

Links become the default (`LINKS_ENABLED = True`) **ONLY IF all three hold**:

1. pooled losses <= 1;
2. no single dev set has net < -1;
3. on the 5-question incident mechanism check (`hybrid/benchmark/incident_link_check.json`), links-on gets **at least one more pair** (both
   documents of the INC/RCA pair) into the final top 5 than links-off.

If it fails, links stay **off** by default and the result is reported as a negative result with the table. Selection and adoption use the dev
sets and the mechanism check only.

## What the mechanism check is not

Five incident/RCA pairs is a **mechanism check, not generalisation evidence**: it can show that the plumbing works, not that links help in general.
The final unbiased run is Person A's single run on her 42 questions.

## Not changed

`hybrid/query_gate.py` outputs, the reranker, and the frozen benchmark files (`hybrid/benchmark/first_run_phase7.json` etc.) are not changed.
