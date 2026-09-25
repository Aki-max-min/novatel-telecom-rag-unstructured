"""Deterministic content-concept extraction for the NovaTel knowledge graph.

Phase 2 adds a CONTENT layer on top of the Phase 1 metadata graph: telecom
concepts (services, channels, verification methods, requirements, locations) are
pulled out of each document's ``title`` and ``content``.

Method: a **curated pattern dictionary**. Every concept is a canonical name
mapped to an explicit list of case-insensitive trigger phrases. A phrase matches
only on non-alphanumeric boundaries, so ``port`` never fires inside ``portal``
and ``pan`` never fires inside ``Pan-India``. No LLM, no ML, no statistical
model, and deliberately no spaCy: the baseline has to be explainable line by
line and identical on every run. Each match records the trigger that fired and a
snippet of surrounding text, so any edge in the graph can be traced back to the
exact words that produced it.

Two passes:

1. **Mention pass** - one edge per (document, concept) pair, carrying the matched
   triggers and evidence text.
2. **Co-occurrence pass** - Service/Channel, Service/VerificationMethod and
   Service/Requirement pairs seen in the *same document*. These are heuristic,
   not asserted fact, so every such edge carries ``confidence="cooccurrence"``
   plus the document ids that support it.

Run standalone to inspect the extraction::

    python -m knowledge_graph.content_extractor              # summary
    python -m knowledge_graph.content_extractor FAQ_C01_001  # one document
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from knowledge_graph.entity_extractor import OUTPUT_DIR, load_documents, node_id

# ---------------------------------------------------------------------------
# Curated pattern dictionary
# ---------------------------------------------------------------------------
# canonical concept name -> trigger phrases (matched case-insensitively).
#
# Rules followed when adding a phrase:
#   * prefer the phrase as it actually appears in the corpus;
#   * never use a bare word that is a substring of a common unrelated word
#     ("port" would hit "portal", "pan" would hit "Pan-India" - both excluded);
#   * a phrase naming a *verification act* belongs to VerificationMethod, while
#     a phrase naming a *document the customer must produce* belongs to
#     Requirement. That is why "valid photo ID" is a Requirement and
#     "photo ID verification" is a VerificationMethod.
CONCEPT_DICTIONARY: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "Service": {
        "Mobile Number Update": (
            "update the mobile number",
            "update mobile number",
            "mobile number update",
            "update alternate number",
            "update your registered number",
            "update the registered mobile number",
            "change the registered mobile number",
            "registered mobile number",
            "contact details",
        ),
        "SIM Swap": (
            "sim swap",
            "swap the sim",
            "sim replacement",
            "replacement sim",
            "new sim card",
            "sim-status check",
        ),
        "eSIM Activation": (
            "esim",
            "e-sim",
            "esim conversion",
            "esim profile",
            "activating an esim",
        ),
        "Number Portability": (
            "number portability",
            "portability",
            "porting",
            "port number",
            "port into",
            "mnp",
            "unique porting code",
            "upc",
        ),
        "Recharge": (
            "recharge",
            "top-up",
            "top up",
            "validity extension",
        ),
        "Bill Payment": (
            "bill payment",
            "pay the bill",
            "pay your bill",
            "make a payment",
            "payment methods",
            "auto-pay",
            "autopay",
            "net banking",
            "upi mandate",
        ),
        "KYC Verification": (
            "kyc",
            "e-kyc",
            "re-kyc",
            "know your customer",
            "kyc re-verification",
        ),
        "Roaming Activation": (
            "roaming",
            "roaming pack",
            "roaming activation",
            "international roaming",
            "activate roaming",
        ),
        "Plan Change": (
            "plan change",
            "plan changes",
            "change your plan",
            "plan upgrade",
            "plan upgrades",
            "plan migration",
            "tariff change",
        ),
        "DND Activation": (
            "dnd",
            "do not disturb",
            "ucc",
            "commercial communication preference",
        ),
        "Broadband/FTTH Installation": (
            "ftth",
            "broadband connection",
            "broadband installation",
            "fibre installation",
            "fibre connection",
            "fibre-line",
            "ont",
            "home broadband",
        ),
        "Loyalty Redemption": (
            "loyalty points",
            "loyalty reward",
            "reward points",
            "redeem",
            "redeemed",
            "rewards",
        ),
        "Complaint Registration": (
            "complaint",
            "complaints",
            "grievance",
            "raise a complaint",
            "register a complaint",
            "log a complaint",
            "escalation",
        ),
        "Refund": (
            "refund",
            "refunds",
            "refunded",
            "reversal",
            "adjustment",
        ),
    },
    "Channel": {
        "My NovaTel App": (
            "my novatel app",
            "novatel app",
            "mynovatel app",
            "in-app",
            "self-care app",
        ),
        "Self-Care Portal": (
            "self-care portal",
            "selfcare portal",
            "self care portal",
            "web self-care",
            "self-care",
        ),
        "IVR": (
            "ivr",
            "interactive voice response",
        ),
        "Helpline/Call Center": (
            "helpline",
            "call centre",
            "call center",
            "customer care number",
            "contact centre",
        ),
        "WhatsApp": (
            "whatsapp",
            "whats app",
        ),
        "Website": (
            "website",
            "novatel.com",
            "web portal",
        ),
    },
    "VerificationMethod": {
        "OTP": (
            "otp",
            "one-time password",
            "one time password",
            "otp-based verification",
        ),
        "Photo ID": (
            "photo id verification",
            "id verification",
            "identity verification",
            "original id proof",
            "id proof",
        ),
        "Aadhaar": (
            "aadhaar-based",
            "aadhaar based",
            "aadhaar e-kyc",
            "aadhaar otp",
            "aadhaar verification",
        ),
        "Biometric": (
            "biometric",
            "fingerprint",
            "face unlock",
            "liveness check",
        ),
        "Video KYC": (
            "video kyc",
            "video-kyc",
            "video verification",
        ),
        "PAN": (
            "pan verification",
            "pan-based verification",
        ),
        "Email Verification": (
            "email verification",
            "verify your email",
            "email otp",
        ),
    },
    "Requirement": {
        "Valid Photo ID": (
            "valid photo id",
            "photo id",
            "photo identification",
            "government-issued proof of identity",
            "proof of identity",
        ),
        "Address Proof": (
            "address proof",
            "proof of address",
        ),
        "Aadhaar": (
            "aadhaar",
            "aadhar",
            "aadhaar card",
        ),
        "PAN": (
            # Deliberately NOT a bare "pan": that matches "Pan-India" in every
            # incident report header. No PAN-card language exists in the corpus,
            # so this concept is declared but currently unevidenced.
            "pan card",
            "permanent account number",
        ),
        "Passport": (
            "passport",
        ),
    },
    "Location": {
        "NovaTel Experience Store": (
            "novatel experience store",
            "experience store",
        ),
        "Retail Outlet": (
            # Deliberately NOT a bare "store": that would swallow every
            # "visit a store" and duplicate the Experience Store concept.
            "retail outlet",
            "retail outlets",
            "authorised retail outlet",
            "authorized retail outlet",
            "retail pos",
        ),
    },
}

#: Concept type -> mention relationship emitted from the Document.
MENTION_RELATIONSHIPS: Dict[str, str] = {
    "Service": "MENTIONS_SERVICE",
    "Channel": "MENTIONS_CHANNEL",
    "VerificationMethod": "MENTIONS_VERIFICATION",
    "Requirement": "MENTIONS_REQUIREMENT",
    "Location": "MENTIONS_LOCATION",
}

#: (from type, to type, relationship) pairs built by the co-occurrence pass.
COOCCURRENCE_RULES: Tuple[Tuple[str, str, str], ...] = (
    ("Service", "Channel", "AVAILABLE_VIA"),
    ("Service", "VerificationMethod", "REQUIRES_VERIFICATION"),
    ("Service", "Requirement", "REQUIRES_DOCUMENT"),
)

#: Fields of the document that are scanned, in this order.
SCANNED_FIELDS: Tuple[str, ...] = ("title", "content")

EVIDENCE_WINDOW = 60  # characters of context kept on each side of a match
EVIDENCE_MAX_LEN = 220


def _compile(phrase: str) -> re.Pattern:
    """Case-insensitive literal phrase, bounded by non-alphanumerics.

    Lookarounds rather than ``\\b`` because triggers contain hyphens, dots and
    slashes: ``\\b`` would fire inside ``Pan-India`` for the phrase ``pan``,
    while ``(?<![A-Za-z0-9])`` will not.
    """
    return re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(phrase) + r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


#: concept type -> concept name -> [(trigger phrase, compiled pattern), ...]
COMPILED_PATTERNS: Dict[str, Dict[str, List[Tuple[str, re.Pattern]]]] = {
    concept_type: {
        name: [(phrase, _compile(phrase)) for phrase in phrases]
        for name, phrases in concepts.items()
    }
    for concept_type, concepts in CONCEPT_DICTIONARY.items()
}


def _snippet(text: str, start: int, end: int) -> str:
    """Whitespace-collapsed context around a match, for audit trails."""
    window = text[max(0, start - EVIDENCE_WINDOW) : end + EVIDENCE_WINDOW]
    collapsed = " ".join(window.split())
    if len(collapsed) > EVIDENCE_MAX_LEN:
        collapsed = collapsed[: EVIDENCE_MAX_LEN - 3] + "..."
    return collapsed


# ---------------------------------------------------------------------------
# Context-sensitive trigger exclusion
# ---------------------------------------------------------------------------
# Same "boundary-safe matching" philosophy as the port/pan/store fixes above,
# extended to bare-word triggers that are ambiguous without surrounding
# context. Found via the Sep 2026 corpus merge: Person A's new document
# template adds a structural "### Escalation" section heading to many FAQs
# regardless of whether escalation is actually relevant, and that section's
# own prose sometimes explicitly denies an escalation applies (e.g. FAQ_C01_001:
# "...rather than a general support escalation"). A bare "escalation" trigger
# fired on both, producing a false Complaint Registration concept on a document
# about updating a phone number.
#
# Scoped narrowly to (concept_type, concept, phrase) triples that are known to
# need it, rather than applied globally, so no other trigger's behaviour
# changes. Corpus-wide check before adding this: only 2 of 30 heading-only
# matches in the whole corpus belong to a different trigger (Roaming Activation
# on two tariff documents), and neither is touched by this exclusion.
NEGATION_SENSITIVE_TRIGGERS: frozenset = frozenset(
    {
        ("Service", "Complaint Registration", "escalation"),
    }
)

#: Contrast/negation cues checked in the text immediately before a match.
#: "rather than" and "instead of" are what the corpus actually uses to deny a
#: concept applies; "not a"/"isn't a"/"is not a" cover the direct negations.
NEGATION_CUES: Tuple[str, ...] = (
    "rather than",
    "instead of",
    "not a",
    "not an",
    "isn't a",
    "is not a",
)
NEGATION_WINDOW = 60  # characters checked before the match start

_HEADING_LINE_PATTERN = re.compile(r"^#{1,6}\s*(.+?)\s*$")


def _is_negated(text: str, match_start: int) -> bool:
    """True if a negation/contrast cue appears just before the match."""
    window = text[max(0, match_start - NEGATION_WINDOW) : match_start].lower()
    return any(cue in window for cue in NEGATION_CUES)


def _is_heading_only_match(text: str, match_start: int, match_end: int) -> bool:
    """True if the match is the entire content of a markdown heading line.

    A heading like "### Escalation" is a section label the document template
    inserts structurally, not a prose assertion that the concept applies -
    distinct from the same word appearing in a sentence.
    """
    line_start = text.rfind("\n", 0, match_start) + 1
    line_end = text.find("\n", match_end)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    heading_match = _HEADING_LINE_PATTERN.match(line)
    if not heading_match:
        return False
    return heading_match.group(1).strip().lower() == text[match_start:match_end].lower()


def _is_excluded_match(
    concept_type: str, name: str, phrase: str, text: str, match: re.Match
) -> bool:
    """Context checks applied only to triggers flagged as needing them."""
    if (concept_type, name, phrase) not in NEGATION_SENSITIVE_TRIGGERS:
        return False
    return _is_negated(text, match.start()) or _is_heading_only_match(
        text, match.start(), match.end()
    )


def extract_document_concepts(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return one record per (concept type, concept) found in a single document.

    Each record carries every trigger that fired, how many times, which fields
    matched, and the evidence snippet of the first match.
    """
    found: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for field in SCANNED_FIELDS:
        text = document.get(field) or ""
        if not text:
            continue
        for concept_type, concepts in COMPILED_PATTERNS.items():
            for name, patterns in concepts.items():
                for phrase, pattern in patterns:
                    for match in pattern.finditer(text):
                        if _is_excluded_match(concept_type, name, phrase, text, match):
                            continue
                        record = found.get((concept_type, name))
                        if record is None:
                            record = {
                                "concept": name,
                                "concept_type": concept_type,
                                "document_id": document["document_id"],
                                "matched_terms": [],
                                "fields": [],
                                "match_count": 0,
                                "evidence": _snippet(text, match.start(), match.end()),
                                "evidence_field": field,
                                "evidence_span": match.group(0),
                                "evidence_offset": match.start(),
                            }
                            found[(concept_type, name)] = record
                        record["match_count"] += 1
                        if phrase not in record["matched_terms"]:
                            record["matched_terms"].append(phrase)
                        if field not in record["fields"]:
                            record["fields"].append(field)

    for record in found.values():
        record["matched_terms"] = sorted(record["matched_terms"])

    return [found[key] for key in sorted(found)]


