"""
Hybrid decomposition + parser-friendly structured rewriting.

A 421M-parameter classifier (Laya) decides the ROUTE; it cannot write text. For a
hybrid query this separate step -- an Ollama instruct model, kept independent of
the router -- produces two sub-queries:

    structured   : a lookup the EXISTING structured parser/retriever can execute
                   ("Show invoices for customer 1025", "How many tickets have
                   status Open?")
    unstructured : a standalone natural-language question for the document index
                   (customer-specific details removed)

The structured sub-query is VALIDATED against structured/query_parser.parse_query
(thin call, parser unchanged). The parser is a first-substring-match keyword
rule set with known quirks (e.g. "postpaid" contains "paid" -> payment_transactions),
so an LLM-written sub-query is accepted only if it parses to a resolved table AND
that table is the one the LLM said it was targeting. Otherwise deterministic
templates built from the original query are tried; if none parses, the structured
half is recorded as unexecutable (`structured_parse_ok=False`) and the system
degrades to the document half -- it never invents a lookup.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from query_router.base import parse_json_object

ROOT = Path(__file__).resolve().parents[1]
STRUCTURED_DIR = ROOT / "structured"

CUSTOMER_RE = re.compile(r"customer\s*(?:id|no\.?|number)?\s*#?\s*(\d{4,})", re.I)

# entity cue in the question -> a phrase the parser's KEYWORD_TABLE_MAP resolves to the intended table
TEMPLATE_ENTITY = [
    (r"\binvoice|\bbill", "invoices", "invoices"),
    (r"\bticket|\bcomplaint|\bgrievance", "tickets", "tickets"),
    (r"\brecharge|\btop-?up", "recharge transactions", "recharge_transactions"),
    (r"\bkyc", "kyc records", "kyc_records"),
    (r"\bporting|\bport request|\bport\b", "porting requests", "porting_requests"),
    (r"\bsim\b|\bsims\b", "sim inventory", "sim_inventory"),
    (r"\bfraud", "fraud cases", "fraud_cases"),
    (r"\bescalation", "escalation cases", "escalation_cases"),
    (r"\border", "orders", "orders"),
    (r"\boutage|\bsite", "network sites", "network_sites"),
    (r"\broaming", "roaming usage", "roaming_usage"),
    (r"\bsubscription|\bplan\b", "subscriptions", "subscriptions"),
    (r"\bpayment", "payment transactions", "payment_transactions"),
]
STATUS_WORDS = ["Overdue", "Unpaid", "Paid", "Open", "Closed", "InProgress", "Pending", "Expired", "Failed",
                "Active", "Suspended", "Blocked", "Rejected", "Accepted", "Cancelled", "Investigating",
                "Resolved", "Outage", "Inactive"]
STATUS_ALIAS = {"in progress": "InProgress", "under investigation": "Investigating", "failed": "FAILED",
                "success": "SUCCESS", "refunded": "REFUNDED"}

SYSTEM = """You split a telecom customer question into two independent sub-queries. Output ONE JSON object only.

"structured": a short lookup for a SQL database, or null if the question needs no database record. It must follow
  one of these forms so a rule-based parser can run it:
    "Show <table words> for customer <id>"            e.g. "Show invoices for customer 1025"
    "What is customer <id>'s <field>?"                e.g. "What is customer 1097's KYC status?"
    "How many <table words> have status <Status>?"    e.g. "How many tickets have status Open?"
    "List all <table words> with status <Status>"     e.g. "List all invoices with status Overdue"
  Use table words such as: invoices, tickets, recharge transactions, kyc records, subscriptions, porting requests,
  sim inventory, fraud cases, escalation cases, orders, network sites, roaming usage, payment transactions.
  Do NOT use the words "plan", "account", "profile" or "postpaid" in it unless that is the table you want.
"structured_table": the database table that sub-query targets.
"unstructured": a standalone natural-language question about the POLICY, PROCEDURE or REGULATION part of the
  question, with every customer id and customer-specific detail removed.

