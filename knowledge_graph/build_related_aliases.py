"""Build the RELATED_TO alias file (E13 KG hardening, Part 2).

The corpus' ``related_ids`` mostly point at ids that do not exist (all 84 were dangling). This script resolves
the ones that can be resolved by DETERMINISTIC rules only, without editing any source document:

1. ``INC_INC_<id>``     -> the unique document matching ``^INC_C\\d\\d_INC_<id>$``      (rule ``inc_prefix``)
2. ``KB_Cnn_overview``  -> the unique document ``KB_Cnn_*`` if exactly one exists      (rule ``kb_overview_unique``)
   ``FAQ_Cnn_001`` is NEVER aliased by default (every category has two FAQs, so the target is ambiguous).
   Anything else stays unresolved.
3. ``FAQ_Cnn_001``      -> EVERY FAQ document of category Cnn          (rule ``faq_placeholder_all_in_category``)
   ASSUMPTION (KG fixes 2, step 3): "001" is a placeholder for the category's own FAQs. Off unless ``RESOLVE_FAQ_PLACEHOLDER`` is True,
   which is decided by the pre-declared dev-set rule in docs/E13_kg_fixes2.md. The ``FAQ_Cnn_*`` -> ``KB_Cnn_overview`` links in
   C01, C10, C11, C12, C14, C15, C24, C27 stay unresolved: no such document exists and none is invented.

Outputs (both deterministic, byte-identical across builds):

* ``knowledge_graph/related_id_aliases.json``     {"aliases": {original_target: real_document_id}, ...}
* ``knowledge_graph/related_id_alias_audit.csv``  source_doc, original_target, resolved_target, rule, status

The entity/relationship extractors apply the alias file when it exists. Rebuild with::

    python -m knowledge_graph.build_related_aliases
    python -m knowledge_graph.graph_builder
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from knowledge_graph.entity_extractor import load_documents

PACKAGE_DIR = Path(__file__).resolve().parent
ALIASES_PATH = PACKAGE_DIR / "related_id_aliases.json"
AUDIT_PATH = PACKAGE_DIR / "related_id_alias_audit.csv"
AUDIT_FIELDS = ["source_doc", "original_target", "resolved_target", "rule", "status", "note"]

#: KG fixes 2, step 3: resolve FAQ_Cnn_001 placeholders to all FAQs of the category (an ASSUMPTION, see module docstring).
RESOLVE_FAQ_PLACEHOLDER = True
FAQ_PLACEHOLDER_RULE = "faq_placeholder_all_in_category"
FAQ_PLACEHOLDER_NOTE = "ASSUMPTION: 001 is a placeholder for the category's own FAQs; resolved to every FAQ document of that category"
_FAQ_PLACEHOLDER = re.compile(r"^FAQ_(C\d\d)_001$")

_INC_PREFIX = re.compile(r"^INC_(INC_\d{4}_\d{4})$")
_KB_OVERVIEW = re.compile(r"^KB_(C\d\d)_overview$")


def resolve_target(target: str, canonical_ids: Iterable[str]) -> Tuple[Optional[str], str]:
    """(resolved_id or None, rule name). A target that already exists needs no alias (rule ``canonical``)."""
    ids = sorted(canonical_ids)
    if target in ids:
        return target, "canonical"
    m = _INC_PREFIX.match(target)
    if m:
        pattern = re.compile(rf"^INC_C\d\d_{re.escape(m.group(1))}$")
        found = [i for i in ids if pattern.match(i)]
        return (found[0], "inc_prefix") if len(found) == 1 else (None, "inc_prefix_not_unique")
    m = _KB_OVERVIEW.match(target)
    if m:
        found = [i for i in ids if i.startswith(f"KB_{m.group(1)}_")]
        return (found[0], "kb_overview_unique") if len(found) == 1 else (None, "kb_overview_not_unique")
    if re.match(r"^FAQ_C\d\d_001$", target):
        return None, "faq_ambiguous_never_aliased"
    return None, "no_rule"


def build_aliases(documents: Optional[List[Dict[str, Any]]] = None, faq_placeholder: Optional[bool] = None, with_multi: bool = False):
    """(aliases, audit rows) - plus the one-to-many ``multi_aliases`` as a third value when ``with_multi``.
    Rows are in document order, then related_ids order. ``faq_placeholder`` None means the module switch."""
    documents = list(documents) if documents is not None else load_documents()
    faq_placeholder = RESOLVE_FAQ_PLACEHOLDER if faq_placeholder is None else faq_placeholder
    canonical = {d["document_id"] for d in documents}
    faqs_by_category: Dict[str, List[str]] = {}
    for d in documents:
        if d["document_id"].startswith("FAQ_") and d.get("category"):
            faqs_by_category.setdefault(d["category"], []).append(d["document_id"])
    aliases: Dict[str, str] = {}
    multi: Dict[str, List[str]] = {}
    audit: List[Dict[str, str]] = []
    for document in documents:
        for target in document.get("related_ids") or []:
            if not target:
                continue
            placeholder = _FAQ_PLACEHOLDER.match(target)
            if faq_placeholder and placeholder and target not in canonical and faqs_by_category.get(placeholder.group(1)):
                ids = sorted(faqs_by_category[placeholder.group(1)])
                multi[target] = ids
                audit.append({"source_doc": document["document_id"], "original_target": target, "resolved_target": ";".join(ids),
                              "rule": FAQ_PLACEHOLDER_RULE, "status": "resolved", "note": FAQ_PLACEHOLDER_NOTE})
                continue
            resolved, rule = resolve_target(target, canonical)
            if resolved is not None and resolved != target:
                aliases[target] = resolved
            audit.append({
                "source_doc": document["document_id"],
                "original_target": target,
                "resolved_target": resolved or "",
                "rule": rule,
                "status": "resolved" if resolved else "unresolved",
                "note": "",
            })
    if with_multi:
        return dict(sorted(aliases.items())), audit, dict(sorted(multi.items()))
    return dict(sorted(aliases.items())), audit


def write_files(aliases_path: Path = ALIASES_PATH, audit_path: Path = AUDIT_PATH) -> Dict[str, int]:
    aliases, audit, multi = build_aliases(with_multi=True)
    payload = {
        "description": "RELATED_TO target aliases: dangling related_ids resolved by deterministic rules "
                       "(inc_prefix, kb_overview_unique). FAQ_Cnn_001 is never aliased. Source documents are untouched.",
        "aliases": aliases,
    }
    if multi:
        payload["description"] = ("RELATED_TO target aliases: dangling related_ids resolved by deterministic rules (inc_prefix, "
                                  "kb_overview_unique) and, in multi_aliases, FAQ_Cnn_001 -> every FAQ of category Cnn "
                                  "(rule faq_placeholder_all_in_category, an ASSUMPTION). Source documents are untouched.")
        payload["multi_aliases"] = multi
    aliases_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    with audit_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(audit)
    resolved = sum(r["status"] == "resolved" for r in audit)
    return {"related_ids": len(audit), "resolved": resolved, "unresolved": len(audit) - resolved,
            "distinct_aliases": len(aliases)}


def main() -> None:
    counts = write_files()
    print("===== RELATED_TO ALIASES =====")
    for name, value in counts.items():
        print(f"{name:<16}: {value}")
    print(f"written: {ALIASES_PATH}")
    print(f"written: {AUDIT_PATH}")


if __name__ == "__main__":
    main()