def _concept_node(concept_type: str, name: str) -> Dict[str, Any]:
    return {
        "id": node_id(concept_type, name),
        "label": concept_type,
        "key": name,
        "properties": {
            "name": name,
            "concept_type": concept_type,
            "extraction_method": "curated_pattern_dictionary",
            "trigger_count": len(CONCEPT_DICTIONARY[concept_type][name]),
            "document_frequency": 0,  # filled in below
        },
    }


def extract_content(
    documents: Iterable[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Run both passes over the corpus.

    Returns ``nodes``, ``edges``, ``mentions`` (the raw per-document records) and
    ``stats``. Only concepts actually evidenced in the corpus become nodes; a
    declared-but-unmatched concept stays in the dictionary and is reported under
    ``concepts_without_evidence`` rather than becoming an orphan node.
    """
    documents = list(documents) if documents is not None else load_documents()

    mentions: List[Dict[str, Any]] = []
    per_document: Dict[str, Dict[str, List[str]]] = {}
    document_frequency: Dict[Tuple[str, str], int] = defaultdict(int)

    for document in documents:
        records = extract_document_concepts(document)
        mentions.extend(records)
        by_type: Dict[str, List[str]] = defaultdict(list)
        for record in records:
            by_type[record["concept_type"]].append(record["concept"])
            document_frequency[(record["concept_type"], record["concept"])] += 1
        per_document[document["document_id"]] = {
            concept_type: sorted(names) for concept_type, names in by_type.items()
        }

    # --- nodes -------------------------------------------------------------
    nodes: Dict[str, Dict[str, Any]] = {}
    for (concept_type, name), frequency in document_frequency.items():
        node = _concept_node(concept_type, name)
        node["properties"]["document_frequency"] = frequency
        nodes[node["id"]] = node

    # --- pass 1: mention edges --------------------------------------------
    edges: List[Dict[str, Any]] = []
    for record in mentions:
        edges.append(
            {
                "source": node_id("Document", record["document_id"]),
                "target": node_id(record["concept_type"], record["concept"]),
                "type": MENTION_RELATIONSHIPS[record["concept_type"]],
                "source_field": ",".join(record["fields"]),
                "properties": {
                    "confidence": "pattern_match",
                    "matched_terms": ", ".join(record["matched_terms"]),
                    "match_count": record["match_count"],
                    "evidence": record["evidence"],
                    "evidence_span": record["evidence_span"],
                    "evidence_field": record["evidence_field"],
                },
            }
        )

    # --- pass 2: co-occurrence edges --------------------------------------
    # Heuristic: two concepts in the same document. Aggregated so a pair seen in
    # several documents is one edge carrying every supporting document id.
    cooccurrence: Dict[Tuple[str, str, str], List[str]] = defaultdict(list)
    for document in documents:
        document_id = document["document_id"]
        by_type = per_document.get(document_id, {})
        for from_type, to_type, relationship in COOCCURRENCE_RULES:
            for from_name in by_type.get(from_type, []):
                for to_name in by_type.get(to_type, []):
                    key = (
                        node_id(from_type, from_name),
                        node_id(to_type, to_name),
                        relationship,
                    )
                    if document_id not in cooccurrence[key]:
                        cooccurrence[key].append(document_id)

    for (source, target, relationship), document_ids in sorted(cooccurrence.items()):
        edges.append(
            {
                "source": source,
                "target": target,
                "type": relationship,
                "source_field": "content_cooccurrence",
                "properties": {
                    "confidence": "cooccurrence",
                    "support": len(document_ids),
                    "evidence_document_id": document_ids[0],
                    "evidence_document_ids": ", ".join(sorted(document_ids)),
                    "evidence": (
                        f"co-mentioned in {len(document_ids)} document(s); "
                        f"heuristic, not an asserted fact"
                    ),
                },
            }
        )

    # --- stats -------------------------------------------------------------
    nodes_by_type: Dict[str, int] = {}
    for node in nodes.values():
        nodes_by_type[node["label"]] = nodes_by_type.get(node["label"], 0) + 1
    edges_by_type: Dict[str, int] = {}
    for edge in edges:
        edges_by_type[edge["type"]] = edges_by_type.get(edge["type"], 0) + 1

    declared = {
        (concept_type, name)
        for concept_type, concepts in CONCEPT_DICTIONARY.items()
        for name in concepts
    }
    without_evidence = sorted(
        f"{concept_type}::{name}" for concept_type, name in declared - set(document_frequency)
    )

    documents_with_content_edge = sum(1 for value in per_document.values() if value)

    stats = {
        "documents_read": len(documents),
        "documents_with_at_least_one_content_edge": documents_with_content_edge,
        "concepts_declared": len(declared),
        "concepts_with_evidence": len(nodes),
        "concepts_without_evidence": without_evidence,
        "total_mentions": len(mentions),
        "content_nodes_by_type": dict(sorted(nodes_by_type.items())),
        "content_edges_by_type": dict(sorted(edges_by_type.items())),
        "cooccurrence_edges": len(cooccurrence),
    }

    ordered_nodes = sorted(nodes.values(), key=lambda node: (node["label"], node["key"]))
    return {
        "nodes": ordered_nodes,
        "edges": edges,
        "mentions": mentions,
        "per_document": per_document,
        "stats": stats,
    }


def save_content(result: Dict[str, Any], output_dir: Path = OUTPUT_DIR) -> Path:
    """Write content_extraction.json (nodes, edges, per-document mentions)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "content_extraction.json"
    payload = {
        "extraction_method": "curated_pattern_dictionary",
        "stats": result["stats"],
        "concept_dictionary": {
            concept_type: {name: list(phrases) for name, phrases in concepts.items()}
            for concept_type, concepts in CONCEPT_DICTIONARY.items()
        },
        "per_document": result["per_document"],
        "nodes": result["nodes"],
        "edges": result["edges"],
        "mentions": result["mentions"],
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path


def concepts_for_document(document_id: str) -> Dict[str, List[str]]:
    """Convenience lookup used by the ground-truth spotcheck."""
    for document in load_documents():
        if document["document_id"] == document_id:
            records = extract_document_concepts(document)
            by_type: Dict[str, List[str]] = defaultdict(list)
            for record in records:
                by_type[record["concept_type"]].append(record["concept"])
            return {key: sorted(value) for key, value in by_type.items()}
    raise KeyError(f"document {document_id!r} not found in the corpus")


def _print_document(document_id: str) -> None:
    for document in load_documents():
        if document["document_id"] != document_id:
            continue
        print(f"=== {document_id} — extracted concepts ===")
        for record in extract_document_concepts(document):
            print(f"  [{record['concept_type']}] {record['concept']}")
            print(f"      triggers : {', '.join(record['matched_terms'])}")
            print(f"      matches  : {record['match_count']} ({', '.join(record['fields'])})")
            print(f"      evidence : {record['evidence']}")
        return
    raise KeyError(f"document {document_id!r} not found in the corpus")


def main() -> None:
    if len(sys.argv) > 1:
        _print_document(sys.argv[1])
        return

    result = extract_content()
    path = save_content(result)
    stats = result["stats"]
    print(f"documents read              : {stats['documents_read']}")
    print(f"documents with content edge : {stats['documents_with_at_least_one_content_edge']}")
    print(f"concepts declared / evidenced: {stats['concepts_declared']} / {stats['concepts_with_evidence']}")
    print("content nodes by type:")
    for label, count in stats["content_nodes_by_type"].items():
        print(f"  {label:<20}: {count}")
    print("content edges by type:")
    for edge_type, count in stats["content_edges_by_type"].items():
        print(f"  {edge_type:<22}: {count}")
    if stats["concepts_without_evidence"]:
        print(f"declared but unevidenced   : {', '.join(stats['concepts_without_evidence'])}")
    print(f"written                    : {path}")


if __name__ == "__main__":
    main()
