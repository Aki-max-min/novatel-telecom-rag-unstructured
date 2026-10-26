"""
Phase 9d-2 tests: snippet cleaning on REAL chunk text, consequence families, and the KYC acceptance test
through the full pipeline (rag-api environment; skipped without faiss/sentence-transformers).
"""

import importlib.util
import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from answer import answer_question  # noqa: E402
from context import assemble_context  # noqa: E402
from groundedness import verify_answer  # noqa: E402
from snippets import chunk_index_of, clean_chunk_text  # noqa: E402
from test_answerer import stub_pipeline  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
HAVE_RETRIEVAL = all(importlib.util.find_spec(m) for m in ("faiss", "sentence_transformers"))
KYC_Q = "My KYC is showing pending - does that mean my number will get disconnected, and what do I do?"


def chunk(chunk_id):
    data = json.loads((REPO_ROOT / "data" / "processed" / "chunks" / f"{chunk_id}.json").read_text(encoding="utf-8"))
    return data["text"], chunk_index_of(chunk_id)


def candidate(chunk_id, text=None):
    raw, _ = chunk(chunk_id)
    return {"source": "unstructured", "record_id": chunk_id, "dataset": "novatel_synthetic", "category": "",
            "score": 1.0, "retrieval_method": "vector", "content": text or raw,
            "metadata": {"document_id": chunk_id.rsplit("_chunk_", 1)[0], "title": "t"}}


def doc(doc_id, text, chunk_no=0):
    return {"source": "unstructured", "record_id": f"{doc_id}_chunk_{chunk_no:03d}", "dataset": "novatel_synthetic",
            "category": "", "score": 1.0, "retrieval_method": "vector", "content": text,
            "metadata": {"document_id": doc_id, "title": doc_id}}


class TestSnippetCleaningOnRealChunks(unittest.TestCase):

    def test_faq_chunk_0_loses_markers_labels_and_table_but_keeps_the_suspension_sentence(self):
        raw, idx = chunk("FAQ_C17_034_chunk_000")
        self.assertIn("### Key Details | Detail | Value |", raw)          # the raw chunk really has this noise
        clean = clean_chunk_text(raw, idx)
        for noise in ("###", "|", "---", "Question:", "Answer:", "Short Answer", "Detailed Explanation", "Key Details"):
            self.assertNotIn(noise, clean)
        self.assertTrue(clean.startswith("Visit a NovaTel Experience Store"))
        self.assertIn("Failure to complete requested re-verification within the notified window may result in "
                      "service suspension per licence conditions.", clean)

    def test_faq_chunk_1_drops_the_mid_sentence_fragment(self):
        raw, idx = chunk("FAQ_C17_034_chunk_001")
        self.assertTrue(raw[0].islower())                                  # starts mid-sentence
        self.assertEqual(idx, 1)
        clean = clean_chunk_text(raw, idx)
        self.assertFalse(clean[0].islower())
        self.assertNotIn("this makes prompt action", clean)
        self.assertNotIn("###", clean)
        self.assertNotIn("**", clean)
        self.assertIn("Video KYC is enabled in their circle", clean)
        # chunk 0 is never trimmed even if it starts lower-case
        self.assertEqual(clean_chunk_text("lower case start. Next sentence here.", 0), "lower case start. Next sentence here.")

    def test_sop_chunk_loses_the_inline_header(self):
        raw, idx = chunk("SOP_C17_KYC_VERIFICATION_chunk_000")
        self.assertIn("Document ID: SOP_C17_KYC_VERIFICATION", raw)
        clean = clean_chunk_text(raw, idx)
        for noise in ("Document ID", "Category:", "Last Updated", "Source Authority", "Customer Scope", "Version:"):
            self.assertNotIn(noise, clean)
        self.assertTrue(clean.startswith("New Connection and Re-Verification KYC Procedure"))
        self.assertIn("Purpose To ensure all new connections", clean)       # the body is NOT swallowed by the header rule

    def test_cleaning_only_removes_text_it_never_rewrites(self):
        raw, idx = chunk("FAQ_C17_034_chunk_000")
        clean = clean_chunk_text(raw, idx)
        words = re.findall(r"[A-Za-z]{4,}", clean)
        raw_words = set(re.findall(r"[A-Za-z]{4,}", raw))
        self.assertTrue(set(words) <= raw_words)                          # no word appears that was not in the chunk

    def test_assemble_context_applies_cleaning_and_chunk_index(self):
        result = {"route_plan": {"outcome": "answer", "route": "unstructured"}, "facts": [], "blocked": [],
                  "documents": [candidate("FAQ_C17_034_chunk_001")], "trace": {}}
        ctx = assemble_context(result, snippet_chars=2000)
        self.assertFalse(ctx.documents[0]["snippet"][0].islower())
        self.assertIn("this makes prompt action", ctx.full_texts[0])        # provenance keeps the FULL raw chunk

    def test_real_table_chunk_has_no_pipes_left(self):
        raw, idx = chunk("FAQ_C20_040_chunk_000")
        self.assertIn("|", raw)
        self.assertNotIn("|", clean_chunk_text(raw, idx))


