"""
EmbeddingPrototypeRouter -- open source, no server.

Embeds the query with a sentence-transformers model and compares it (cosine)
to one PROTOTYPE per label (the normalised mean embedding of that label's
queries in router_train.jsonl ONLY -- never val or test). A softmax over the
four prototype similarities gives a label posterior, from which the three
independent heads are read off so hybrid stays expressible:

    p_in_scope = 1 - P(out_of_scope)
    p_struct   = P(structured)   + P(hybrid)
    p_unstruct = P(unstructured) + P(hybrid)

The softmax temperature is the only hyper-parameter; it is chosen on the
VALIDATION split (minimum negative log-likelihood), never on test.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from query_router.base import BaseRouter, RouterUnavailable

ROOT = Path(__file__).resolve().parents[1]
TRAIN_PATH = ROOT / "data" / "eval" / "router_train.jsonl"
VAL_PATH = ROOT / "data" / "eval" / "router_val.jsonl"
LABEL_ORDER = ("structured", "unstructured", "hybrid", "out_of_scope")

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
FALLBACK_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _read_jsonl(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class EmbeddingPrototypeRouter(BaseRouter):
    name = "embedding"

    def __init__(self, model_name: str = DEFAULT_MODEL, temperature: float | None = None,
                 allow_fallback_model: bool = False):
        self.requested_model = model_name
        self.model_id = model_name
        self.allow_fallback_model = allow_fallback_model
        self.temperature = temperature
        self._model = None
        self._prototypes = None
        self._load_error = None

    # -- lifecycle ---------------------------------------------------------
    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover
            self._load_error = f"sentence-transformers unavailable: {exc}"
            raise RouterUnavailable(self._load_error)
        try:
            self._model = SentenceTransformer(self.requested_model)
        except Exception as exc:
            if not self.allow_fallback_model:
                self._load_error = f"cannot load {self.requested_model}: {exc}"
                raise RouterUnavailable(self._load_error)
            self._model = SentenceTransformer(FALLBACK_MODEL)
            self.model_id = FALLBACK_MODEL
        self.size_params = sum(p.numel() for p in self._model.parameters())

        train = _read_jsonl(TRAIN_PATH)
        embeddings = self._model.encode([r["query"] for r in train], normalize_embeddings=True, convert_to_numpy=True)
        protos = []
        for label in LABEL_ORDER:
            rows = np.array([i for i, r in enumerate(train) if r["label"] == label])
            centroid = embeddings[rows].mean(axis=0)
            protos.append(centroid / (np.linalg.norm(centroid) + 1e-12))
        self._prototypes = np.vstack(protos)

        if self.temperature is None:
            self.temperature = self._tune_temperature()

    def available(self):
        if self._model is not None:
            return True, ""
        if self._load_error:
            return False, self._load_error
        try:
            self._load()
            return True, ""
        except RouterUnavailable as exc:
            return False, str(exc)

    # -- math --------------------------------------------------------------
    def _posterior(self, query_embedding: np.ndarray, temperature: float) -> np.ndarray:
        sims = self._prototypes @ query_embedding
        z = sims / temperature
        z = z - z.max()
        e = np.exp(z)
        return e / e.sum()

    def _tune_temperature(self) -> float:
        """Pick the softmax temperature that minimises NLL on the VALIDATION split."""
        val = _read_jsonl(VAL_PATH)
        embeddings = self._model.encode([r["query"] for r in val], normalize_embeddings=True, convert_to_numpy=True)
        best_t, best_nll = 0.05, math.inf
        for t in (0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.2):
            nll = 0.0
            for row, emb in zip(val, embeddings):
                p = self._posterior(emb, t)
                nll -= math.log(max(p[LABEL_ORDER.index(row["label"])], 1e-9))
            nll /= len(val)
            if nll < best_nll:
                best_t, best_nll = t, nll
        return best_t

    def _predict(self, query: str) -> dict:
        self._load()
        emb = self._model.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]
        post = self._posterior(emb, self.temperature)
        p = dict(zip(LABEL_ORDER, post))
        return {
            "p_in_scope": float(1.0 - p["out_of_scope"]),
            "p_structured": float(p["structured"] + p["hybrid"]),
            "p_unstructured": float(p["unstructured"] + p["hybrid"]),
            "extra": {"label_posterior": {k: round(float(v), 4) for k, v in p.items()},
                      "temperature": self.temperature},
        }
