"""
Step 3 of the KG fixes (tests first), hybrid side: the `concept` label stamped on structured facts is no longer dropped by
hybrid/context.py - it appears on each fact, in Context.concepts and in the pipeline trace. NOTHING else changes: the extractive
answer text for the anchor customers is identical to the text recorded before the change (golden_answers_step3.json), and retrieval
does not depend on concept metadata (graph_expand ignores the new labels; checked on the 52 dev questions when the models are available).
"""

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pipeline  # noqa: E402
from answer import answer_question  # noqa: E402
from context import assemble_context  # noqa: E402

GOLDEN = json.loads((Path(__file__).parent / "golden_answers_step3.json").read_text(encoding="utf-8"))["answers"]
HAVE_MODELS = all(importlib.util.find_spec(m) for m in ("faiss", "sentence_transformers"))


class TestConceptExposure(unittest.TestCase):

    def result(self, question, customer, as_of=None):
        return pipeline.run_hybrid_query(question, customer, as_of)

    def test_facts_carry_their_concept_in_the_context(self):
        ctx = assemble_context(self.result("Did my last recharge go through?", 1042))
        self.assertTrue(ctx.facts)
        self.assertEqual({f["concept"] for f in ctx.facts}, {"Recharge"})
        self.assertEqual(ctx.concepts, ["Recharge"])

    def test_concept_per_table(self):
        ctx = assemble_context(self.result("Is my KYC complete?", 1042))
        by_table = {f["table"]: f["concept"] for f in ctx.facts}
        self.assertEqual(by_table["customer_master"], "Customer Account")
        self.assertEqual(by_table["kyc_records"], "KYC & Identity Verification")
        self.assertEqual(ctx.concepts, ["Customer Account", "KYC & Identity Verification"])

    def test_concept_is_still_not_part_of_the_stored_fields(self):
        ctx = assemble_context(self.result("Did my last recharge go through?", 1042))
        for fact in ctx.facts:
            self.assertNotIn("concept", fact["fields"])
            self.assertNotIn("concept=", fact["text"])        # the verifier's evidence text is unchanged too

    def test_trace_exposes_the_concepts(self):
        out = self.result("When does my plan expire?", 1042, "2026-10-06")
        t = out["trace"]
        self.assertEqual(t["fact_concepts"], ["Subscription"])
        self.assertIn("concept_hint", t)

    def test_no_facts_no_concepts(self):
        out = self.result("Did my last recharge go through?", None)
        self.assertEqual(out["trace"]["fact_concepts"], [])
        self.assertEqual(assemble_context(out).concepts, [])

    def test_extractive_answer_text_is_identical_to_the_recorded_golden(self):
        for g in GOLDEN:
            out = answer_question(g["question"], g["customer"], g["as_of"], pipeline=pipeline.run_hybrid_query)
            self.assertEqual(out["answer"], g["answer"], g["question"])
            self.assertEqual(out["notices"], g["notices"])
            self.assertEqual(out["citations"], g["citations"])
            self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])


@unittest.skipUnless(HAVE_MODELS, "needs faiss + sentence-transformers (rag-api environment)")
class TestRetrievalDoesNotMove(unittest.TestCase):

    def test_top5_of_all_52_dev_questions_is_identical_with_and_without_the_concept_layer(self):
        import tempfile
        from knowledge_graph.graph_builder import GRAPH_JSON_PATH
        if not GRAPH_JSON_PATH.exists():
            self.skipTest("graph.json missing: run python -m knowledge_graph.build_related_aliases && python -m knowledge_graph.graph_builder")
        try:
            import evaluate_fixes as ef
            from knowledge_graph.graph_augmented_retrieval import load_graph_index
            run = ef.Runner()
        except Exception as exc:  # models not cached on this machine
            self.skipTest(f"retrieval assets unavailable: {type(exc).__name__}: {exc}")
        payload = json.loads(GRAPH_JSON_PATH.read_text(encoding="utf-8"))
        stripped = {"nodes": [n for n in payload["nodes"] if n["label"] != "Concept"],
                    "edges": [e for e in payload["edges"] if e["type"] != "EXPRESSES_CONCEPT"]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "graph.json"
            p.write_text(json.dumps(stripped), encoding="utf-8")
            plain_index = load_graph_index(p)
        full_index = run.ctx["graph_index"]
        from knowledge_graph.evaluate_hardening import SETS, load_sets
        sets = load_sets()
        cfg = ef.current_state()
        checked = 0
        for s in SETS:
            for q, _ in sets[s]:
                run.ctx["graph_index"] = full_index
                a = [c["metadata"]["document_id"] for c in run.ranked(q, cfg, 5)[2]]
                run.ctx["graph_index"] = plain_index
                b = [c["metadata"]["document_id"] for c in run.ranked(q, cfg, 5)[2]]
                self.assertEqual(a, b, q)
                checked += 1
        run.ctx["graph_index"] = full_index
        self.assertEqual(checked, 52)


if __name__ == "__main__":
    unittest.main(verbosity=2)
