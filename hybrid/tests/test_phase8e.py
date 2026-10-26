"""
Phase 8e tests for the clause-level analysis (hybrid/clauses.py). Every sentence is NEW; a scan asserts
none appears in any JSON under hybrid/benchmark/ or ingestion/. A second scan fails on any control
character (for example a literal backspace) in any .py file under hybrid/.
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from clauses import ASSERTION, HYPOTHETICAL, POLICY, STATUS_QUERY, split_clauses  # noqa: E402
from query_gate import classify_query  # noqa: E402
from router import route_query  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
HYBRID_DIR = REPO_ROOT / "hybrid"

BOTH = [
    "My last top-up failed - what should I do next?",
    "My invoice shows unpaid but I already paid, how do I fix it?",
    "My ticket is still open. If it stays open for a week, what happens?",
]
STRUCTURED = ["Did my last payment succeed?"]
UNSTRUCTURED = [
    "If my recharge fails, how long until the money is refunded?",
    "What happens if I change my plan mid-cycle?",
    "When I top up twice, do offers stack?",
    "If I port my number out, what happens to my balance?",
]


def kinds(question):
    return [k for _, k in split_clauses(question)]


class TestClauseRouting(unittest.TestCase):

    def test_both(self):
        for q in BOTH:
            plan = route_query(q, 1042)
            self.assertEqual((plan.route, plan.outcome), ("both", "answer"), q)

    def test_structured(self):
        for q in STRUCTURED:
            plan = route_query(q, 1042)
            self.assertEqual((plan.route, plan.outcome), ("structured", "answer"), q)

    def test_unstructured(self):
        for q in UNSTRUCTURED:
            plan = route_query(q, 1042)
            self.assertEqual((plan.route, plan.outcome), ("unstructured", "answer"), q)
            self.assertTrue(plan.has_policy_component, q)

    def test_clause_decomposition_and_kinds(self):
        self.assertEqual(split_clauses(BOTH[0]),
                         [("My last top-up failed", ASSERTION), ("what should I do next", POLICY)])
        self.assertEqual(split_clauses(BOTH[1]),
                         [("My invoice shows unpaid but I already paid", ASSERTION), ("how do I fix it", POLICY)])
        # conditional inheritance: the clause after "If ..." is also hypothetical; the sentence before is independent
        self.assertEqual(split_clauses(BOTH[2]),
                         [("My ticket is still open", ASSERTION), ("If it stays open for a week", HYPOTHETICAL),
                          ("what happens", HYPOTHETICAL)])
        self.assertEqual(split_clauses(STRUCTURED[0]), [("Did my last payment succeed", STATUS_QUERY)])
        self.assertEqual(kinds(UNSTRUCTURED[0]), [HYPOTHETICAL, HYPOTHETICAL])

    def test_wh_word_followed_by_an_auxiliary_is_not_hypothetical(self):
        self.assertEqual(kinds("When does my plan expire?"), [STATUS_QUERY])
        # when/after/before + an auxiliary is a wh-question word, not a hypothetical
        self.assertNotEqual(kinds("After does my plan end, what is the rule?")[0], HYPOTHETICAL)
        self.assertEqual(kinds("When I top up twice")[0], HYPOTHETICAL)
        self.assertEqual(kinds("whenever we renew")[0], HYPOTHETICAL)
        self.assertEqual(kinds("after I pay")[0], HYPOTHETICAL)

    def test_if_with_any_subject_is_hypothetical(self):
        for q in ("If the bill is late", "if it fails", "Suppose my plan lapses", "assuming I pay on time",
                  "in case the payment bounces"):
            self.assertEqual(kinds(q), [HYPOTHETICAL], q)

    def test_clauses_before_a_hypothetical_are_independent(self):
        self.assertEqual(kinds("My recharge failed, if it stays failed, what happens?"),
                         [ASSERTION, HYPOTHETICAL, HYPOTHETICAL])

    def test_inheritance_stops_at_the_sentence_boundary(self):
        self.assertEqual(kinds("If it is late, what happens? My bill is unpaid."),
                         [HYPOTHETICAL, HYPOTHETICAL, ASSERTION])

    def test_boundaries(self):
        self.assertEqual([c for c, _ in split_clauses("My bill is unpaid — how do I pay? Thanks; bye")],
                         ["My bill is unpaid", "how do I pay", "Thanks", "bye"])
        self.assertEqual(split_clauses(""), [])
        self.assertEqual(split_clauses(None), [])

    def test_public_gate_output_fields_unchanged(self):
        out = classify_query(BOTH[0])
        self.assertEqual(set(out), {"needs_personal_data", "concept_hint", "hypothetical_frame", "reasoning"})
        self.assertTrue(out["needs_personal_data"])

    def test_sentences_are_not_in_any_benchmark_file(self):
        sentences = [s.lower() for s in BOTH + STRUCTURED + UNSTRUCTURED]
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


class TestSourceHygiene(unittest.TestCase):

    def test_no_control_characters_in_any_hybrid_source_file(self):
        findings = []
        files = sorted(HYBRID_DIR.rglob("*.py"))
        self.assertGreater(len(files), 15)
        for path in files:
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                bad = [c for c in line if ord(c) < 32 and c != "\t"]
                if bad:
                    findings.append(f"{path.relative_to(REPO_ROOT)}:{n}: {[hex(ord(c)) for c in bad]}")
        self.assertEqual(findings, [])
        # the scan must be able to fail: a backspace written the way the Phase 8d bug wrote it is caught
        sample = "x = re.compile(r\"" + chr(8) + "how\")"
        self.assertTrue([c for c in sample if ord(c) < 32 and c != "\t"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
