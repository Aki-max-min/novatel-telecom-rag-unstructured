"""
SetFitRouter -- open source, few-shot contrastive fine-tune of a sentence-
transformers encoder + logistic-regression heads.

Three INDEPENDENT binary targets (in_scope, needs_structured, needs_unstructured)
are trained with SetFit's multi-label "one-vs-rest" strategy, so hybrid is
expressible. Training data: router_train.jsonl ONLY.

    python -m query_router.setfit_router --train

The trained model is written under models/ (git-ignored). If SetFit cannot train
in the current environment (it predates transformers 5.x), `train()` raises and
the router reports itself unavailable -- it is then marked "not run" in the
comparison, never silently substituted.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from query_router.base import BaseRouter, RouterUnavailable

ROOT = Path(__file__).resolve().parents[1]
TRAIN_PATH = ROOT / "data" / "eval" / "router_train.jsonl"
DEFAULT_CHECKPOINT = ROOT / "models" / "setfit_router"
BASE_ENCODER = "sentence-transformers/all-MiniLM-L6-v2"
TARGETS = ("in_scope", "needs_structured", "needs_unstructured")


def _load_rows(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def train(checkpoint: Path = DEFAULT_CHECKPOINT, base_encoder: str = BASE_ENCODER,
          batch_size: int = 16, num_epochs: int = 1, num_iterations: int = 20, seed: int = 42) -> dict:
    from datasets import Dataset
    from setfit import SetFitModel, Trainer, TrainingArguments

    rows = _load_rows(TRAIN_PATH)
    assert all(r["split"] == "train" for r in rows)
    dataset = Dataset.from_dict({
        "text": [r["query"] for r in rows],
        "label": [[int(r[t]) for t in TARGETS] for r in rows],
    })
    model = SetFitModel.from_pretrained(base_encoder, multi_target_strategy="one-vs-rest")
    args = TrainingArguments(batch_size=batch_size, num_epochs=num_epochs, num_iterations=num_iterations, seed=seed)
    trainer = Trainer(model=model, args=args, train_dataset=dataset)

    start = time.time()
    trainer.train()
    elapsed = time.time() - start

    checkpoint.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(checkpoint))
    summary = {"base_encoder": base_encoder, "train_rows": len(rows), "seconds": round(elapsed, 1),
               "batch_size": batch_size, "num_epochs": num_epochs, "num_iterations": num_iterations, "seed": seed}
    with open(checkpoint / "training_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary


class SetFitRouter(BaseRouter):
    name = "setfit"

    def __init__(self, checkpoint: Path | str = DEFAULT_CHECKPOINT):
        self.checkpoint = Path(checkpoint)
        self.model_id = f"setfit:{BASE_ENCODER}"
        self._model = None
        self._load_error = None

    def available(self):
        if self._model is not None:
            return True, ""
        if self._load_error:
            return False, self._load_error
        if not self.checkpoint.exists():
            return False, f"no trained SetFit checkpoint at {self.checkpoint} (run: python -m query_router.setfit_router --train)"
        try:
            self._load()
            return True, ""
        except RouterUnavailable as exc:
            return False, str(exc)

    def _load(self):
        if self._model is not None:
            return
        try:
            from setfit import SetFitModel
            self._model = SetFitModel.from_pretrained(str(self.checkpoint))
        except Exception as exc:
            self._load_error = f"cannot load SetFit checkpoint: {exc}"
            raise RouterUnavailable(self._load_error)
        try:
            self.size_params = sum(p.numel() for p in self._model.model_body.parameters())
        except Exception:
            self.size_params = None

    def _predict(self, query: str) -> dict:
        self._load()
        proba = self._model.predict_proba([query])
        row = [float(x) for x in (proba[0].tolist() if hasattr(proba[0], "tolist") else proba[0])]
        return {"p_in_scope": row[0], "p_structured": row[1], "p_unstructured": row[2]}


if __name__ == "__main__":
    import sys

    if "--train" in sys.argv:
        print(json.dumps(train(), indent=2))
    else:
        print("usage: python -m query_router.setfit_router --train")
