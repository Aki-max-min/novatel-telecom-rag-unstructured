"""
ZeroShotNLIRouter -- open source, no server, no training.

Hugging Face `zero-shot-classification` pipeline over an NLI checkpoint. The
query is the premise; each candidate label becomes a hypothesis via
`hypothesis_template`; the NLI entailment score decides.

THREE INDEPENDENT two-label questions are asked (in scope? needs database
records? needs documents?) rather than one four-way question, so hybrid is
expressible: a query can answer "yes" to both data and documents.

The checkpoint (MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli) is the same one
integration/eval/faithfulness_nli.py already uses and has cached locally.
"""

from __future__ import annotations

from query_router.base import BaseRouter, RouterUnavailable

DEFAULT_MODEL = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
TEMPLATE = "This question {}."

# head -> (YES label text, NO label text)
HEADS = {
    "in_scope": (
        "is about a mobile telecom operator's services, customers, billing, network or telecom regulation",
        "is about something unrelated to telecom, such as weather, sport, cooking, coding or general knowledge",
    ),
    "needs_structured": (
        "asks for specific customer, account, invoice, ticket or transaction records, or for a count of records",
        "does not ask for any specific records or counts",
    ),
    "needs_unstructured": (
        "asks about a policy, procedure, rule, regulation or how to do something",
        "does not ask about any policy, procedure or regulation",
    ),
}


class ZeroShotNLIRouter(BaseRouter):
    name = "zeroshot_nli"

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_id = model_name
        self._pipe = None
        self._load_error = None

    def _load(self):
        if self._pipe is not None:
            return
        try:
            from transformers import pipeline
            self._pipe = pipeline("zero-shot-classification", model=self.model_id, device=-1)
        except Exception as exc:
            self._load_error = f"cannot load {self.model_id}: {exc}"
            raise RouterUnavailable(self._load_error)
        self.size_params = sum(p.numel() for p in self._pipe.model.parameters())

    def available(self):
        if self._pipe is not None:
            return True, ""
        if self._load_error:
            return False, self._load_error
        try:
            self._load()
            return True, ""
        except RouterUnavailable as exc:
            return False, str(exc)

    def _p_yes(self, query: str, yes_label: str, no_label: str) -> float:
        out = self._pipe(query, candidate_labels=[yes_label, no_label], hypothesis_template=TEMPLATE, multi_label=False)
        scores = dict(zip(out["labels"], out["scores"]))
        return float(scores[yes_label])

    def _predict(self, query: str) -> dict:
        self._load()
        p = {head: self._p_yes(query, yes, no) for head, (yes, no) in HEADS.items()}
        return {"p_in_scope": p["in_scope"], "p_structured": p["needs_structured"],
                "p_unstructured": p["needs_unstructured"]}
