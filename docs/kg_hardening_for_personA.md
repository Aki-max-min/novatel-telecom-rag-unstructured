# Knowledge-graph hardening - handoff for Person A's Claude

Branch: `person-b/kg-hardening` (from `person-b/parser-tiers-msisdn`). Not merged to main, no tag. Only Person B's files changed
(`knowledge_graph/`, `hybrid/`, `structured/`, `docs/`, README, `.gitignore`); Person A's source documents were not edited.

## Verdict first

The pre-declared evaluation (`docs/E13_kg_hardening_rule.md`, committed before any code) compared 22 `graph_expand` configurations on **dev sets only**
(main 29, mini 9, validation 14; your 42 questions were NOT used). **Adoption rule: FAIL - negative result.** The best cell (`V2 h=0.05 m=3`) reaches
pooled wins - losses = **+1** (1 win, 0 losses), below the pre-declared +2; every cell is within one question of the graph-off baseline, and the legacy
profile itself is net +1. Full table: `docs/E13_kg_hardening_results.md`. So **in `hybrid/` the graph is OFF by default** (`GRAPH_ENABLED = False` in
`hybrid/pipeline.py`; the trace says "graph disabled by config").

What the work did establish: the hub defect is real and measurable at the candidate level (72.4% of legacy candidates share only hub concepts; same-category
p@5 0.38 -> 0.68 with a hub cut -> 0.85 for the best specific-label cell). What it could not show: a downstream gain after fusion and the CrossEncoder.
The dev sets have almost no resolution (one question = 1.9 points pooled), and the rerank may be undoing a weak graph signal (roadmap Section 8).

## New `graph_expand` parameters (`knowledge_graph/graph_augmented_retrieval.py`)

Keyword-only, all optional; with none given the behaviour is EXACTLY the legacy one (golden-tested against 11 recorded outputs in
`knowledge_graph/tests_data/graph_expand_golden.json`). The call signature `graph_expand(seeds, graph_index, bridges=..., limit=...)` is unchanged.

| parameter | meaning |
|---|---|
| `hub_fraction=None` | drop concepts whose document frequency is > `hub_fraction` x N |
| `specificity=False` | weight each shared concept by `log(N/df)` instead of 1 |
| `max_documents=None` | cap on the returned candidates (together with `limit`) |
| `allowed_labels=None` | restrict the bridge labels (e.g. `["Service","VerificationMethod","Tag"]`) |

Also new: `GraphIndex.document_frequency(label, concept)`, `GraphIndex.document_count`, `GraphIndex.related` (undirected resolved RELATED_TO links) and
`related_neighbours(seeds, graph_index, limit)`. Ordering is deterministic (score desc, shared_count desc, id asc).

Profile names used in the evaluation (reproduce your review with `V0`):

| name | kwargs |
|---|---|
| V0 (legacy) | none |
| V1 hub cut | `hub_fraction` in {0.05, 0.10, 0.20} |
| V2 | V1 + `specificity=True` + `max_documents` in {3, 5, 10} |
| V3 | V2 + `allowed_labels=["Service","VerificationMethod","Tag"]` |
| best by the rule (not adopted) | `hub_fraction=0.05, specificity=True, max_documents=3` |

## RELATED_TO repair (alias file)

`python -m knowledge_graph.build_related_aliases` writes `knowledge_graph/related_id_aliases.json` and `related_id_alias_audit.csv`
(columns source_doc, original_target, resolved_target, rule, status); then `python -m knowledge_graph.graph_builder` rebuilds `output/graph.json`.
Deterministic rules only: `INC_INC_<id>` -> the unique `INC_Cnn_INC_<id>` (5), `KB_Cnn_overview` -> the unique `KB_Cnn_*` (42); `FAQ_Cnn_001` is never
aliased (ambiguous). Result: **47 of 84** edges resolve (`resolved=true`, `via_alias=true`), 37 stay unresolved stubs (21 FAQ + 16 KB). Two builds are
byte-identical (tested). Your documents are untouched.

