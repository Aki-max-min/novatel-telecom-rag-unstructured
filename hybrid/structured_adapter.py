"""
Customer-scoped, READ-ONLY structured adapter (E13 Phase 7a).

fetch_customer_facts(customer_id, intents, as_of=None, limit=3) returns the
session customer's own facts as Common Result Schema dicts
(source="structured_sql", retrieval_method="structured_sql",
record_id=f"{table}:{pk}").

Why this module uses its own read-only sqlite3 connection instead of
structured/data_loader.DataLoader / StructuredRetriever: DataLoader opens the
database read-write (plain sqlite3.connect) and builds SQL with f-strings; this
adapter must open it read-only (file:...?mode=ro) and use fixed, parameterised
SQL only. `category` is still taken from structured/schema.py's category_tag, exactly
as StructuredRetriever._wrap_result emits it. It is carried through untouched and
is NEVER compared or joined on anywhere in hybrid/: the C-code taxonomies of the
two branches conflict (structured C11 = tickets vs document C16 = Complaints, ...).
Cross-branch meaning travels in metadata["concept"], from the shared concept
vocabulary in knowledge_graph/concept_bridge.py.

Rules enforced here:
  * every query is filtered by the SESSION customer_id; recharge_transactions is
    keyed by msisdn, which is looked up from the customer's own customer_master row
    (never taken from question text);
  * stored values are reported verbatim; anything derived is labelled under
    metadata["derived"] and never overrides a stored field;
  * data minimisation: fixed allow-list of fields per intent (no name/dob/email/
    address), msisdn is never returned and is masked to its last 4 digits in content;
  * a customer with no rows for an intent gets an empty list for that intent.
"""

import importlib.util
import os
import sqlite3
import sys
from datetime import date, datetime
from decimal import Decimal

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from knowledge_graph.concept_bridge import load_crosswalk  # noqa: E402

DB_PATH = os.path.join(REPO_ROOT, "data", "processed", "structured", "novatel_structured.db")

INTENTS = ("recharge", "kyc", "subscription", "tickets", "invoice")


