"""Wrong-sense judgements of the vocabulary-overlay matches (KG fixes 4). Writes docs/E13_kg_fixes4_judgements.csv.

Every (concept, phrase, document) match of the ten concepts kept by KG fixes 3 is listed before (the KG fixes 3 phrase set) and after (the active overlay),
with the snippet and a judgement: *correct sense*, *wrong sense* or *unsure*. The judgements are a person's reading of the snippet with its sentence and the
document title (here: mine), recorded below in ``WRONG`` and ``UNSURE``; every other match is *correct sense*. Retrieval metrics play no part.
They are listed so that anyone can check and overrule them; the test ``test_vocabulary_judgements`` ties the table to the overlay.

    python -m knowledge_graph.judge_overlay_matches
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from knowledge_graph import content_extractor as ce
from knowledge_graph import vocabulary_overlay as vo
from knowledge_graph.entity_extractor import load_documents

REPO_ROOT = Path(__file__).resolve().parent.parent
TABLE = REPO_ROOT / "docs" / "E13_kg_fixes4_judgements.csv"
COLUMNS = ["concept", "phrase", "doc_id", "judgement", "before", "after", "action", "snippet"]

#: Phrases added by KG fixes 4 (not part of the KG fixes 3 state).
ADDED = {("Account Closure & Deactivation", p) for p in ("permanently deactivate", "deactivated for non-payment", "Deactivated Connection")}
#: Narrowed phrases that were REPLACED by a more specific phrase (the others were removed).
REPLACED = {("Account Closure & Deactivation", "deactivate"), ("Account Closure & Deactivation", "deactivated")}
#: Concepts dropped by the acceptance rule in the KG fixes 3 state (not judged).
DROPPED_IN_FIXES3 = {"Billing & Invoices", "Enterprise & Business Services", "International Calling & ISD"}

A = "Account Closure & Deactivation"
WRONG: Dict[Tuple[str, str, str], str] = {
    (A, "deactivate", "FAQ_C10_019"): "deactivating a Value Added Service ('deactivate any you did not authorise'), not closing an account",
    (A, "deactivate", "SOP_C05_SIM_REPLACEMENT"): "'deactivate old SIM' in a SIM replacement, not closing an account",
    (A, "deactivate", "SOP_C10_VAS_DISPUTE"): "'Deactivate the VAS immediately' in a VAS dispute, not closing an account",
    (A, "deactivate", "TRN_001"): "'deactivate the service' in a VAS refund example, not closing an account",
    (A, "deactivated", "EML_001"): "'We have also deactivated the service' after a refund, not a closed account",
    (A, "deactivated", "MAN_ESIM_001"): "'The physical SIM is deactivated automatically' when an eSIM is activated, not a closed account",
    ("Connectivity Troubleshooting", "Airplane Mode", "SOP_C13_APP_ACCESS_ISSUES"):
        "'device is not on Airplane Mode' is an OTP precondition in an app-login SOP, not connectivity troubleshooting",
}
UNSURE: Dict[Tuple[str, str, str], str] = {
    ("Device Compatibility", "VoLTE", "REL_2026_06"):
        "a network release note on VoLTE band expansion: about the network side, only indirectly about which devices work",
}


def _matches(documents, triggers: Dict[str, List[str]], excluded) -> Dict[Tuple[str, str, str], str]:
    out = {}
    for concept, phrases in triggers.items():
        for phrase in phrases:
            pattern = ce._compile(phrase)
            for d in documents:
                if (d["document_id"], concept) in excluded:
                    continue
                text = ce.body_text(d)
                m = pattern.search(text)
                if m:
                    out[(concept, phrase, d["document_id"])] = " ".join(text[max(0, m.start() - 110): m.end() + 90].split())
    return out


def build_rows() -> List[Dict[str, str]]:
    documents = load_documents()
    overlay = vo.load_overlay()
    raw = overlay.raw
    dropped_now = set(raw.get("dropped", {}))
    kept_in_fixes3 = [c["concept"] for c in raw["concepts"] if c["concept"] not in DROPPED_IN_FIXES3]
    before_triggers = {c["concept"]: [p for p in c["trigger_phrases"] if (c["concept"], p) not in ADDED]
                       for c in raw["concepts"] if c["concept"] in kept_in_fixes3}
    before = _matches(documents, before_triggers, overlay.excluded)
    after = _matches(documents, overlay.triggers, overlay.excluded)
    rows = []
    for key in sorted(set(before) | set(after), key=lambda k: (kept_in_fixes3.index(k[0]) if k[0] in kept_in_fixes3 else 99, k[1].lower(), k[2])):
        concept, phrase, doc = key
        judgement = "wrong sense" if key in WRONG else "unsure" if key in UNSURE else "correct sense"
        if key in before and key in after:
            action = "unchanged"
        elif key in after:
            action = "replacement phrase"
        elif concept in dropped_now:
            action = "concept dropped by rule (b)" if phrase not in overlay.narrowed.get(concept, []) else _narrow_action(concept, phrase)
        else:
            action = _narrow_action(concept, phrase)
        rows.append({"concept": concept, "phrase": phrase, "doc_id": doc, "judgement": judgement,
                     "before": "yes" if key in before else "no", "after": "yes" if key in after else "no",
                     "action": action, "snippet": before.get(key) or after[key]})
    return rows


def _narrow_action(concept: str, phrase: str) -> str:
    return "phrase narrowed" if (concept, phrase) in REPLACED else "phrase removed"


def summary(rows: List[Dict[str, str]]) -> Dict[str, int]:
    return {"matches_before": sum(r["before"] == "yes" for r in rows), "matches_after": sum(r["after"] == "yes" for r in rows),
            "wrong_before": sum(r["judgement"] == "wrong sense" and r["before"] == "yes" for r in rows),
            "wrong_after": sum(r["judgement"] == "wrong sense" and r["after"] == "yes" for r in rows),
            "unsure_before": sum(r["judgement"] == "unsure" and r["before"] == "yes" for r in rows),
            "unsure_after": sum(r["judgement"] == "unsure" and r["after"] == "yes" for r in rows)}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = build_rows()
    with TABLE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary(rows)))
    for r in rows:
        if r["action"] != "unchanged" or r["judgement"] != "correct sense":
            print(f"{r['judgement']:<14} {r['before']}->{r['after']} {r['action']:<28} {r['concept']} | {r['phrase']!r} | {r['doc_id']}")
    print("written", TABLE)


if __name__ == "__main__":
    main()
