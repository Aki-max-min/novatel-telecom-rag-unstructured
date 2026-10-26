"""
Phase 8e probes: new sentences used to test the clause-level rule BEFORE any benchmark run.
Each probe prints its clause decomposition, kinds and route. A scan asserts that none of the
sentences appears in any JSON under hybrid/benchmark/ or ingestion/.
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from clauses import split_clauses  # noqa: E402
from router import route_query  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

PROBES = [
    # (sentence, expected route)
    ("Can I change my plan before the cycle ends?", "unstructured"),
    ("Am I allowed to transfer my balance to another number?", "unstructured"),
    ("Do I need to submit anything to update my KYC?", "unstructured"),
    ("Is it possible to merge my plan with my wife's?", "unstructured"),
    ("Do I have any open tickets?", "structured"),
    ("Is my KYC complete?", "structured"),
    ("My roaming pack shows as expired - can I get it back?", "both"),
]


class TestProbes(unittest.TestCase):

    def test_probes(self):
        results = []
        print()
        for sentence, expected in PROBES:
            plan = route_query(sentence, 1042)
            ok = plan.route == expected  # probes are specified as expected ROUTES; the outcome is printed too
            results.append(ok)
            print(f"[{'PASS' if ok else 'FAIL'}] expected={expected} got={plan.route}/{plan.outcome}  {sentence}")
            for clause, kind in split_clauses(sentence):
                print(f"        {kind:<13} {clause}")
        print(f"probes passed: {sum(results)}/{len(PROBES)}")
        self.assertTrue(all(results), f"{sum(results)}/{len(PROBES)} probes passed")

    def test_probe_sentences_are_not_in_any_benchmark_file(self):
        sentences = [s.lower() for s, _ in PROBES]
        files = (list((REPO_ROOT / "hybrid" / "benchmark").rglob("*.json"))
                 + list((REPO_ROOT / "ingestion").rglob("*.json")))
        self.assertGreater(len(files), 2)
        findings = []
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            try:
                text += "\n" + json.dumps(json.loads(text), ensure_ascii=False).lower()
            except ValueError:
                pass
            findings += [f"{path.relative_to(REPO_ROOT)}: {s}" for s in sentences if s in text]
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
