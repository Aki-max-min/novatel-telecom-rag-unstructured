# Note for Person B: customer-scoped lookups on tables without `customer_id`

From Person A, 2026-10-31. **Nothing in `structured/` was edited.** This is a description of a failure we hit and how Person A's
adapters now route around it, so you can decide whether to fix it at the source.

## The failure
A question that names a customer is parsed to an `exact_filter` on `customer_id` whatever table the keyword chose. If that table has
no `customer_id` column, the SQL layer raises and the whole query ends.

| Step | File | Function | Line |
|---|---|---|---|
| Parser always emits a `customer_id` filter when it finds a customer id | `structured/query_parser.py` | `parse_query` | 169-174 (`"filter_column": "customer_id"`) |
| Retriever dispatches on it without checking the table's columns | `structured/retriever.py` | `StructuredRetriever.search` | 112-113 (`self.exact_filter(table, "customer_id", ...)`) |
| Generic filter helper builds the SQL | `structured/data_loader.py` | `DataLoader.filter_by` | 51 (`SELECT * FROM {table_name} WHERE {column} = ?`) |

Error: `sqlite3.OperationalError: no such column: customer_id`

## Failing inputs (reproduced)
* `Show recharge transactions for customer 1056`
* `For customer 1056: My last recharge didn't go through - what happens to the money, and what should I do?` (item `RB_B02` of the frozen route benchmark)
* any customer-scoped question parsed to `cdr` or `sim_inventory`, or to a table with neither column (`network_sites`, `offers`, `plan_master`, ...).

## What the real schema looks like (read from the SQLite file, not assumed)
* 28 tables. 15 have `customer_id`.
* **Without `customer_id` but with `msisdn`:** `cdr`, `recharge_transactions`, `sim_inventory`.
* **With neither:** `corporate_accounts`, `coverage_5g`, `device_config`, `escalation_cases`, `network_alarms`, `network_sites`, `offers`,
  `plan_master`, `retail_outlets`, `technicians`.
* `customer_master` maps customer to msisdn one-to-one: 1,809 customers, 1,809 distinct msisdn, and every msisdn in `recharge_transactions` (1,716) exists there.

## What Person A's adapters do now (`integration/structured_guard.py`)
1. Call `StructuredRetriever.search` as before. If it works, nothing changes.
2. On exactly `no such column: customer_id`: re-parse with your `parse_query`; read the table's columns with `PRAGMA table_info`.
3. Table has `msisdn` and `customer_master` returns exactly one msisdn: call your own `exact_filter(table, "msisdn", <msisdn>)` and mark the result `route = msisdn_mapping`.
4. Otherwise return no rows and `executed = False` with the reason, so the answer says "the database lookup could not be executed" rather than "I don't know".
5. Any other exception is re-raised.

## Suggestions (not applied, your call)
* In `StructuredRetriever.search`, check the target table's columns before choosing `customer_id`, and use the msisdn route (or return a clear "not applicable") for msisdn-keyed tables.
* `escalation_cases` has no customer column either but links to `tickets` by `ticket_id`; a customer-scoped escalation question needs a join the parser cannot express today.
* Your `origin/person-b/parser-wordboundary` branch (word-boundary keyword matching) is separate; Person A is trialling it on a local branch and will report differences.
