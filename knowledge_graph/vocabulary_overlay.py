"""Vocabulary overlay for the content extraction (KG fixes 3, step 1).

``knowledge_graph/vocabulary_extension.json`` holds the Gap 5 proposal: trigger phrases for concepts that are in the shared crosswalk vocabulary
(``EXTEND existing``) and for concepts that are not (``NEW``). It is PROPOSED, pending approval by the ontology owners, and it never edits the
shared ontology: new concepts exist only here (and become ``Concept`` nodes with ``source="vocabulary_extension"``), existing concepts get extra
mention triggers without any existing rule being edited.

Rules are never deleted. Whatever the acceptance check drops stays in the file under ``dropped`` (a whole concept) or ``dropped_phrases``
(one phrase), and a documented ``exclusions`` entry removes one (document, concept) pair whatever rule produced it.
The loader refuses generic template words as phrases (``outage``, ``troubleshooting``, a bare ``bill`` ...). A missing file is an empty overlay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

PACKAGE_DIR = Path(__file__).resolve().parent
OVERLAY_PATH = PACKAGE_DIR / "vocabulary_extension.json"
STATUS_EXTEND = "EXTEND existing"
STATUS_NEW = "NEW"
SOURCE = "vocabulary_extension"


@dataclass
class Overlay:
    raw: Dict[str, Any] = field(default_factory=lambda: {"concepts": [], "exclusions": [], "dropped": {}, "dropped_phrases": {}})
    status: str = ""
    triggers: Dict[str, List[str]] = field(default_factory=dict)     # active concept -> active phrases, proposal order
    new_concepts: List[str] = field(default_factory=list)            # active NEW concepts, proposal order
    excluded: Set[Tuple[str, str]] = field(default_factory=set)      # (document_id, concept)
    narrowed: Dict[str, List[str]] = field(default_factory=dict)     # concept -> phrases narrowed for a documented wrong sense (KG fixes 4)
    generic_words: List[str] = field(default_factory=list)


def _shared_vocabulary() -> Set[str]:
    from knowledge_graph.concept_bridge import concept_vocabulary, load_crosswalk  # lazy: concept_bridge imports graph_builder

    return set(concept_vocabulary(load_crosswalk()))


def load_overlay(path: Optional[Path] = None) -> Overlay:
    path = Path(OVERLAY_PATH if path is None else path)
    if not path.exists():
        return Overlay()
    return overlay_from_raw(json.loads(path.read_text(encoding="utf-8")))


def overlay_from_raw(raw: Dict[str, Any]) -> Overlay:
    """Validate and normalise an overlay payload (same checks for the file and for the acceptance run)."""
    shared = _shared_vocabulary()
    generic = [w.lower() for w in raw.get("generic_template_words", [])]
    dropped = dict(raw.get("dropped", {}))
    dropped_phrases = dict(raw.get("dropped_phrases", {}))
    narrowed_phrases = dict(raw.get("narrowed_phrases", {}))

    seen = set()
    triggers: Dict[str, List[str]] = {}
    new_concepts: List[str] = []
    for entry in raw.get("concepts", []):
        name, status, phrases = entry["concept"], entry.get("status"), entry.get("trigger_phrases", [])
        if name in seen:
            raise ValueError(f"duplicate overlay concept: {name}")
        seen.add(name)
        if status == STATUS_EXTEND:
            if name not in shared:
                raise ValueError(f"EXTEND existing names a concept that is not in the shared vocabulary: {name}")
        elif status == STATUS_NEW:
            if name in shared:
                raise ValueError(f"NEW concept shadows a shared-vocabulary concept: {name}")
        else:
            raise ValueError(f"unknown status {status!r} for {name}")
        for phrase in phrases:
            if not isinstance(phrase, str) or not phrase.strip():
                raise ValueError(f"empty phrase for {name}")
            if phrase.lower() in generic:
                raise ValueError(f"generic template word refused as a trigger phrase: {phrase!r} ({name})")
        for phrase, info in narrowed_phrases.get(name, {}).items():
            if phrase not in phrases:
                raise ValueError(f"narrowed phrase {phrase!r} is not a trigger phrase of {name}")
            if not (info or {}).get("reason"):
                raise ValueError(f"narrowed phrase {phrase!r} ({name}) needs a documented reason")
        if name in dropped:
            continue
        gone = set(dropped_phrases.get(name, {})) | set(narrowed_phrases.get(name, {}))
        active = [p for p in phrases if p not in gone]
        if active:
            triggers[name] = active
            if status == STATUS_NEW:
                new_concepts.append(name)

    known = shared | seen
    excluded = set()
    for e in raw.get("exclusions", []):
        if e["concept"] not in known:
            raise ValueError(f"exclusion names an unknown concept: {e['concept']}")
        excluded.add((e["document_id"], e["concept"]))
    for name in narrowed_phrases:
        if name not in seen:
            raise ValueError(f"narrowed_phrases names an unknown overlay concept: {name}")
    return Overlay(raw=raw, status=raw.get("status", ""), triggers=triggers, new_concepts=new_concepts,
                   excluded=excluded, generic_words=generic, narrowed={k: list(v) for k, v in narrowed_phrases.items()})
