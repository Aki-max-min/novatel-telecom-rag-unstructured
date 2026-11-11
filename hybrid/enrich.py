"""Deterministic query enrichment for the FAISS search (KG fixes 2, step 4). Our own module; nothing is imported from Person A's code.

For every shared-vocabulary concept recognised in the question, the enriched text appends the concept's canonical name and then
synonyms taken ONLY from vocabulary that already exists in this repository:

  * the keywords of ``query_gate.KEYWORD_CONCEPT_MAP`` that point at the concept, and
  * the trigger phrases of the document-side services that ``concept_bridge.SERVICE_CONCEPT_MAPPING`` maps to the concept
    (``content_extractor.CONCEPT_DICTIONARY``).

Rules: at most ``MAX_APPENDED_TERMS`` (6) appended terms in total - canonical names first (in order of appearance in the question),
then synonyms round-robin across the recognised concepts; a term already present in the question is never appended; the original
words are never removed or reordered (the terms are appended after them); nothing recognised -> the enriched text IS the question.

Only the FAISS candidate search may use the enriched text. The CrossEncoder, the gate, the router and the structured parser always get
the ORIGINAL question (``pipeline.run_hybrid_query``). Enabled by ``pipeline.ENRICH_ENABLED`` (default False).

Difference from Person A's ``SemanticLayer.normalise_query`` (compared in docs/E13_kg_fixes2.md): hers uses ONE concept (the gate's hint)
and appends the concept name plus the names of the document categories the crosswalk links to it, without a cap, and it lives in her
pipeline; ours recognises every concept in the question, appends the name plus vocabulary synonyms (no category names), caps at 6,
and is a separate switchable module in the hybrid pipeline.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from knowledge_graph.concept_bridge import SERVICE_CONCEPT_MAPPING  # noqa: E402
from knowledge_graph.content_extractor import CONCEPT_DICTIONARY  # noqa: E402
from query_gate import CONCEPT_VOCABULARY, KEYWORD_CONCEPT_MAP  # noqa: E402
from textmatch import find_term  # noqa: E402

MAX_APPENDED_TERMS = 6


def _recognition_terms(concept: str) -> List[str]:
    terms = [concept.lower()]
    terms += [k for k, v in KEYWORD_CONCEPT_MAP.items() if v == concept]
    terms += [s.lower() for s, c in SERVICE_CONCEPT_MAPPING.items() if c == concept]
    return terms


def _synonyms(concept: str) -> List[str]:
    out = [k for k, v in KEYWORD_CONCEPT_MAP.items() if v == concept]
    for service, mapped in SERVICE_CONCEPT_MAPPING.items():
        if mapped == concept:
            out += list(CONCEPT_DICTIONARY["Service"].get(service, ()))
    return out


def _present(term: str, lowered: str) -> bool:
    return term.lower() in lowered or find_term(lowered, [term]) is not None


def enrich_query(question: Optional[str]) -> Tuple[Optional[str], Dict[str, Any]]:
    """(enriched_text, trace). ``trace`` = {"concepts": [...], "appended": [...], "enriched": bool}. Never raises."""
    empty = {"concepts": [], "appended": [], "enriched": False}
    if not isinstance(question, str) or not question.strip():
        return question, empty
    lowered = question.lower()

    recognised = []                                   # (position, concept)
    for concept in CONCEPT_VOCABULARY:
        positions = [m.start() for t in _recognition_terms(concept) for m in [find_term(lowered, [t])] if m]
        if positions:
            recognised.append((min(positions), concept))
    recognised.sort()
    concepts = [c for _, c in recognised]
    if not concepts:
        return question, empty

    appended: List[str] = []
    seen = set()

    def add(term: str) -> bool:
        if len(appended) >= MAX_APPENDED_TERMS or term.lower() in seen or _present(term, lowered):
            return False
        seen.add(term.lower())
        appended.append(term)
        return True

    for concept in concepts:
        add(concept)
    queues = [[s for s in _synonyms(c)] for c in concepts]
    while len(appended) < MAX_APPENDED_TERMS and any(queues):
        for queue in queues:
            while queue and not add(queue.pop(0)):
                pass
            if len(appended) >= MAX_APPENDED_TERMS:
                break

    text = question + (" " + " ".join(appended) if appended else "")
    return text, {"concepts": concepts, "appended": appended, "enriched": bool(appended)}