Examples:
Q: Customer 1025 has an overdue invoice. What late-payment rules apply to them?
{"structured": "Show invoices for customer 1025", "structured_table": "invoices", "unstructured": "What are the late payment rules for an overdue invoice?"}
Q: How many support tickets are open, and what is the standard escalation timeline for them?
{"structured": "How many tickets have status Open?", "structured_table": "tickets", "unstructured": "What is the standard escalation timeline for unresolved complaints?"}
"""


class HybridDecomposer:
    def __init__(self, model: str = "qwen2.5:7b-instruct"):
        self.model = model
        if str(STRUCTURED_DIR) not in sys.path:
            sys.path.insert(0, str(STRUCTURED_DIR))

    # -- parser validation -------------------------------------------------
    @staticmethod
    def _parse(sub_query: str) -> dict:
        from query_parser import parse_query
        return parse_query(sub_query)

    def _executable(self, sub_query: str, expect_table: str | None = None) -> tuple[bool, dict]:
        parsed = self._parse(sub_query)
        ok = parsed.get("table") is not None and parsed.get("method") not in (None, "exact_filter_unresolved")
        if ok and expect_table and parsed["table"] != expect_table:
            return False, parsed
        return ok, parsed

    # -- deterministic templates ---------------------------------------------
    def template_candidates(self, query: str) -> list[tuple[str, str]]:
        """[(sub_query, expected_table)] built from the original query (no LLM)."""
        low = query.lower()
        cust = CUSTOMER_RE.search(query)
        cands = []
        for pattern, words, table in TEMPLATE_ENTITY:
            if not re.search(pattern, low):
                continue
            if cust:
                cands.append((f"Show {words} for customer {cust.group(1)}", table))
                if table == "customer_master":
                    cands.append((f"What is customer {cust.group(1)}'s status?", table))
            else:
                status = next((s for s in STATUS_WORDS if re.search(rf"\b{s.lower()}\b", low)), None)
                for alias, canon in STATUS_ALIAS.items():
                    if alias in low:
                        status = canon if status is None else status
                if status:
                    if re.search(r"how many|count|number of", low):
                        cands.append((f"How many {words} have status {status}?", table))
                    else:
                        cands.append((f"List all {words} with status {status}", table))
        if cust and not cands:
            cands.append((f"What is customer {cust.group(1)}'s status?", "customer_master"))
        return cands

    def rewrite_for_parser(self, query: str) -> dict:
        """Parser-friendly structured form of a query, or {"structured": None}. Tries the LLM first, then templates."""
        notes = []
        llm = self._call_llm(query, notes)
        if llm and llm.get("structured"):
            ok, parsed = self._executable(llm["structured"], llm.get("structured_table"))
            if ok:
                return {"structured": llm["structured"], "parsed": parsed, "method": "llm", "notes": notes}
            notes.append(f"LLM structured sub-query not executable: {llm['structured']!r} -> parsed table={parsed.get('table')!r}")
        for sq, table in self.template_candidates(query):
            ok, parsed = self._executable(sq, table)
            if ok:
                notes.append(f"used rule template: {sq!r}")
                return {"structured": sq, "parsed": parsed, "method": "rule_template", "notes": notes}
        notes.append("no executable structured sub-query could be produced")
        return {"structured": None, "parsed": None, "method": "none", "notes": notes}

    # -- LLM -----------------------------------------------------------------
    def _call_llm(self, query: str, notes: list) -> dict | None:
        try:
            import ollama
            reply = ollama.chat(
                model=self.model,
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Q: {query}"}],
                format="json", options={"temperature": 0, "seed": 42},
            )
            return parse_json_object(reply["message"]["content"])
        except Exception as exc:  # noqa: BLE001
            notes.append(f"decomposer LLM unavailable/unparseable: {str(exc)[:120]}")
            return None

    def decompose(self, query: str) -> dict:
        """Full hybrid decomposition. Never raises."""
        notes: list = []
        llm = self._call_llm(query, notes)

        structured_sq, parsed, method = None, None, "none"
        if llm and llm.get("structured"):
            ok, parsed = self._executable(llm["structured"], llm.get("structured_table"))
            if ok:
                structured_sq, method = llm["structured"], "llm"
            else:
                notes.append(f"LLM structured sub-query not executable by the parser: {llm['structured']!r}")
        if structured_sq is None:
            for sq, table in self.template_candidates(query):
                ok, parsed = self._executable(sq, table)
                if ok:
                    structured_sq, method = sq, "rule_template"
                    notes.append(f"fell back to rule template: {sq!r}")
                    break

        unstructured_sq = None
        if llm and isinstance(llm.get("unstructured"), str) and llm["unstructured"].strip():
            unstructured_sq = llm["unstructured"].strip()
        used_original = unstructured_sq is None
        if used_original:
            unstructured_sq = CUSTOMER_RE.sub("a customer", query)
            notes.append("unstructured sub-query: LLM gave none; used the original query with the customer id masked")

        return {
            "structured": structured_sq,
            "unstructured": unstructured_sq,
            "structured_parse_ok": structured_sq is not None,
            "structured_parsed": parsed if structured_sq else None,
            "structured_method": method,
            "unstructured_from_llm": not used_original,
            "notes": notes,
        }
