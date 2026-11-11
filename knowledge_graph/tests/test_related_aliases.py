"""
Tests for the RELATED_TO alias repair (Part 2 of the KG hardening task).

Aliases are a SEPARATE file (knowledge_graph/related_id_aliases.json); the source documents are never edited.
Rules (deterministic only):
  1. INC_INC_<id>      -> the unique document matching ^INC_C\\d\\d_INC_<id>$
  2. KB_Cnn_overview   -> the unique document KB_Cnn_* if exactly one exists
  FAQ_Cnn_001 is NEVER aliased (two FAQs per category: ambiguous); anything else stays unresolved.
Expected: 47 of 84 related ids resolved (5 INC + 42 KB), 37 unresolved (21 FAQ + 16 KB).
"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import build_related_aliases as bra  # noqa: E402
from knowledge_graph.entity_extractor import extract_entities, load_documents  # noqa: E402
from knowledge_graph.graph_builder import build_graph, save_graph  # noqa: E402
from knowledge_graph.relationship_extractor import extract_relationships  # noqa: E402

INCIDENT_PAIRS = {
    "INC_INC_2026_0142": "INC_C08_INC_2026_0142",
    "INC_INC_2026_0163": "INC_C04_INC_2026_0163",
    "INC_INC_2026_0179": "INC_C25_INC_2026_0179",
    "INC_INC_2026_0184": "INC_C13_INC_2026_0184",
    "INC_INC_2026_0197": "INC_C18_INC_2026_0197",
}


class TestAliasRules(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.documents = load_documents()
        cls.aliases, cls.audit = bra.build_aliases(cls.documents)

    def test_expected_counts(self):
        self.assertEqual(len(self.audit), 84)
        resolved = [r for r in self.audit if r["status"] == "resolved"]
        unresolved = [r for r in self.audit if r["status"] == "unresolved"]
        self.assertEqual((len(resolved), len(unresolved)), (47, 37))
        self.assertEqual(sum(r["rule"] == "inc_prefix" for r in resolved), 5)
        self.assertEqual(sum(r["rule"] == "kb_overview_unique" for r in resolved), 42)
        self.assertEqual(sum(r["original_target"].startswith("FAQ_") for r in unresolved), 21)
        self.assertEqual(sum(r["original_target"].startswith("KB_") for r in unresolved), 16)

    def test_incident_pairs_map_to_the_real_ids(self):
        for original, real in INCIDENT_PAIRS.items():
            self.assertEqual(self.aliases[original], real)

    def test_faq_001_is_never_aliased(self):
        self.assertEqual([k for k in self.aliases if k.startswith("FAQ_")], [])

    def test_every_alias_target_is_a_canonical_document(self):
        ids = {d["document_id"] for d in self.documents}
        for original, real in self.aliases.items():
            self.assertIn(real, ids)
            self.assertNotIn(original, ids)

    def test_kb_alias_only_when_the_category_has_exactly_one_kb_document(self):
        ids = sorted(d["document_id"] for d in self.documents)
        for original, real in self.aliases.items():
            if original.startswith("KB_"):
                cnn = original.split("_")[1]
                self.assertEqual([i for i in ids if i.startswith(f"KB_{cnn}_")], [real])

    def test_source_documents_keep_their_original_related_ids(self):
        original_targets = {r for d in self.documents for r in (d.get("related_ids") or [])}
        self.assertTrue(set(INCIDENT_PAIRS) <= original_targets)


class TestAliasFiles(unittest.TestCase):

    def test_committed_alias_files_match_a_fresh_build(self):
        aliases, _ = bra.build_aliases(load_documents())
        committed = json.loads(bra.ALIASES_PATH.read_text(encoding="utf-8"))
        self.assertEqual(committed["aliases"], aliases)
        with bra.AUDIT_PATH.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
            # KG fixes 2 step 3: a sixth column `note` carries the ASSUMPTION flag of the FAQ-placeholder rule (empty for every other row)
            self.assertEqual(reader.fieldnames, ["source_doc", "original_target", "resolved_target", "rule", "status", "note"])
        self.assertEqual(len(rows), 84)

    def test_two_fresh_alias_builds_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            bra.write_files(Path(a) / "aliases.json", Path(a) / "audit.csv")
            bra.write_files(Path(b) / "aliases.json", Path(b) / "audit.csv")
            self.assertEqual((Path(a) / "aliases.json").read_bytes(), (Path(b) / "aliases.json").read_bytes())
            self.assertEqual((Path(a) / "audit.csv").read_bytes(), (Path(b) / "audit.csv").read_bytes())
            # the committed file may carry CRLF after a Windows checkout (git autocrlf); content must match
            self.assertEqual((Path(a) / "aliases.json").read_bytes(),
                             bra.ALIASES_PATH.read_bytes().replace(b"\r\n", b"\n"))


class TestGraphWithAliases(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.documents = load_documents()

    def build(self, out_dir):
        entities = extract_entities(self.documents)
        relationships = extract_relationships(self.documents)
        graph = build_graph(entities, relationships, None)
        save_graph(graph, entities, relationships, None, output_dir=Path(out_dir))
        payload = json.loads((Path(out_dir) / "graph_metadata_only.json").read_text(encoding="utf-8"))
        return payload, relationships

    def test_related_edges_resolve_47_and_leave_37_stubs(self):
        with tempfile.TemporaryDirectory() as d:
            payload, relationships = self.build(d)
        stats = relationships["stats"]
        self.assertEqual((stats["related_ids_total"], stats["related_ids_resolved"], stats["related_ids_unresolved"]),
                         (84, 47, 37))
        related = [e for e in payload["edges"] if e["type"] == "RELATED_TO"]
        self.assertEqual(len(related), 84)
        via = [e for e in related if e["properties"].get("via_alias")]
        self.assertEqual(len(via), 47)
        self.assertTrue(all(e["properties"]["resolved"] is True for e in via))
        unresolved = [e for e in related if not e["properties"]["resolved"]]
        self.assertEqual(len(unresolved), 37)
        self.assertTrue(all("via_alias" not in e["properties"] for e in unresolved))
        stubs = {n["key"] for n in payload["nodes"] if n["label"] == "Document" and n["properties"].get("stub")}
        self.assertFalse(stubs & set(INCIDENT_PAIRS))
        self.assertTrue(all(k.startswith(("FAQ_", "KB_")) for k in stubs))
        key_of = {n["id"]: n["key"] for n in payload["nodes"]}
        self.assertEqual(stubs, {key_of[e["target"]] for e in unresolved})

    def test_incident_edges_point_at_the_real_documents(self):
        with tempfile.TemporaryDirectory() as d:
            payload, _ = self.build(d)
        key_of = {n["id"]: n["key"] for n in payload["nodes"]}
        pairs = {(key_of[e["source"]], key_of[e["target"]]) for e in payload["edges"] if e["type"] == "RELATED_TO"}
        for real in INCIDENT_PAIRS.values():
            number = real.split("_INC_")[1]
            self.assertIn((f"RCA_INC_{number}", real), pairs)

    def test_two_fresh_graph_builds_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.build(a)
            self.build(b)
            for name in ("graph_metadata_only.json", "edges_metadata_only.json", "nodes_metadata_only.json"):
                self.assertEqual((Path(a) / name).read_bytes(), (Path(b) / name).read_bytes(), name)

    def test_missing_alias_file_means_legacy_behaviour(self):
        from knowledge_graph import entity_extractor
        self.assertEqual(entity_extractor.load_related_aliases(Path("/nonexistent/aliases.json")), {})


class TestPersonAReaderCompatibility(unittest.TestCase):
    """Replicates integration/rag/semantic_layer.py::_read_related_edges (branch integrate/kg-ontology-router-ui):
    nodes -> key map, edges with type RELATED_TO. Run against the rebuilt output/graph.json."""

    @staticmethod
    def read_related_edges(graph_path):
        payload = json.loads(Path(graph_path).read_text(encoding="utf-8"))
        key_of = {n["id"]: n["key"] for n in payload["nodes"]}
        return [(key_of[e["source"]], key_of[e["target"]]) for e in payload["edges"] if e["type"] == "RELATED_TO"]

    def test_rebuilt_graph_json_yields_47_resolvable_pairs(self):
        from knowledge_graph.graph_builder import GRAPH_JSON_PATH
        if not GRAPH_JSON_PATH.exists():   # output/ is generated, not tracked: build it with graph_builder first
            self.skipTest("knowledge_graph/output/graph.json missing - run: python -m knowledge_graph.graph_builder")
        payload = json.loads(GRAPH_JSON_PATH.read_text(encoding="utf-8"))
        known = {n["key"] for n in payload["nodes"]
                 if n["label"] == "Document" and n["properties"].get("resolved", True)}
        pairs = self.read_related_edges(GRAPH_JSON_PATH)
        self.assertEqual(len(pairs), 84)
        self.assertEqual(len([1 for s, t in pairs if s in known and t in known]), 47)


if __name__ == "__main__":
    unittest.main(verbosity=2)