**Your semantic layer picks these up automatically.** `integration/rag/semantic_layer.py::_read_related_edges` (branch `integrate/kg-ontology-router-ui`)
reads `RELATED_TO` edges from `output/graph.json`; a compatibility test replicates that reader against the rebuilt graph and gets 47 resolvable pairs
(vs 0 before), so `use_related_links=True` now has something to add. One difference: your `neighbours()` appends linked documents AFTER the concept
list; `hybrid/retrievers.py` puts them FIRST. Mechanism check (5 incident/RCA questions, `hybrid/benchmark/incident_link_check.json`): both documents of the
pair in the final top 5 with links ON 3/5, OFF 3/5 - **no change**, and the trace (`docs/E13_incident_link_trace.md`) shows why: the gate gives graph weight 0.0 to four of the five questions (IL1, IL3, IL4, IL5; only IL2 has a concept hint), and weight 0.0 excludes the whole graph list - links included - from fusion. IL4: the linked partner INC_C13_INC_2026_0184 was graph rank 3 but never entered fusion for that reason. IL1: the partner was already vector rank 2 and fusion rank 2, but the rerank (rerank-only rank 9 of 9) pushed it to blend rank 6, just outside the top 5; the graph played no part. So the check barely exercised the link mechanism; links only matter for questions with a gate weight above 0. This is a mechanism
check on five pairs, not evidence of generalisation.

`knowledge_graph/output/` is generated and not tracked in git: after cloning run `python -m knowledge_graph.graph_builder`, then
`python -m hybrid.setup_check` (OK/MISSING for each asset with the fix command). `load_graph_index` raises `FileNotFoundError` naming that command.

## Foreign-key follow (`structured/retriever.py`)

`StructuredRetriever.fk_follow(question, customer_id=None)` (and `search()`, which calls it first): a question naming a parent record ("invoice 5001",
"ticket 11011") plus a child entity ("payment transactions", "escalation case") returns the parent row plus its child rows, each child with
`metadata["relation"] = "fk:<parent>.<column>"` (e.g. `fk:invoices.invoice_id`). The parent->child allowlist is built from `structured/schema.py`
`foreign_keys` (invoices->payment_transactions, tickets->escalation_cases, network_sites->network_alarms, device_config->device_registry); names are validated
against the schema, values parameterised. Customer scoping applies: a parent that belongs to another customer, an unknown id, a table pair without a foreign key
and an injection string all return an empty result with a note, never someone else's rows. The structured Neo4j KG is NOT used (out of scope).
Tests: `structured/tests/test_fk_follow.py` with `join_cases.json` (ids chosen by SQL; expected rows recomputed from the database).
**Pass the signed-in session's customer id** (`customer_id=`); the id is otherwise read from the question text, which a user controls.

## Run your 42 questions ONCE

The 42-question harness is not in this repository, so I cannot give you a command that runs it. What to do:
1. check out `person-b/kg-hardening`, rebuild the graph (`python -m knowledge_graph.build_related_aliases && python -m knowledge_graph.graph_builder`) and
   run `python -m hybrid.setup_check`;
2. run your harness unchanged for the baseline (graph off: `GRAPH_ENABLED=False`, i.e. `hybrid.pipeline.run_hybrid_query`'s default) - this is the profile the rule selected;
3. if you want the best-by-the-rule graph profile as well, pass it to your `graph_expand` call:
   `graph_expand(seeds, graph_index, bridges=..., limit=..., hub_fraction=0.05, specificity=True, max_documents=3)` (or `run_hybrid_query(..., graph_enabled=True)` in this repo);
4. run each configuration **once**, report every number.

**Warning: the 42 questions must not be used for tuning.** They are the final unbiased run. Everything chosen here was chosen on the dev sets only; if you tune a profile on the 42
the number stops meaning anything.

## Not touched here (yours)

The router is yours and was not changed: its confidence threshold of 0.5 never fires, and incident-type questions must not go database-only. This branch
does not change `hybrid/query_gate.py` outputs or any frozen benchmark file (`hybrid/benchmark/first_run_phase7.json` is byte-identical to origin).
