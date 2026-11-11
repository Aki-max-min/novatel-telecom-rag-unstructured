# Requests for Person A (from Person B, KG fixes 2)

Nothing in `data/processed`, `integration/` or any Person A file was changed. These are requests only.

## 1. Sixteen `related_ids` that point at documents that do not exist

Sixteen FAQ documents list `KB_Cnn_overview` as a related document, but no document with that id exists, and the categories below have no single KB document that
could stand in for it. They stay unresolved in our graph (stub nodes) and nothing is linked in their place. Categories affected (8): **C01, C10, C11, C12, C14, C15, C24, C27**.

| # | source document | related_id that does not exist |
|---|---|---|
| 1 | `FAQ_C01_001` | `KB_C01_overview` |
| 2 | `FAQ_C01_002` | `KB_C01_overview` |
| 3 | `FAQ_C10_019` | `KB_C10_overview` |
| 4 | `FAQ_C10_020` | `KB_C10_overview` |
| 5 | `FAQ_C11_021` | `KB_C11_overview` |
| 6 | `FAQ_C11_022` | `KB_C11_overview` |
| 7 | `FAQ_C12_023` | `KB_C12_overview` |
| 8 | `FAQ_C12_024` | `KB_C12_overview` |
| 9 | `FAQ_C14_027` | `KB_C14_overview` |
| 10 | `FAQ_C14_028` | `KB_C14_overview` |
| 11 | `FAQ_C15_029` | `KB_C15_overview` |
| 12 | `FAQ_C15_030` | `KB_C15_overview` |
| 13 | `FAQ_C24_047` | `KB_C24_overview` |
| 14 | `FAQ_C24_048` | `KB_C24_overview` |
| 15 | `FAQ_C27_053` | `KB_C27_overview` |
| 16 | `FAQ_C27_054` | `KB_C27_overview` |

### Options (your decision)

1. **Add a KB overview document** for each of the 8 categories (id `KB_Cnn_overview`). The 16 links then resolve with no change on our side; we would rebuild the graph.
2. **Correct the `related_ids`** in those 16 FAQs so they name documents that exist (or remove them).
3. **Confirm the links can be dropped.** They would remain permanently unresolved stubs, which is harmless for retrieval but keeps the unresolved count at 16 of 84.

## 2. For information: the 21 `KB_Cnn_*` -> `FAQ_Cnn_001` links

`FAQ_Cnn_001` does not exist for those 21 categories (the FAQ ids start at another number). We **assumed** that "001" is a placeholder for the category's own FAQs and
resolve each such link to **every FAQ document of that category (two per category)**, in our alias layer only (`knowledge_graph/related_id_aliases.json`,
rule `faq_placeholder_all_in_category`, flagged ASSUMPTION in `knowledge_graph/related_id_alias_audit.csv`). Please tell us if that reading is wrong; if it is, we set
`RESOLVE_FAQ_PLACEHOLDER = False` in `knowledge_graph/build_related_aliases.py`. Measured effect on the 52 development questions: none (the reverse FAQ -> KB links already
connect the same pairs, so the number of undirected linked pairs stays at 47).
