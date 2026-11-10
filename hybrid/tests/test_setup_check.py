"""Setup-check and reproducibility tests: the missing-graph error names the exact fix command and stays an error;
setup_check reports OK/MISSING per asset with a fix command. No network, no models."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "hybrid"))

import setup_check  # noqa: E402
from knowledge_graph.graph_augmented_retrieval import load_graph_index  # noqa: E402


class TestMissingGraphError(unittest.TestCase):

    def test_error_contains_the_exact_command_and_is_not_swallowed(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "graph.json"
            with self.assertRaises(FileNotFoundError) as ctx:
                load_graph_index(missing)
            message = str(ctx.exception)
            self.assertIn("python -m knowledge_graph.graph_builder", message)
            self.assertIn(str(missing), message)
            self.assertFalse(missing.exists())   # it never builds anything silently


class TestSetupCheck(unittest.TestCase):

    def make_root(self, d, with_everything):
        root = Path(d) / "repo"
        cache = Path(d) / "hf"
        if with_everything:
            for rel in ("data/processed/structured/novatel_structured.db", "knowledge_graph/output/graph.json",
                        "data/vectorstore/faiss.index", "data/vectorstore/chunk_metadata.json"):
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("x")
            for folder in (setup_check.EMBEDDING_MODEL_DIR, setup_check.CROSSENCODER_MODEL_DIR):
                (cache / folder / "snapshots" / "abc").mkdir(parents=True)
        else:
            root.mkdir(parents=True)
            cache.mkdir()
        return root, cache

    def test_everything_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root, cache = self.make_root(d, False)
            rows = setup_check.check(root, cache)
        self.assertEqual([r[0] for r in rows], ["structured DB", "graph.json", "FAISS index", "model files"])
        self.assertFalse(any(ok for _, ok, _, _ in rows))
        fixes = {name: fix for name, _, _, fix in rows}
        self.assertIn("python -m knowledge_graph.graph_builder", fixes["graph.json"])
        self.assertIn("build_database", fixes["structured DB"])
        self.assertIn("ingestion.build_faiss_index", fixes["FAISS index"])
        self.assertIn("sentence_transformers", fixes["model files"])

    def test_everything_present(self):
        with tempfile.TemporaryDirectory() as d:
            root, cache = self.make_root(d, True)
            rows = setup_check.check(root, cache)
        self.assertTrue(all(ok for _, ok, _, _ in rows))

    def test_one_missing_model_is_reported_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            root, cache = self.make_root(d, True)
            import shutil
            shutil.rmtree(cache / setup_check.CROSSENCODER_MODEL_DIR)
            rows = {name: (ok, detail) for name, ok, detail, _ in setup_check.check(root, cache)}
        self.assertFalse(rows["model files"][0])
        self.assertIn("cross-encoder/ms-marco-MiniLM-L-6-v2", rows["model files"][1])

    def test_main_prints_ok_or_missing_and_sets_the_exit_code(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = setup_check.main()
        out = buf.getvalue()
        self.assertIn(code, (0, 1))
        for name in ("structured DB", "graph.json", "FAISS index", "model files"):
            self.assertIn(name, out)
        self.assertTrue("OK" in out or "MISSING" in out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
