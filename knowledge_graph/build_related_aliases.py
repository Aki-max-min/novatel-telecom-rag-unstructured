"""Build the RELATED_TO alias file (E13 KG hardening, Part 2).

The corpus' ``related_ids`` mostly point at ids that do not exist (all 84 were dangling). This script resolves
the ones that can be resolved by DETERMINISTIC rules only, without editing any source document:

1. ``INC_INC_<id>``     -> the unique document matching ``^INC_C\\d\\d_INC_<id>$``      (rule ``inc_prefix``)
2. ``KB_Cnn_overview``  -> the unique document ``KB_Cnn_*`` if exactly one exists      (rule ``kb_overview_unique``)
   ``FAQ_Cnn_001`` is NEVER aliased (every category has two FAQs, so the target is ambiguous).
   Anything else stays unresolved.

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
AUDIT_FIELDS = ["source_doc", "original_target", "resolved_target", "rule", "status"]

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


def build_aliases(documents: Optional[List[Dict[str, Any]]] = None) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
    """(aliases, audit rows). Rows are in document order, then related_ids order."""
    documents = list(documents) if documents is not None else load_documents()
    canonical = {d["document_id"] for d in documents}
    aliases: Dict[str, str] = {}
    audit: List[Dict[str, str]] = []
    for document in documents:
        for target in document.get("related_ids") or []:
            if not target:
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
            })
    return dict(sorted(aliases.items())), audit


def write_files(aliases_path: Path = ALIASES_PATH, audit_path: Path = AUDIT_PATH) -> Dict[str, int]:
    aliases, audit = build_aliases()
    payload = {
        "description": "RELATED_TO target aliases: dangling related_ids resolved by deterministic rules "
                       "(inc_prefix, kb_overview_unique). FAQ_Cnn_001 is never aliased. Source documents are untouched.",
        "aliases": aliases,
    }
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
