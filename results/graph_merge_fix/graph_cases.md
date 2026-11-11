# Gold-rank regressions with CrossEncoder scores (run 1 retrieval re-run without the LLM)

A case is a document question whose gold document ranks worse with the graph arm than in the plain B2 search (or leaves the top 10). 'ce' = CrossEncoder score against the original question; 'added' = the chunk joined the pool through the graph. With the fixed merge every document above the gold must have a higher CrossEncoder score than the gold's best chunk (checked in the last column).

## GF: 0 regression case(s); re-run top-10 equals the stored run-1 record on 25 of 25 document questions

| id | cat | gold | rank B2 -> arm | gold best chunk (ce) | documents above the gold (doc: ce, added?) | all above have higher ce? |
|---|---|---|---|---|---|---|

## GFL: 0 regression case(s); re-run top-10 equals the stored run-1 record on 25 of 25 document questions

| id | cat | gold | rank B2 -> arm | gold best chunk (ce) | documents above the gold (doc: ce, added?) | all above have higher ce? |
|---|---|---|---|---|---|---|
