"""
Context assembly for the answer layer (E13 Phase 9a).

assemble_context(result, max_docs=5, snippet_chars=400) -> Context

`result` is the dict returned by pipeline.run_hybrid_query. The context has three parts:

  FACTS      F1..Fn : the customer's own structured facts - id, table:pk, the human-readable line, the
             stored fields VERBATIM, and any derived flags kept apart and labelled as derived.
  DOCUMENTS  D1..Dk : the top `max_docs` retrieved documents - id, document_id, title, a cleaned snippet
             of the best chunk (document metadata header lines removed, text otherwise untouched).
  NOTICES           : codes derived from the route plan and trace - needs_identity, refuse_other_customer,
             unrecognised_personal_request, documents_are_generic, status_ledger_mismatch, expiry_passed,
             "no kyc_records row".

Facts and documents stay separate channels: nothing is merged, re-scored or ranked across them (the
retriever scores are deliberately not carried into the context).
"""

import re
from dataclasses import dataclass, field

# metadata keys on a fact that are bookkeeping, not stored record fields
_FACT_BOOKKEEPING = {"customer_id", "concept", "derived", "status_vocabulary"}

_HEADER_LINE = re.compile(
    r"^\s*(?:#|\*\*[^*]+:\*\*|(?:Document ID|Category|Department|Customer Scope|Version|Last Updated|"
    r"Source Authority|Channel)\b\s*:|-{3,}\s*$)", re.I)


@dataclass
class Context:
    facts: list = field(default_factory=list)
    documents: list = field(default_factory=list)
    notices: list = field(default_factory=list)
    route: str = ""
    outcome: str = "answer"
    refusal_reason: object = None
    as_of: object = None

    def item(self, item_id: str):
        for it in self.facts + self.documents:
            if it["id"] == item_id:
                return it
        return None

    def ids(self) -> set:
        return {it["id"] for it in self.facts + self.documents}


def flatten(obj) -> str:
    """Searchable text of a stored value: 'key=value' pairs, recursing into dicts and lists."""
    if isinstance(obj, dict):
        return " ".join(f"{k}={flatten(v)}" for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return " ".join(flatten(v) for v in obj)
    return "" if obj is None else str(obj)


def clean_snippet(content: str, snippet_chars: int) -> str:
    """Drop markdown/metadata header lines and cut at a word boundary. Text is otherwise verbatim."""
    lines = []
    for raw in (content or "").splitlines():
        if _HEADER_LINE.match(raw):
            continue
        line = re.sub(r"[#*]+", " ", raw)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    text = " ".join(lines)
    if len(text) <= snippet_chars:
        return text
    cut = text[:snippet_chars]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut


def assemble_context(result: dict, max_docs: int = 5, snippet_chars: int = 400) -> Context:
    plan = result.get("route_plan", {}) or {}
    trace = result.get("trace", {}) or {}
    blocked = result.get("blocked", []) or []

    facts = []
    for i, f in enumerate(result.get("facts", []) or [], start=1):
        md = f.get("metadata", {}) or {}
        fields = {k: v for k, v in md.items() if k not in _FACT_BOOKKEEPING}
        derived = md.get("derived")
        table, _, pk = f["record_id"].partition(":")
        text = " ".join(filter(None, [f.get("content", ""), f["record_id"], flatten(fields),
                                      ("derived: " + flatten(derived)) if derived else ""]))
        facts.append({"id": f"F{i}", "record_id": f["record_id"], "table": table, "pk": pk,
                      "line": f.get("content", ""), "fields": fields, "derived": derived, "text": text})

    documents = []
    for i, d in enumerate((result.get("documents", []) or [])[:max_docs], start=1):
        md = d.get("metadata", {}) or {}
        snippet = clean_snippet(d.get("content", ""), snippet_chars)
        title = md.get("title", "") or ""
        documents.append({"id": f"D{i}", "document_id": md.get("document_id", d.get("record_id", "")),
                          "title": title, "snippet": snippet,
                          "text": " ".join([md.get("document_id", ""), title, snippet])})

    notices = []
    outcome = plan.get("outcome", "answer")
    if outcome == "needs_identity" or "needs_identity" in blocked:
        notices.append("needs_identity")
    if outcome == "refuse_other_customer" or "refuse_other_customer" in blocked:
        notices.append("refuse_other_customer")
    if plan.get("unrecognised_personal_request") or trace.get("unrecognised_personal_request") \
            or "unrecognised_personal_request" in blocked:
        notices.append("unrecognised_personal_request")
    if result.get("documents_are_generic") or trace.get("documents_are_generic"):
        notices.append("documents_are_generic")
    if any((f["derived"] or {}).get("status_ledger_mismatch") for f in facts):
        notices.append("status_ledger_mismatch")
    if any((f["derived"] or {}).get("expiry_passed") is True for f in facts):
        notices.append("expiry_passed")
    if any(f["fields"].get("marker") == "no kyc_records row" for f in facts):
        notices.append("no kyc_records row")

    return Context(facts=facts, documents=documents, notices=notices, route=plan.get("route", ""),
                   outcome=outcome, refusal_reason=plan.get("refusal_reason") or trace.get("refusal_reason"))
