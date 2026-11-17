"""
Status adapter around structured/retriever.py::StructuredRetriever.search for customer-scoped lookups. Person A's adapter code only:
nothing in structured/ is edited or monkey-patched.

History (why this file changed, 2026-11-17)
    Version 1 (5d11ae5, 2026-10-31) CAUGHT `sqlite3.OperationalError: no such column: customer_id` and did the msisdn mapping itself.
    Person B's 794662c (2026-11-01) moved that logic into StructuredRetriever.customer_scoped_filter, which never raises; version 1's
    success path then reported executed=True, route="direct" for every question. Person B's contract-fixes (7adfb65) added `empty_reason`
    to every return. This version READS the retriever's result and catches nothing.

The contract it relies on (customer_scoped_filter; every other search path simply has no `empty_reason`)
    executed       always a bool on a scoped lookup. False ONLY when the table cannot be scoped to a customer
                   (empty_reason "table_not_scopable" or "unknown_table"). True otherwise, even when no row comes back.
    route          "msisdn_mapping" only on the msisdn path; the direct path has no `route` key.
    empty_reason   None when rows came back, else one of: unknown_table, table_not_scopable, unknown_customer (msisdn path only; also
                   a customer with more than one customer_master row), no_rows (customer_id path, or a mapped msisdn with no rows).
    note           developer text; copied to the status for logging, NEVER shown to a user.
A search path that has no `executed` key (unresolved parse, aggregate, plain exact_filter) ran normally: executed=True.
A non-bool `executed` is a contract violation and raises TypeError.

Status dict (always returned):
    {"executed": bool, "route": "direct" | "msisdn_mapping" | None, "reason": str | None, "empty_reason": str | None,
     "table": str | None, "customer_id": str | None, "msisdn_lookup": {...} | None, "note": str | None}
    route is None only when executed is False. `reason` is OUR user-facing wording and is set only when executed is False.
    unknown_customer and no_rows are "nothing found" (executed stays True): they are never reported as "could not be executed".
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Person B's vocabulary (structured/retriever.py::customer_scoped_filter docstring)
NOT_SCOPABLE = ("table_not_scopable", "unknown_table")
MSISDN_ROUTE = "msisdn_mapping"


@dataclass
class GuardedResult:
    results: list
    parsed: dict
    status: dict = field(default_factory=dict)


def _unexecutable_reason(empty_reason: str | None, table: str | None) -> str:
    """Our own wording for a lookup that cannot be run (the retriever's note text is developer text, not a contract)."""
    if empty_reason == "table_not_scopable":
        return f"table '{table}' has no customer_id and no msisdn column, so a per-customer lookup cannot be run on it"
    if empty_reason == "unknown_table":
        return "the question could not be mapped to a database table"
    return f"the per-customer lookup on table '{table}' could not be run ({empty_reason})"


def status_from_result(res: dict) -> tuple[dict, dict]:
    """(status, parsed) for one StructuredRetriever.search result. Pure; reads the result, raises only on a contract violation."""
    parsed = dict(res.get("parsed_query") or {})
    results = res.get("results") or []
    executed = res.get("executed", True)
    if not isinstance(executed, bool):
        raise TypeError(f"StructuredRetriever result has a non-bool 'executed': {executed!r}")
    table = parsed.get("table")
    empty_reason = res.get("empty_reason")
    customer_id = parsed.get("filter_value") if parsed.get("filter_column") == "customer_id" else None

    msisdn_lookup = None
    if "route" in res:
        route = res["route"]
    else:
        route = "direct" if executed else None
    if route == MSISDN_ROUTE and results:
        msisdn = str((results[0].get("metadata") or {}).get("msisdn") or "") or None
        if msisdn:
            msisdn_lookup = {"via": "customer_master.customer_id -> msisdn", "filter_column": "msisdn", "filter_value": msisdn}
            parsed = {**parsed, "filter_column": "msisdn", "filter_value": msisdn}   # what was actually filtered on (as version 1 reported)

    status = {"executed": executed, "route": route, "reason": None if executed else _unexecutable_reason(empty_reason, table),
              "empty_reason": empty_reason, "table": table, "customer_id": None if customer_id is None else str(customer_id),
              "msisdn_lookup": msisdn_lookup, "note": res.get("note")}
    return status, parsed


def guarded_structured_search(retriever, query: str, top_k: int) -> GuardedResult:
    """retriever: a structured.retriever.StructuredRetriever. Returns the rows in the retriever's Common Schema plus the status above.
    No exception is caught: any error from the retriever propagates."""
    res = retriever.search(query, top_k=top_k)
    status, parsed = status_from_result(res)
    return GuardedResult(res.get("results", []), parsed, status)