def _load_structured_schema():
    """structured/schema.py by path (its module name 'schema' is too generic to import by name)."""
    spec = importlib.util.spec_from_file_location(
        "novatel_structured_schema", os.path.join(REPO_ROOT, "structured", "schema.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_schema = _load_structured_schema()
_CONCEPT_BY_TABLE = {row["structured_table"]: row["shared_domain_concept"]
                     for row in load_crosswalk()["rows"]}


def open_readonly(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Read-only connection: any write attempt raises sqlite3.OperationalError."""
    uri = "file:" + db_path.replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Fixed, parameterised SQL (no string building anywhere)
# ---------------------------------------------------------------------------
SQL_CUSTOMER = "SELECT customer_id, msisdn, kyc_status FROM customer_master WHERE customer_id = ?"
SQL_RECHARGES = (
    "SELECT recharge_id, amount, plan_id, channel, timestamp, status, balance_after "
    "FROM recharge_transactions WHERE msisdn = ? ORDER BY timestamp DESC, recharge_id DESC LIMIT ?")
SQL_KYC_RECORDS = (
    "SELECT kyc_id, kyc_type, status, last_updated FROM kyc_records "
    "WHERE customer_id = ? ORDER BY last_updated DESC, kyc_id DESC LIMIT ?")
SQL_SUBSCRIPTIONS = (
    "SELECT s.subscription_id, s.plan_id, s.activation_date, s.expiry_date, s.status, s.renewal_type, "
    "p.plan_name, p.price, p.validity_days "
    "FROM subscriptions s LEFT JOIN plan_master p ON p.plan_id = s.plan_id "
    "WHERE s.customer_id = ? ORDER BY s.expiry_date DESC, s.subscription_id DESC LIMIT ?")
SQL_TICKETS = (
    "SELECT ticket_id, category, subcategory, created_at, sla_due_at, status FROM tickets "
    "WHERE customer_id = ? ORDER BY created_at DESC, ticket_id DESC LIMIT ?")
SQL_TICKET_STATUSES = "SELECT DISTINCT status FROM tickets ORDER BY status"
SQL_INVOICES = (
    "SELECT invoice_id, billing_cycle_start, billing_cycle_end, plan_charge, usage_charge, vas_charge, "
    "tax_gst, late_fee, total_amount, due_date, payment_status FROM invoices "
    "WHERE customer_id = ? ORDER BY due_date DESC, invoice_id DESC LIMIT ?")
SQL_PAYMENTS = (
    "SELECT transaction_id, amount, payment_method, status, timestamp FROM payment_transactions "
    "WHERE invoice_id = ? AND customer_id = ? ORDER BY timestamp, transaction_id")


def _mask(msisdn):
    return "****" + str(msisdn)[-4:]


def _fact(table, pk, customer_id, content, fields, derived=None, extra=None):
    metadata = {"customer_id": int(customer_id), "concept": _CONCEPT_BY_TABLE.get(table)}
    metadata.update(fields)
    if extra:
        metadata.update(extra)
    if derived:
        metadata["derived"] = derived
    return {
        "source": "structured_sql",
        "record_id": f"{table}:{pk}",
        "dataset": table,
        "category": (_schema.get_schema(table) or {}).get("category_tag", ""),
        "score": 1.0,
        "retrieval_method": "structured_sql",
        "content": content,
        "metadata": metadata,
    }


def _to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _money(value):
    return Decimal(str(value)) if value not in (None, "") else Decimal("0")


# ---------------------------------------------------------------------------
# Intent handlers - each returns a list of facts for ONE intent
# ---------------------------------------------------------------------------
def _recharge(conn, customer, limit, as_of):
    rows = conn.execute(SQL_RECHARGES, (customer["msisdn"], limit)).fetchall()
    facts = []
    for r in rows:
        fields = {k: r[k] for k in ("recharge_id", "amount", "plan_id", "channel",
                                    "timestamp", "status", "balance_after")}
        content = (f"Recharge {r['recharge_id']} on line {_mask(customer['msisdn'])}: amount {r['amount']}, "
                   f"status {r['status']}, at {r['timestamp']}, balance after {r['balance_after']}")
        facts.append(_fact("recharge_transactions", r["recharge_id"], customer["customer_id"], content, fields))
    return facts


def _kyc(conn, customer, limit, as_of):
    cid = customer["customer_id"]
    # customer_master.kyc_status is AUTHORITATIVE
    facts = [_fact("customer_master", cid, cid,
                   f"KYC status on the customer record (authoritative): {customer['kyc_status']}",
                   {"kyc_status": customer["kyc_status"]})]
    rows = conn.execute(SQL_KYC_RECORDS, (str(cid), limit)).fetchall()
    for r in rows:
        fields = {k: r[k] for k in ("kyc_id", "kyc_type", "status", "last_updated")}
        facts.append(_fact("kyc_records", r["kyc_id"], cid,
                           f"KYC record {r['kyc_id']}: {r['kyc_type']}, status {r['status']}, "
                           f"updated {r['last_updated']}", fields))
    if not rows:
        facts.append(_fact("kyc_records", "none", cid,
                           "no kyc_records row for this customer (the customer-record KYC status above is "
                           "still the authoritative status)",
                           {"kyc_records_rows": 0, "marker": "no kyc_records row"}))
    return facts


def _subscription(conn, customer, limit, as_of):
    cid = customer["customer_id"]
    today = _to_date(as_of)
    facts = []
    for r in conn.execute(SQL_SUBSCRIPTIONS, (str(cid), limit)).fetchall():
        fields = {k: r[k] for k in ("subscription_id", "plan_id", "activation_date", "expiry_date",
                                    "status", "renewal_type", "plan_name", "price", "validity_days")}
        derived = None
        if today is not None:
            derived = {"expiry_passed": _to_date(r["expiry_date"]) < today, "as_of": today.isoformat(),
                       "note": "derived from expiry_date; the stored status is reported verbatim"}
        facts.append(_fact("subscriptions", r["subscription_id"], cid,
                           f"Subscription {r['subscription_id']}: plan {r['plan_name']} (price {r['price']}, "
                           f"{r['validity_days']} days), stored status {r['status']}, "
                           f"expiry_date {r['expiry_date']}", fields, derived=derived))
    return facts


def _tickets(conn, customer, limit, as_of):
    cid = customer["customer_id"]
    vocabulary = [row[0] for row in conn.execute(SQL_TICKET_STATUSES).fetchall()]
    facts = []
    for r in conn.execute(SQL_TICKETS, (str(cid), limit)).fetchall():
        fields = {k: r[k] for k in ("ticket_id", "category", "subcategory", "created_at",
                                    "sla_due_at", "status")}
        facts.append(_fact("tickets", r["ticket_id"], cid,
                           f"Ticket {r['ticket_id']}: {r['category']}/{r['subcategory']}, stored status "
                           f"{r['status']}, created {r['created_at']}", fields,
                           extra={"status_vocabulary": vocabulary}))
    return facts


def _invoice(conn, customer, limit, as_of):
    cid = customer["customer_id"]
    facts = []
    for r in conn.execute(SQL_INVOICES, (str(cid), limit)).fetchall():
        fields = {k: r[k] for k in ("invoice_id", "billing_cycle_start", "billing_cycle_end", "plan_charge",
                                    "usage_charge", "vas_charge", "tax_gst", "late_fee", "total_amount",
                                    "due_date", "payment_status")}
        payments = [{k: p[k] for k in ("transaction_id", "amount", "payment_method", "status", "timestamp")}
                    for p in conn.execute(SQL_PAYMENTS, (r["invoice_id"], str(cid))).fetchall()]
        success_sum = sum((_money(p["amount"]) for p in payments if p["status"] == "SUCCESS"), Decimal("0"))
        derived = None
        if r["payment_status"] in ("Unpaid", "Overdue") and success_sum >= _money(r["total_amount"]):
            derived = {"status_ledger_mismatch": True,
                       "note": "stored payment_status is unpaid/overdue but SUCCESS payments already cover "
                               "total_amount; the stored status is reported verbatim"}
        facts.append(_fact(
            "invoices", r["invoice_id"], cid,
            f"Invoice {r['invoice_id']}: total {r['total_amount']}, due {r['due_date']}, stored payment_status "
            f"{r['payment_status']}, SUCCESS payments sum {success_sum}", fields, derived=derived,
            extra={"payments": payments, "success_payments_sum": float(success_sum)}))
    return facts


_HANDLERS = {"recharge": _recharge, "kyc": _kyc, "subscription": _subscription,
             "tickets": _tickets, "invoice": _invoice}


def fetch_customer_facts(customer_id, intents, as_of=None, limit=3, db_path=DB_PATH):
    """Facts for the SESSION customer only, for each requested intent (deterministic order).

    Returns [] for an unknown customer or when nothing exists for an intent.
    `as_of` (date or ISO string) only adds metadata["derived"]["expiry_passed"] to subscriptions.
    """
    unknown = [i for i in intents if i not in _HANDLERS]
    if unknown:
        raise ValueError(f"unknown structured intent(s): {unknown}; supported: {list(INTENTS)}")
    if customer_id is None:
        return []
    conn = open_readonly(db_path)
    try:
        customer = conn.execute(SQL_CUSTOMER, (str(customer_id),)).fetchone()
        if customer is None:
            return []
        facts = []
        for intent in dict.fromkeys(intents):  # de-duplicated, order kept
            facts.extend(_HANDLERS[intent](conn, customer, limit, as_of))
        return facts
    finally:
        conn.close()


def lookup_msisdn(customer_id, db_path=DB_PATH):
    """The session customer's OWN msisdn from customer_master (None if unknown). Used by the router
    for ownership checks; the number is never taken from question text."""
    if customer_id is None:
        return None
    conn = open_readonly(db_path)
    try:
        row = conn.execute(SQL_CUSTOMER, (str(customer_id),)).fetchone()
        return row["msisdn"] if row else None
    finally:
        conn.close()