def ask(question, docs, customer_id=None):
    return answer_question(question, customer_id, None, None, pipeline=stub_pipeline(docs))


class TestConsequenceFamilies(unittest.TestCase):

    SUSPENSION = doc("D_SUSP", "Failure to complete requested re-verification within the notified window may result "
                               "in service suspension per licence conditions. Visit a store with your original ID proof.")

    def test_different_family_member_is_quoted_first_and_the_exact_term_is_declared_absent(self):
        out = ask("Will my number get disconnected if I do not update my details?", [self.SUSPENSION])
        a = out["answer"]
        first_quote = a.split("[D1]")[0]
        self.assertIn("service suspension per licence conditions", first_quote)           # quoted first
        self.assertIn("The retrieved passages don't state anything about disconnect.", a)  # exact term absent
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])

    def test_same_term_is_quoted_and_no_silence_sentence(self):
        out = ask("Will my number be suspended if I do not update my details?", [self.SUSPENSION])
        self.assertIn("service suspension per licence conditions", out["answer"])
        self.assertNotIn("don't state anything about suspend", out["answer"])
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])

    def test_no_family_member_anywhere_gives_the_silence_sentence_only(self):
        plain = doc("D_PLAIN", "Visit a NovaTel Experience Store with your original ID proof to update your details.")
        out = ask("Will my number get disconnected if I do not update my details?", [plain])
        self.assertIn("The retrieved passages don't state anything about disconnect.", out["answer"])
        self.assertNotIn("suspension", out["answer"])
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])

    def test_other_family_pairs(self):
        barred = doc("D_BAR", "Numbers with unpaid dues may be barred for outgoing calls until the dues are cleared.")
        out = ask("Will my SIM be blocked for unpaid dues?", [barred])
        self.assertIn("barred for outgoing calls", out["answer"])
        self.assertIn("The retrieved passages don't state anything about block.", out["answer"])
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])

    def test_silence_sentence_is_never_produced_when_the_term_is_in_the_full_chunk_beyond_the_snippet(self):
        deep = doc("D_DEEP", "Visit a store with your ID. " + "More general words here. " * 120 + "The line may be disconnected afterwards.")
        out = ask("Will my number get disconnected?", [deep])
        self.assertNotIn("don't state anything about disconnect", out["answer"])


@unittest.skipUnless(HAVE_RETRIEVAL, "needs faiss + sentence-transformers (rag-api environment)")
class TestKycAcceptanceRealData(unittest.TestCase):

    def test_customer_1042_kyc_pending_question_through_the_full_pipeline(self):
        out = answer_question(KYC_Q, 1042)
        a = out["answer"]
        doc_sources = [v for k, v in out["citations"].items() if k.startswith("D")]
        retrieved = "document:FAQ_C17_034" in doc_sources
        print(f"\n[KYC 1042] FAQ_C17_034 among cited documents: {retrieved}; cited documents: {doc_sources}")
        print(a)
        self.assertIn("Pending", a)
        self.assertIn("no kyc_records row", a)
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])
        self.assertEqual(out["mode"], "extractive")
        if retrieved:
            self.assertIn("service suspension per licence conditions", a)
            self.assertRegex(a, r"service suspension per licence conditions[^\[]*\[D\d\]")
            self.assertIn("don't state anything about disconnect", a)
        else:
            self.skipTest("FAQ_C17_034 was not among the documents cited for this question - reported, not forced")

    def test_same_question_without_a_customer(self):
        out = answer_question(KYC_Q, None)
        a = out["answer"]
        print(f"\n[KYC no customer] {a}")
        self.assertIn("once you are identified", a)
        self.assertIn("needs_identity", out["notices"])
        self.assertIn("documents_are_generic", out["notices"])
        self.assertTrue(any(k.startswith("D") for k in out["citations"]))
        self.assertFalse(any(k.startswith("F") for k in out["citations"]))
        for value in ("Pending", "1042", "4254", "399.00", "kyc_records row"):
            self.assertNotIn(value, a)
        self.assertNotIn("I found no", a)
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
