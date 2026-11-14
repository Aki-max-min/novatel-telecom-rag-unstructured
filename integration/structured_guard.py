"""
Guard around structured/retriever.py::StructuredRetriever.search for customer-scoped lookups on tables that have no
`customer_id` column. Person A's adapter code only: nothing in structured/ is edited or monkey-patched.

The failure it handles
    structured/query_parser.py resolves a table by keyword and, when the question names a customer, asks the retriever for an
    exact filter on `customer_id` (structured/retriever.py:113). On a table without that column the SQL layer raises
    `sqlite3.OperationalError: no such column: customer_id` (structured/data_loader.py:51). Before this guard that exception
    ended the whole question (a crash in the E14 pipeline; a false "I don't know" in the QA backend).

What it does instead (verified against the real schema, nothing invented)
    * The table has an `msisdn` column (cdr, recharge_transactions, sim_inventory) AND customer_master maps the customer to
      exactly one msisdn (customer_master: 1,809 customers, 1,809 distinct msisdn, one per customer):
      run the SAME filter on `msisdn` (StructuredRetriever.exact_filter, the retriever's own public method) and say so.
    * The table has neither column (corporate_accounts, coverage_5g, device_config, escalation_cases, network_alarms,
      network_sites, offers, plan_master, retail_outlets, technicians), or the customer has no unique msisdn mapping:
      return NO rows and a status {"executed": False, "reason": ...} so the caller can say "the database part could not be
      executed" instead of pretending nothing exists.
    * Any other exception is not swallowed.

Status dict (always returned): {"executed": bool, "route": "direct" | "msisdn_mapping" | "not_executable", "reason": str|None,
"table": str|None, "customer_id": str|None, "msisdn_lookup": {...}|None}
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

NO_CUSTOMER_COLUMN = re.compile(r"no such column: customer_id", re.I)


@dataclass
class GuardedResult:
    results: list
    parsed: dict
    status: dict = field(default_factory=dict)


def _columns(conn: sqlite3.Connection, table: str) -> list[str] | None:
    known = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if table not in known:          # also guards the PRAGMA below against anything that is not a real table name
        return None
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def guarded_structured_search(retriever, query: str, top_k: int) -> GuardedResult:
    """retriever: a structured.retriever.StructuredRetriever. Returns the results list in the retriever's Common Schema."""
    try:
        res = retriever.search(query, top_k=top_k)
        parsed = res.get("parsed_query") or {}
        return GuardedResult(res.get("results", []), parsed,
                             {"executed": True, "route": "direct", "reason": None, "table": parsed.get("table"),
                              "customer_id": None, "msisdn_lookup": None, "note": res.get("note")})
    except sqlite3.OperationalError as exc:
        if not NO_CUSTOMER_COLUMN.search(str(exc)):
            raise

    from query_parser import parse_query   # structured/ is on sys.path whenever a StructuredRetriever exists

    parsed = parse_query(query)
    table, customer_id = parsed.get("table"), parsed.get("filter_value")
    base = {"table": table, "customer_id": None if customer_id is None else str(customer_id), "msisdn_lookup": None}
    cols = _columns(retriever.loader.conn, table) if table else None
    if cols is None:
        return GuardedResult([], parsed, {**base, "executed": False, "route": "not_executable",
                                          "reason": "the question could not be mapped to a database table"})
    if "msisdn" not in cols:
        return GuardedResult([], parsed, {**base, "executed": False, "route": "not_executable",
                                          "reason": f"table '{table}' has no customer_id and no msisdn column, so a "
                                                    f"per-customer lookup cannot be run on it"})

    mapping = retriever.exact_filter("customer_master", "customer_id", customer_id, top_k=2)["results"]
    msisdns = {str((r.get("metadata") or {}).get("msisdn")) for r in mapping if (r.get("metadata") or {}).get("msisdn")}
    if len(msisdns) != 1:
        why = ("customer_master has no row for this customer" if not msisdns
               else "customer_master maps this customer to more than one msisdn")
        return GuardedResult([], parsed, {**base, "executed": False, "route": "not_executable",
                                          "reason": f"table '{table}' is keyed by msisdn and {why}"})
    (msisdn,) = msisdns
    rows = retriever.exact_filter(table, "msisdn", msisdn, top_k=top_k)["results"]
    lookup = {"via": "customer_master.customer_id -> msisdn", "filter_column": "msisdn", "filter_value": msisdn}
    parsed = {**parsed, "filter_column": "msisdn", "filter_value": msisdn}
    return GuardedResult(rows, parsed, {**base, "executed": True, "route": "msisdn_mapping", "reason": None,
                                        "msisdn_lookup": lookup})
