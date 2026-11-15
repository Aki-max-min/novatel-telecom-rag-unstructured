"""
Overlay NEW concepts whose names equal a document Category NAME ("Privacy & Data Protection" = C19, "IoT & M2M Services" = C24) must not be confused with the Category:
  * the Concept node has its own id ("Concept::<name>") that differs from the Category node id ("Category::<code>"), and no node id is shared;
  * there is NO Category -> Concept entry in the GraphIndex (concept_categories / categories_of_concept / concepts_of_category / concept_groups)
    unless an explicit EXPRESSES_CONCEPT edge exists in graph.json: sharing a name never creates the link by itself;
  * a positive control: when such an edge is written, the index entry appears.
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import vocabulary_overlay as vo  # noqa: E402
from knowledge_graph.graph_augmented_retrieval import load_graph_index  # noqa: E402
from knowledge_graph.graph_builder import build_full, save_graph  # noqa: E402

COLLISIONS = {"Privacy & Data Protection": "C19", "IoT & M2M Services": "C24"}


class TestOverlayConceptsThatShareACategoryName(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        built = build_full()
        cls.tmp = tempfile.TemporaryDirectory()
        save_graph(built["graph"], built["entities"], built["relationships"], built["content"], output_dir=Path(cls.tmp.name),
                   concepts=built["concepts"])
        cls.path = Path(cls.tmp.name) / "graph.json"
        cls.payload = json.loads(cls.path.read_text(encoding="utf-8"))
        cls.index = load_graph_index(cls.path)
        cls.nodes = {n["id"]: n for n in cls.payload["nodes"]}
        cls.category_names = {n["key"]: n["properties"].get("name") for n in cls.payload["nodes"] if n["label"] == "Category"}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_collision_exists_in_the_data_so_the_test_is_not_vacuous(self):
        new = set(vo.load_overlay().new_concepts)
        for name, code in COLLISIONS.items():
            self.assertIn(name, new, name)                                   # an accepted overlay NEW concept
            self.assertEqual(self.category_names[code], name)                # and a Category's name

    def test_concept_and_category_nodes_have_distinct_ids(self):
        for name, code in COLLISIONS.items():
            concept_id, category_id = f"Concept::{name}", f"Category::{code}"
            self.assertIn(concept_id, self.nodes)
            self.assertIn(category_id, self.nodes)
            self.assertNotEqual(concept_id, category_id)
            self.assertEqual(self.nodes[concept_id]["label"], "Concept")
            self.assertEqual(self.nodes[category_id]["label"], "Category")
            self.assertEqual(self.nodes[concept_id]["properties"]["source"], "vocabulary_extension")
        ids = [n["id"] for n in self.payload["nodes"]]
        self.assertEqual(len(ids), len(set(ids)))                            # no node id is shared by two nodes

    def test_the_graph_has_no_edge_between_the_same_named_category_and_concept(self):
        for name, code in COLLISIONS.items():
            linking = [e for e in self.payload["edges"]
                       if {e["source"], e["target"]} == {f"Category::{code}", f"Concept::{name}"}]
            self.assertEqual(linking, [], (name, code))
            expresses = [e for e in self.payload["edges"] if e["type"] == "EXPRESSES_CONCEPT" and e["target"] == f"Concept::{name}"]
            self.assertEqual(expresses, [], name)                            # the overlay concept is reached by MENTIONS_CONCEPT only

    def test_no_category_to_concept_index_entry_without_an_explicit_edge(self):
        for name, code in COLLISIONS.items():
            self.assertEqual(self.index.categories_of_concept(name), [], name)
            self.assertNotIn(name, self.index.concepts_of_category(code), code)
            self.assertNotIn(name, self.index.concept_groups().get(code, []), code)
            self.assertNotIn(name, self.index.concept_categories)
            self.assertEqual(self.index.documents_of_concept(name), [], name)    # documents_of_concept follows categories only
        self.assertIn("Privacy & Data Protection", self.index.concepts())          # the Concept node itself is loaded

    def test_positive_control_an_explicit_expresses_concept_edge_creates_the_entry(self):
        payload = copy.deepcopy(self.payload)
        payload["edges"].append({"source": "Category::C19", "target": "Concept::Privacy & Data Protection", "type": "EXPRESSES_CONCEPT",
                                 "source_field": "test", "properties": {"via": "Category"}})
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "graph.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            index = load_graph_index(p)
        self.assertEqual(index.categories_of_concept("Privacy & Data Protection"), ["C19"])
        self.assertIn("Privacy & Data Protection", index.concepts_of_category("C19"))
        self.assertEqual(index.categories_of_concept("IoT & M2M Services"), [])      # the other collision is still unlinked


if __name__ == "__main__":
    unittest.main(verbosity=2)
