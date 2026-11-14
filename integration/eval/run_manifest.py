"""
Run manifest: one JSON file written next to every evaluation result, recording what was actually used.

    from integration.eval.run_manifest import write_manifest
    write_manifest("results/perf_report/metrics.json", rag_config=RagConfig.b2(), qa_config=QAConfig(),
                   index_dirs=[...], extra={"arm": "B2"})            # -> results/perf_report/metrics.manifest.json

Every value is either read from code, from the running machine, or from the files named; values that the code does not set are
stated as such ("not set in code ...") and never filled in with a guess.

Recorded
  generator model + quantization (quantization asked from the local Ollama server; "unavailable: <reason>" if it cannot answer)
  decoding settings: temperature and seed (defaults of integration/rag/llm_client.OllamaClient), top_p and max tokens
    ("not set in code": Ollama's own defaults apply and are not recorded by the code)
  sha256 of every prompt template used by the RAG generator, the QA generator, the decomposer and the E14a judge
  context-budget settings (shared top_n, per-source budget) and retrieval flags (RagConfig, QAConfig: SciFact filter, ontology,
    document graph, structured KG, ColPali, router, semantic layer, ...)
  index path(s) + sha256 + chunk counts and corpus composition
  git commit hash, branch and whether the working tree had uncommitted changes
  package versions (torch, transformers, sentence-transformers, faiss, numpy, ollama client), hardware, UTC timestamp
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import inspect
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("torch", "transformers", "sentence-transformers", "faiss-cpu", "numpy", "ollama")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest_path_for(results_path) -> Path:
    p = Path(results_path)
    return p.with_name(p.stem + ".manifest.json")


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=20)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def git_info() -> dict:
    return {"commit": _run(["git", "rev-parse", "HEAD"]), "branch": _run(["git", "branch", "--show-current"]),
            "dirty": bool(_run(["git", "status", "--porcelain"]))}


def package_versions() -> dict:
    out = {}
    for name in PACKAGES:
        try:
            out[name] = md.version(name)
        except md.PackageNotFoundError:
            out[name] = "not installed"
    return out


def hardware() -> dict:
    info = {"platform": platform.platform(), "python": platform.python_version(), "processor": platform.processor(),
            "cpu_count": os.cpu_count()}
    gpu = _run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"])
    info["gpu"] = gpu or "not detected (nvidia-smi unavailable)"
    return info


def prompt_template_hashes() -> dict:
    """sha256 of every prompt template in use. Importing the modules only reads string constants."""
    out = {}

    def add(label, module, names):
        try:
            mod = __import__(module, fromlist=["*"])
            for n in names:
                out[f"{label}.{n}"] = sha256_text(getattr(mod, n))
        except Exception as exc:  # noqa: BLE001
            out[f"{label}"] = f"unavailable: {type(exc).__name__}: {str(exc)[:80]}"

    add("rag_generate", "integration.rag.generate", ["SYSTEM_PROMPT", "USER_TEMPLATE"])
    add("qa_generation", "integration.qa.generation", ["SYSTEM_TEMPLATE", "USER_TEMPLATE"])
    add("e14a_eval", "integration.eval.base_vs_rag",
        ["BASE_SYSTEM_PROMPT", "JUDGE_SYSTEM", "CORRECTNESS_TEMPLATE", "GROUNDING_TEMPLATE"])
    add("decomposer", "query_router.decomposer", ["SYSTEM"])
    return out


def decoding_settings() -> dict:
    from integration.rag.llm_client import DEFAULT_MODEL, DEFAULT_SEED, OllamaClient

    params = inspect.signature(OllamaClient.__init__).parameters
    return {"model_default": DEFAULT_MODEL, "temperature": params["temperature"].default, "seed": DEFAULT_SEED,
            "top_p": "not set in code (Ollama server default applies; the value is not recorded)",
            "max_tokens": "not set in code (Ollama default num_predict applies; not recorded)",
            "source": "defaults of integration/rag/llm_client.OllamaClient, passed as options={temperature, seed}"}


def quantization(model: str, ollama_show=None) -> str:
    try:
        if ollama_show is None:
            import ollama
            ollama_show = ollama.show
        details = getattr(ollama_show(model), "details", None)
        return getattr(details, "quantization_level", None) or "unavailable: server returned no quantization_level"
    except Exception as exc:  # noqa: BLE001
        return f"unavailable: {type(exc).__name__}: {str(exc)[:80]}"


def index_info(index_dir: Path) -> dict:
    index_dir = Path(index_dir)
    meta_path, faiss_path = index_dir / "chunk_metadata.json", index_dir / "faiss.index"
    out = {"path": str(index_dir.relative_to(ROOT)).replace("\\", "/") if index_dir.is_absolute() and ROOT in index_dir.parents
           else str(index_dir)}
    if faiss_path.exists():
        out["faiss.index_sha256"] = sha256_file(faiss_path)
    if meta_path.exists():
        out["chunk_metadata_sha256"] = sha256_file(meta_path)
        from integration.corpus_labels import corpus_label
        records = json.loads(meta_path.read_text(encoding="utf-8"))
        comp: dict[str, int] = {}
        for r in records:
            comp[corpus_label(r)] = comp.get(corpus_label(r), 0) + 1
        out.update(chunks=len(records), composition=comp)
    return out


def _as_dict(cfg) -> dict | None:
    if cfg is None:
        return None
    return cfg.as_dict() if hasattr(cfg, "as_dict") else dict(cfg)


def build_manifest(*, generator_model: str | None = None, rag_config=None, qa_config=None, index_dirs=(), extra: dict | None = None,
                   ollama_show=None) -> dict:
    from integration.rag.context_builder import DEFAULT_TOP_N
    from integration.rag.llm_client import DEFAULT_MODEL

    model = generator_model or DEFAULT_MODEL
    rag, qa = _as_dict(rag_config), _as_dict(qa_config)
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": {"name": model, "quantization": quantization(model, ollama_show)},
        "decoding": decoding_settings(),
        "prompt_template_sha256": prompt_template_hashes(),
        "context_budget": {"shared_top_n": DEFAULT_TOP_N,
                           "per_source_budget": ({"db_blocks": rag["budget_db_blocks"], "doc_blocks": rag["budget_doc_blocks"]}
                                                 if rag and rag.get("budget_db_blocks") is not None else None),
                           "qa_top_n_context": (qa or {}).get("top_n_context")},
        "retrieval_flags": {"rag_config": rag, "qa_config": qa},
        "indexes": [index_info(d) for d in index_dirs],
        "git": git_info(),
        "packages": package_versions(),
        "hardware": hardware(),
        "extra": extra or {},
    }


def write_manifest(results_path, **kwargs) -> Path:
    path = manifest_path_for(results_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_manifest(**kwargs), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path
