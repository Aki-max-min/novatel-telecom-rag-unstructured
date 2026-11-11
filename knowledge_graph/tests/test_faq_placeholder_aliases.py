"""
KG fixes 2, step 3 (tests first): the 21 KB_Cnn_* -> FAQ_Cnn_001 links, in OUR alias layer only (source documents untouched).

ASSUMPTION (flagged in the audit csv): "001" is a placeholder for the category's own FAQs, so FAQ_Cnn_001 resolves to EVERY FAQ document of
category Cnn in the corpus (two per category) - rule `faq_placeholder_all_in_category`. The 16 FAQ_Cnn_* -> KB_Cnn_overview links in C01, C10,
C11, C12, C14, C15, C24, C27 stay UNRESOLVED (no such document); nothing is linked to any other document.
The switch RESOLVE_FAQ_PLACEHOLDER is False until the pre-declared dev-set rule (docs/E13_kg_fixes2.md) accepts the mapping; these tests pass the flag explicitly.
"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import build_related_aliases as bra  # noqa: E402
from knowledge_graph import entity_extractor, relationship_extractor  # noqa: E402
from knowledge_graph.entity_extractor import extract_entities, load_documents  # noqa: E402
from knowledge_graph.relationship_extractor import extract_relationships  # noqa: E402

UNRESOLVED_KB_CATEGORIES = ["C01", "C10", "C11", "C12", "C14", "C15", "C24", "C27"]


class TestRule(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.documents = load_documents()
        cls.faq_by_cat = {}
        for d in cls.documents:
            if d["document_id"].startswith("FAQ_"):
                cls.faq_by_cat.setdefault(d["category"], []).append(d["document_id"])
        cls.aliases, cls.audit, cls.multi = bra.build_aliases(cls.documents, faq_placeholder=True, with_multi=True)

    def test_switch_exists_and_off_keeps_the_old_result(self):
        self.assertIsInstance(bra.RESOLVE_FAQ_PLACEHOLDER, bool)
        aliases, audit = bra.build_aliases(self.documents, faq_placeholder=False)
        self.assertEqual((sum(r["status"] == "resolved" for r in audit), sum(r["status"] == "unresolved" for r in audit)), (47, 37))
        self.assertEqual(len(aliases), 26)

    def test_counts_on(self):
        resolved = [r for r in self.audit if r["status"] == "resolved"]
        self.assertEqual((len(resolved), len(self.audit) - len(resolved)), (68, 16))
        self.assertEqual(sum(r["rule"] == "faq_placeholder_all_in_category" for r in resolved), 21)
        self.assertEqual(len(self.multi), 21)

    def test_each_placeholder_resolves_to_every_faq_of_its_own_category_and_nothing_else(self):
        for target, ids in self.multi.items():
            category = target.split("_")[1]
            self.assertEqual(ids, sorted(self.faq_by_cat[category]), target)
            self.assertEqual(len(ids), 2)
            for i in ids:
                self.assertTrue(i.startswith(f"FAQ_{category}_"))

    def test_an_existing_faq_001_document_is_never_aliased(self):
        existing = {d["document_id"] for d in self.documents}
        self.assertTrue(all(t not in existing for t in self.multi))
        self.assertNotIn("FAQ_C01_001", self.multi)

    def test_sixteen_kb_overview_links_in_eight_categories_stay_unresolved(self):
        unresolved = [r for r in self.audit if r["status"] == "unresolved"]
        self.assertEqual(len(unresolved), 16)
        self.assertTrue(all(r["rule"] == "kb_overview_not_unique" and r["resolved_target"] == "" for r in unresolved))
        self.assertEqual(sorted({r["original_target"][3:6] for r in unresolved}), UNRESOLVED_KB_CATEGORIES)
        self.assertTrue(all(r["original_target"].endswith("_overview") for r in unresolved))

    def test_audit_rows_carry_the_assumption_flag(self):
        rows = [r for r in self.audit if r["rule"] == "faq_placeholder_all_in_category"]
        self.assertEqual(len(rows), 21)
        for r in rows:
            self.assertIn("ASSUMPTION", r["note"])
            self.assertEqual(r["resolved_target"].count(";"), 1)
        self.assertTrue(all(r["note"] == "" for r in self.audit if r["rule"] != "faq_placeholder_all_in_category"))

    def test_files_are_written_with_the_multi_aliases_and_are_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.json", Path(d) / "a.csv"
            with mock.patch.object(bra, "RESOLVE_FAQ_PLACEHOLDER", True):
                counts = bra.write_files(a, b)
                first = (a.read_bytes(), b.read_bytes())
                bra.write_files(a, b)
                self.assertEqual(first, (a.read_bytes(), b.read_bytes()))
            payload = json.loads(a.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["multi_aliases"]), 21)
            self.assertEqual(len(payload["aliases"]), 26)                  # single-valued aliases untouched
            rows = list(csv.DictReader(b.open(encoding="utf-8")))
            self.assertEqual(list(rows[0].keys()), bra.AUDIT_FIELDS)
            self.assertIn("note", bra.AUDIT_FIELDS)
        self.assertEqual(counts["resolved"], 68)

    def test_off_writes_no_multi_aliases(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.json", Path(d) / "a.csv"
            with mock.patch.object(bra, "RESOLVE_FAQ_PLACEHOLDER", False):
                counts = bra.write_files(a, b)
            self.assertEqual(json.loads(a.read_text(encoding="utf-8")).get("multi_aliases", {}), {})
        self.assertEqual(counts["resolved"], 47)


class TestExtractorsApplyMultiAliases(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.documents = load_documents()
        _, _, cls.multi = bra.build_aliases(cls.documents, faq_placeholder=True, with_multi=True)

    def run_with(self, multi):
        with mock.patch.object(entity_extractor, "load_related_multi_aliases", lambda *a, **k: multi), \
                mock.patch.object(relationship_extractor, "load_related_multi_aliases", lambda *a, **k: multi):
            return extract_entities(self.documents), extract_relationships(self.documents)

    def test_off_is_the_legacy_graph(self):
        ents, rels = self.run_with({})
        related = [e for e in rels["edges"] if e["type"] == "RELATED_TO"]
        self.assertEqual((len(related), rels["stats"]["related_ids_resolved"], rels["stats"]["related_ids_unresolved"]), (84, 47, 37))

    def test_on_one_edge_per_resolved_target(self):
        ents, rels = self.run_with(self.multi)
        related = [e for e in rels["edges"] if e["type"] == "RELATED_TO"]
        self.assertEqual(len(related), 84 + 21)                              # each of the 21 links becomes 2 edges
        self.assertEqual((rels["stats"]["related_ids_total"], rels["stats"]["related_ids_resolved"],
                          rels["stats"]["related_ids_unresolved"]), (84, 68, 16))
        via = [e for e in related if e["properties"].get("via_alias")]
        self.assertEqual(len(via), 47 + 42)
        multi_edges = [e for e in related if e["properties"].get("alias_rule") == "faq_placeholder_all_in_category"]
        self.assertEqual(len(multi_edges), 42)
        self.assertTrue(all(e["properties"]["resolved"] is True for e in multi_edges))
        stubs = [n for n in ents["nodes"] if n["label"] == "Document" and n["properties"].get("stub")]
        self.assertEqual(len(stubs), 8)                                       # only the 8 KB_Cnn_overview ids remain stubs
        self.assertTrue(all(n["key"].startswith("KB_") for n in stubs))

    def test_extractors_agree_on_what_is_a_stub(self):
        ents, rels = self.run_with(self.multi)
        stub_keys = {n["key"] for n in ents["nodes"] if n["label"] == "Document" and n["properties"].get("stub")}
        self.assertEqual(stub_keys, set(rels["unresolved_targets"]))

    def test_missing_multi_alias_file_means_legacy_behaviour(self):
        self.assertEqual(entity_extractor.load_related_multi_aliases(Path("/nonexistent/aliases.json")), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
