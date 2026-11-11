"""
Step 3 of the KG fixes (tests first): connect the structured side to the graph with METADATA ONLY.
23 Concept nodes and 33 EXPRESSES_CONCEPT edges (22 via Category, 11 via Service) from the shared concept vocabulary, each Concept carrying a
"tables" property (table NAMES only, no rows); joined on concept NAME, never on the C-code. GraphIndex gets accessors
(concept -> categories, documents, tables). Retrieval must not move: graph_expand ignores the new labels.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph.graph_augmented_retrieval import GraphIndex, graph_expand, load_graph_index, related_neighbours  # noqa: E402
from knowledge_graph.graph_builder import build_full, save_graph  # noqa: E402

STRUCTURED_SCHEMA = REPO_ROOT / "structured" / "schema.py"


def structured_table_names():
    import importlib.util
    spec = importlib.util.spec_from_file_location("novatel_structured_schema_for_test", STRUCTURED_SCHEMA)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.TABLE_SCHEMAS)


class TestConceptMetadata(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.built = build_full()
        cls.concepts = cls.built["concepts"]

    def test_counts_23_concepts_and_33_expresses_edges(self):
        self.assertEqual(len(self.concepts["nodes"]), 23)
        self.assertEqual(len(self.concepts["edges"]), 33)
        self.assertEqual({e["type"] for e in self.concepts["edges"]}, {"EXPRESSES_CONCEPT"})
        via = [e["properties"]["via"] for e in self.concepts["edges"]]
        self.assertEqual((via.count("Category"), via.count("Service")), (22, 11))
        self.assertTrue(all(n["label"] == "Concept" for n in self.concepts["nodes"]))

    def test_every_concept_carries_table_names_only(self):
        tables = structured_table_names()
        seen = []
        for node in self.concepts["nodes"]:
            props = node["properties"]
            self.assertIsInstance(props["tables"], list, node["key"])
            for name in props["tables"]:
                self.assertIn(name, tables)                 # a real structured table NAME ...
                self.assertIsInstance(name, str)            # ... and nothing but a name
            seen += props["tables"]
        self.assertEqual(len(seen), 28)                     # all 28 structured tables are mapped to exactly one concept
        self.assertEqual(len(set(seen)), 28)
        blob = json.dumps(self.concepts)
        for forbidden in ("customer_id", "msisdn", "9146794714"):
            self.assertNotIn(forbidden, blob)               # no column values / row data

    def test_join_is_on_the_concept_name_not_the_c_code(self):
        by_key = {n["key"]: n for n in self.concepts["nodes"]}
        self.assertEqual(by_key["Billing & Invoices"]["properties"]["tables"], ["invoices"])
        self.assertEqual(by_key["Complaints & Grievances"]["properties"]["tables"], ["escalation_cases", "tickets"])
        # structured C11 = tickets while document C16 = Complaints: the concept ties them by NAME
        edges = [e for e in self.concepts["edges"] if e["target"] == "Concept::Complaints & Grievances"]
        self.assertEqual({e["source"] for e in edges} & {"Category::C16"}, {"Category::C16"})
        self.assertNotIn("Category::C11", {e["source"] for e in edges})
        self.assertTrue(all(e["target"].startswith("Concept::") for e in self.concepts["edges"]))

    def test_all_edge_endpoints_exist_in_the_built_graph(self):
        graph = self.built["graph"]
        for edge in self.concepts["edges"]:
            self.assertIn(edge["source"], graph.nodes, edge)
            self.assertIn(edge["target"], graph.nodes, edge)

    def test_no_duplicate_concept_edges(self):
        pairs = [(e["source"], e["target"]) for e in self.concepts["edges"]]
        self.assertEqual(len(pairs), len(set(pairs)))


class TestGraphBuildWithConcepts(unittest.TestCase):

    def build_to(self, out):
        b = build_full()
        save_graph(b["graph"], b["entities"], b["relationships"], b["content"], output_dir=Path(out), concepts=b["concepts"])
        return json.loads((Path(out) / "graph.json").read_text(encoding="utf-8"))

    def test_graph_json_has_the_concept_layer(self):
        with tempfile.TemporaryDirectory() as d:
            payload = self.build_to(d)
        labels = [n["label"] for n in payload["nodes"]]
        self.assertEqual(labels.count("Concept"), 23)
        self.assertEqual(sum(1 for e in payload["edges"] if e["type"] == "EXPRESSES_CONCEPT"), 33)
        self.assertEqual((len(payload["nodes"]), len(payload["edges"])), (337 + 23, 1636 + 33))
        self.assertEqual(sum(1 for e in payload["edges"] if e["type"] == "RELATED_TO"), 84)   # untouched

    def test_two_builds_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.build_to(a)
            self.build_to(b)
            for name in ("graph.json", "nodes.json", "edges.json"):
                self.assertEqual((Path(a) / name).read_bytes(), (Path(b) / name).read_bytes(), name)

    def test_person_a_reader_and_incident_pairs_read_the_new_graph_unchanged(self):
        """Replicates integration/rag/semantic_layer.py::_read_related_edges (branch integrate/kg-ontology-router-ui)."""
        with tempfile.TemporaryDirectory() as d:
            payload = self.build_to(d)
            path = Path(d) / "graph.json"
            key_of = {n["id"]: n["key"] for n in payload["nodes"]}
            pairs = [(key_of[e["source"]], key_of[e["target"]]) for e in payload["edges"] if e["type"] == "RELATED_TO"]
            known = {n["key"] for n in payload["nodes"] if n["label"] == "Document" and n["properties"].get("resolved", True)}
            self.assertEqual(len(pairs), 84)
            self.assertEqual(len([1 for s, t in pairs if s in known and t in known]), 47)
            index = load_graph_index(path)
        for number, inc in (("0142", "C08"), ("0163", "C04"), ("0179", "C25"), ("0184", "C13"), ("0197", "C18")):
            rca, incident = f"RCA_INC_2026_{number}", f"INC_{inc}_INC_2026_{number}"
            self.assertIn(incident, [r["document_id"] for r in related_neighbours([rca], index)])
            self.assertIn(rca, [r["document_id"] for r in related_neighbours([incident], index)])

    def test_graph_expand_and_related_ignore_the_concept_layer(self):
        with tempfile.TemporaryDirectory() as d:
            payload = self.build_to(d)
            full = Path(d) / "graph.json"
            stripped = Path(d) / "stripped.json"
            keep_nodes = [n for n in payload["nodes"] if n["label"] != "Concept"]
            keep_edges = [e for e in payload["edges"] if e["type"] != "EXPRESSES_CONCEPT"]
            stripped.write_text(json.dumps({"nodes": keep_nodes, "edges": keep_edges}), encoding="utf-8")
            a, b = load_graph_index(full), load_graph_index(stripped)
        for seeds in (["FAQ_C17_034"], ["KB_C17_kyc_reverification", "SOP_C17_KYC_VERIFICATION", "TRX_007"],
                      ["MAN_APP_001", "SOP_C13_APP_ACCESS_ISSUES", "RCA_INC_2026_0184", "FAQ_C13_025", "KB_C13_selfcare_login_issues"]):
            self.assertEqual(graph_expand(seeds, a), graph_expand(seeds, b))
            self.assertEqual(related_neighbours(seeds, a), related_neighbours(seeds, b))
        self.assertEqual(a.document_count, b.document_count)


class TestGraphIndexConceptAccessors(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        b = build_full()
        cls.tmp = tempfile.TemporaryDirectory()
        save_graph(b["graph"], b["entities"], b["relationships"], b["content"], output_dir=Path(cls.tmp.name), concepts=b["concepts"])
        cls.index = load_graph_index(Path(cls.tmp.name) / "graph.json")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_concepts_list(self):
        self.assertEqual(len(self.index.concepts()), 23)
        self.assertIn("Billing & Invoices", self.index.concepts())

    def test_concept_to_categories_documents_and_tables(self):
        ix = self.index
        self.assertEqual(ix.categories_of_concept("Billing & Invoices"), ["C04"])
        self.assertEqual(len(ix.documents_of_concept("Billing & Invoices")), 7)
        self.assertEqual(ix.tables_of_concept("Billing & Invoices"), ["invoices"])
        self.assertEqual(ix.tables_of_concept("Complaints & Grievances"), ["escalation_cases", "tickets"])
        self.assertEqual(ix.categories_of_concept("Complaints & Grievances"), ["C16"])
        docs = ix.documents_of_concept("Complaints & Grievances")
        self.assertEqual(docs, sorted(set(docs)))              # sorted, unique

    def test_concepts_sharing_a_category_are_deduplicated(self):
        ix = self.index
        for first, second, code in (("Plan Catalogue", "Subscription", "C02"), ("Payments", "Recharge", "C03"),
                                    ("Network Coverage", "Network Outages", "C08")):
            self.assertEqual(ix.categories_of_concept(first), [code])
            self.assertEqual(ix.categories_of_concept(second), [code])
            self.assertEqual(ix.documents_of_concept(first), ix.documents_of_concept(second))
            self.assertEqual(sorted(ix.concepts_of_category(code)), sorted([first, second]))
        groups = ix.concept_groups()                            # category -> concepts; each document group listed once
        self.assertEqual(len(groups["C02"]), 2)
        self.assertEqual(sum(1 for cs in groups.values() if len(cs) > 1), 3)

    def test_unknown_inputs_return_empty(self):
        ix = self.index
        self.assertEqual(ix.categories_of_concept("No Such Concept"), [])
        self.assertEqual(ix.documents_of_concept("No Such Concept"), [])
        self.assertEqual(ix.tables_of_concept("No Such Concept"), [])
        self.assertEqual(ix.concepts_of_category("C99"), [])

    def test_an_old_graph_without_concepts_still_loads(self):
        payload = {"nodes": [], "edges": []}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "graph.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            ix = load_graph_index(p)
        self.assertEqual(ix.concepts(), [])
        self.assertIsInstance(ix, GraphIndex)


if __name__ == "__main__":
    unittest.main(verbosity=2)
