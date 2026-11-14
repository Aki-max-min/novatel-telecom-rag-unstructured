"""
Deterministic, local NLI-based faithfulness checker. Runs entirely on CPU
(device=-1) -- the GPU is reserved for Ollama generation. Complements
(does not replace) both the DeepEval LLM-judged FaithfulnessMetric and the
deterministic structured-fact checker in factcheck.py.

Why this exists: factcheck.py only ever checks sentences that cite
structured evidence, so unstructured/hybrid answers have NO deterministic
groundedness signal today -- only the (weak, 3B/7B-judged) DeepEval score.
This module gives every answer, regardless of source type, a deterministic,
no-LLM-involved faithfulness number.

No randomness, no LLM calls, fixed threshold from config. The HF
text-classification pipeline is loaded once (module-level cache) and reused
across every answer scored in a run.
"""

import re

NLI_MODEL_NAME = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
DEFAULT_THRESHOLD = 0.50

_CITATION_RE = re.compile(r"\[(E\d+)\]")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")

_nli_pipeline = None


def _get_pipeline():
    """Loads the NLI model once (CPU only) and caches it at module level."""
    global _nli_pipeline
    if _nli_pipeline is None:
        from transformers import pipeline as hf_pipeline

        _nli_pipeline = hf_pipeline(
            "text-classification",
            model=NLI_MODEL_NAME,
            device=-1,  # CPU only -- GPU is reserved for Ollama
            top_k=None,
        )
    return _nli_pipeline


def split_sentences(answer: str) -> list[str]:
    """
    Simple, dependency-light sentence splitter: regex on ./?/! boundaries.

    LIMITATION (disclosed, not hidden): this will mis-split on abbreviations
    (e.g. "Mr.", "e.g.", "approx.") and can over-split numbered lists where
    each bullet ends in a period. It is not a real sentence-boundary model.
    Adequate for short, templated support answers; not general-purpose NLP.
    """
    return [s.strip() for s in _SENTENCE_BOUNDARY_RE.split(answer) if s.strip()]


def _best_entailment(nli_pipe, premises: list[str], hypothesis: str) -> dict:
    """
    Scores `hypothesis` against every premise and keeps the MAX entailment
    probability seen (per requirement: "Take the MAX entailment probability
    across the cited chunks"). Returns the argmax label and entailment prob
    for whichever premise produced that max.
    """
    best = {"entailment_prob": 0.0, "argmax_label": None, "premise_index": None}
    for index, premise in enumerate(premises):
        if not premise or not premise.strip():
            continue
        result = nli_pipe(premise, text_pair=hypothesis, truncation=True)
        if result and isinstance(result[0], list):  # top_k=None batches as list-of-lists
            result = result[0]
        scores = {entry["label"].lower(): entry["score"] for entry in result}
        entailment_prob = scores.get("entailment", 0.0)
        if entailment_prob > best["entailment_prob"] or best["premise_index"] is None:
            argmax_label = max(scores, key=scores.get)
            best = {
                "entailment_prob": entailment_prob,
                "argmax_label": argmax_label,
                "premise_index": index,
            }
    return best


def score_answer_faithfulness(
    answer: str,
    evidence: list[dict],
    threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    """
    answer: generated answer text, expected to contain [Ek] citation markers
        (as produced by integration/rag/generate.py's prompt contract).
    evidence: the context_builder evidence list used to generate this answer
        -- each entry has "id" and "content" (and others, ignored here).
    threshold: minimum entailment probability, on top of entailment being
        the argmax label, for a sentence to count as "supported".

    Per-sentence: premise = each CITED evidence chunk's content (falls back
    to ALL retrieved evidence content if the sentence has no [Ek] citation).
    Hypothesis = the sentence. Supported iff entailment is the argmax label
    AND its probability >= threshold.

    Returns {
        "nli_faithfulness": float | None,  # supported/total; None if no
            evidence was retrieved at all (e.g. a correct abstention -- not
            penalized as "unfaithful" for having nothing to check against)
        "total_sentences": int,
        "supported_sentence_count": int,
        "unsupported_sentence_count": int,
        "unsupported_sentences": [ {sentence, best_entailment_prob,
            argmax_label, cited_evidence_ids} ... ],
        "threshold": float,
        "model": str,
    }
    """
    sentences = split_sentences(answer)

    if not evidence:
        return {
            "nli_faithfulness": None,
            "total_sentences": len(sentences),
            "supported_sentence_count": 0,
            "unsupported_sentence_count": 0,
            "unsupported_sentences": [],
            "threshold": threshold,
            "model": NLI_MODEL_NAME,
            "note": "No evidence was retrieved for this query -- not scored "
                    "(an abstention has nothing to be entailed by or against).",
        }

    nli_pipe = _get_pipeline()
    evidence_by_id = {item["id"]: item.get("content", "") for item in evidence}
    all_context_texts = [item.get("content", "") for item in evidence if item.get("content")]

    supported_count = 0
    unsupported = []

    for sentence in sentences:
        cited_ids = _CITATION_RE.findall(sentence)
        if cited_ids:
            premises = [evidence_by_id[cid] for cid in cited_ids if cid in evidence_by_id]
        else:
            premises = all_context_texts

        # Strip [Ek] citation markers from the hypothesis text itself -- the
        # NLI model was never trained on this bracket syntax, and leaving it
        # in measurably pollutes the entailment score (verified: the same
        # sentence scored 0.16/neutral with markers left in vs. 0.59/
        # entailment with them stripped, on an otherwise clear paraphrase).
        clean_sentence = _CITATION_RE.sub("", sentence).strip()
        clean_sentence = re.sub(r"\s+", " ", clean_sentence)

        if not premises:
            unsupported.append({
                "sentence": sentence,
                "best_entailment_prob": 0.0,
                "argmax_label": None,
                "cited_evidence_ids": cited_ids,
            })
            continue

        best = _best_entailment(nli_pipe, premises, clean_sentence)
        is_supported = best["argmax_label"] == "entailment" and best["entailment_prob"] >= threshold

        if is_supported:
            supported_count += 1
        else:
            unsupported.append({
                "sentence": sentence,
                "best_entailment_prob": best["entailment_prob"],
                "argmax_label": best["argmax_label"],
                "cited_evidence_ids": cited_ids,
            })

    total = len(sentences)
    nli_faithfulness = (supported_count / total) if total else None

    return {
        "nli_faithfulness": nli_faithfulness,
        "total_sentences": total,
        "supported_sentence_count": supported_count,
        "unsupported_sentence_count": len(unsupported),
        "unsupported_sentences": unsupported,
        "threshold": threshold,
        "model": NLI_MODEL_NAME,
    }
