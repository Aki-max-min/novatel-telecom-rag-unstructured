"""
Configuration for the integrated QA system (router -> retrieval -> fusion ->
grounded generation with verified sentence-level citations).

Everything that could be a "magic number" is a named field, and the two values
that are CALIBRATED (router-confidence threshold, retrieval-confidence
threshold) are loaded from data/eval/system_calibration.json, which records how
and on which split they were chosen. If that file is absent the fields fall back
to the documented defaults below and the result says so.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CALIBRATION_PATH = ROOT / "data" / "eval" / "system_calibration.json"


def load_calibration() -> dict:
    if CALIBRATION_PATH.exists():
        with open(CALIBRATION_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


_CAL = load_calibration()


@dataclass
class QAConfig:
    # --- routing -----------------------------------------------------------
    router: str = "auto"                       # registry name: auto | laya_finetuned | laya_zeroshot | ollama | ...
    router_chain: tuple = ("laya_finetuned", "embedding", "rule")
    # decisions below this confidence are treated as hybrid. Calibrated on VAL.
    router_conf_threshold: float = field(default_factory=lambda: _CAL.get("router", {}).get("threshold", 0.0))
    forced_route: str | None = None            # "structured" | "unstructured" | "hybrid" for ablations

    # --- retrieval ---------------------------------------------------------
    top_k_structured: int = 10
    top_k_unstructured: int = 5
    faiss_depth: int = 10
    top_n_context: int = 10                    # evidence blocks passed to the generator
    fusion: str = "rrf"                        # rrf (default) | rrf_normalised
    rrf_k: int = 60
    retry_other_source_on_weak: bool = True    # safety net: single-route weak -> try the other source
    exclude_scifact: bool = True               # drop SciFact chunks (external benchmark built into the index) at serving time

    # --- optional components (ablation switches; none are hard-wired) -----
    use_ontology: bool = False
    use_doc_graph: bool = False
    use_structured_kg: bool = False            # present in repo; not wired into retrieval (see report)
    use_colpali: bool = False
    ontology_weight: float = 0.15
    graph_weight: float | None = None          # None -> hybrid.query_gate.graph_weight (Person B's validated gate)

    # --- abstention --------------------------------------------------------
    # unstructured evidence is "answerable" if sigmoid(top CrossEncoder logit) >= this. Calibrated on VAL.
    retrieval_conf_threshold: float = field(default_factory=lambda: _CAL.get("retrieval", {}).get("threshold", 0.05))
    abstention_message: str = "I don't have information about that in the NovaTel knowledge base."

    # --- generation --------------------------------------------------------
    generator_model: str = field(default_factory=lambda: os.environ.get("NOVATEL_LLM_MODEL", "qwen2.5:7b-instruct"))
    decomposer_model: str = field(default_factory=lambda: os.environ.get("NOVATEL_LLM_MODEL", "qwen2.5:7b-instruct"))
    max_answer_sentences: int = 8

    # --- citation verification --------------------------------------------
    verifier: str = "nli"                      # nli | lexical
    nli_supported_threshold: float = 0.50      # entailment prob for SUPPORTED
    nli_weak_threshold: float = 0.15           # entailment prob for WEAK
    lexical_supported_threshold: float = 0.60
    lexical_weak_threshold: float = 0.35
    drop_unsupported: bool = False             # False: keep but visibly flag; True: remove from answer_text

    debug: bool = False

    def as_dict(self) -> dict:
        d = asdict(self)
        d["calibration_file"] = str(CALIBRATION_PATH) if CALIBRATION_PATH.exists() else None
        return d
