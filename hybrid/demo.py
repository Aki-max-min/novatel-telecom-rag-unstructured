"""
End-to-end demo of the E13 grounded answer layer (extractive answerer, no LLM).

    python -m hybrid.demo        # from the repo root, in an environment with faiss + sentence-transformers

Six scenarios; each prints the answer, its sources and the notices. Customer 1042 / 1056 / 1829 are the
verified anchors used throughout the tests; as_of makes the plan-expiry answer date-aware.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(REPO_ROOT)

from answer import answer_question  # noqa: E402

SCENARIOS = [
    ("Customer 1042 asks about recharge and plan expiry (as_of 2026-10-06)",
     "Has my last recharge gone through, and when does my plan expire?", 1042, "2026-10-06"),
    ("No customer asks the DND question",
     "Can the company keep sending me promotional SMS after I've registered for DND?", None, None),
    ("Customer 1042 asks the KYC-pending and disconnection question",
     "My KYC is showing pending - does that mean my number will get disconnected, and what do I do?", 1042, None),
    ("The same question with no customer",
     "My KYC is showing pending - does that mean my number will get disconnected, and what do I do?", None, None),
    ("Customer 1829 asks whether the invoice has been paid",
     "Has my latest invoice been paid?", 1829, None),
    ("Customer 1042 asks about another customer's number",
     "What is the balance on 9756865116?", 1042, None),
]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for title, question, customer_id, as_of in SCENARIOS:
        out = answer_question(question, customer_id, as_of)
        print("=" * 100)
        print(f"{title}\nQ (customer={customer_id}, as_of={as_of}): {question}")
        print(f"\nANSWER: {out['answer']}")
        print("\nSOURCES:")
        for cid, source in out["citations"].items():
            print(f"  [{cid}] {source}")
        if not out["citations"]:
            print("  (none cited)")
        print(f"NOTICES: {out['notices'] or 'none'}   ROUTE: {out['route']}   MODE: {out['mode']}   "
              f"VERIFIED: {out['verifier']['ok']}")
    print("=" * 100)


if __name__ == "__main__":
    main()
