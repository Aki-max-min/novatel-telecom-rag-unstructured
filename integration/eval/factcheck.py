"""
Deterministic structured-fact checker. No LLM judge: scans a generated
answer for citations into structured evidence, then exact-matches any
number/ID/status/count token in the citing sentence against that evidence
record's actual metadata values.

Heuristic, disclosed as such: claim extraction is sentence-plus-citation
based (regex), not full NLU. It catches "the answer cited [E2] and said a
number/status that isn't actually in E2's record" -- it does not attempt
to parse arbitrary natural-language claims.
"""

import re

_CITATION_RE = re.compile(r"\[(E\d+)\]")
_TOKEN_RE = re.compile(r"\b[\w][\w.\-/]*\b")

_STATUS_WORDS = {
    "active", "inactive", "suspended", "overdue", "paid", "pending",
    "failed", "success", "resolved", "open", "closed", "expired",
}


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _record_value_tokens(metadata: dict) -> set[str]:
    """Flatten a structured record's metadata into a set of lowercased,
    comparable string tokens (numbers, ids, statuses, dates as given)."""
    tokens = set()
    for value in metadata.values():
        if value is None:
            continue
        text = str(value).strip().lower()
        if not text:
            continue
        tokens.add(text)
        for sub_token in _TOKEN_RE.findall(text):
            tokens.add(sub_token.lower())
    return tokens


def _claim_tokens(sentence: str) -> set[str]:
    """Extract candidate factual tokens (numbers, status words, ids) from
    one sentence of the generated answer."""
    tokens = set()
    for raw in _TOKEN_RE.findall(sentence):
        token = raw.lower()
        if token in _STATUS_WORDS:
            tokens.add(token)
        elif any(ch.isdigit() for ch in token):
            tokens.add(token)
    return tokens


def check_structured_claims(answer: str, evidence: list[dict]) -> dict:
    """
    answer: the generated answer text (expects [Ek] citation markers).
    evidence: the context_builder evidence list (each entry has "id",
        "source", "metadata", etc. -- pipeline.run_query()'s "evidence"
        field is exactly this list).

    Returns {"checked_claims": int, "unsupported_claims": int,
             "mismatches": [...]} -- deterministic, no LLM involved.
    """
    evidence_by_id = {item["id"]: item for item in evidence}
    structured_ids = {
        item["id"] for item in evidence if item.get("source") == "structured"
    }

    checked = 0
    mismatches = []

    for sentence in _split_sentences(answer):
        cited_ids = set(_CITATION_RE.findall(sentence))
        structured_cited = cited_ids & structured_ids
        if not structured_cited:
            continue

        claim_tokens = _claim_tokens(sentence)
        if not claim_tokens:
            continue

        checked += 1
        supported = False
        for evidence_id in structured_cited:
            record_metadata = evidence_by_id[evidence_id].get("metadata", {}) or {}
            record_tokens = _record_value_tokens(record_metadata)
            if claim_tokens & record_tokens:
                supported = True
                break

        if not supported:
            mismatches.append({
                "sentence": sentence,
                "cited_evidence_ids": sorted(structured_cited),
                "claim_tokens": sorted(claim_tokens),
            })

    return {
        "checked_claims": checked,
        "unsupported_claims": len(mismatches),
        "mismatches": mismatches,
    }
