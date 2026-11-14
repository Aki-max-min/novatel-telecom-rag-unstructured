"""
Fine-tune Laya as the NovaTel query router.

    python -m query_router.train_laya --epochs 8 --out models/laya_router_ft_e8

DATA: data/eval/router_train.jsonl ONLY. router_val.jsonl is used afterwards, by
the evaluation script, to choose between runs/hyper-parameters; router_test.jsonl
is never read here. Laya itself holds out ~10% of THESE training rows to fit its
per-question-type confidence temperature (TrainConfig.calib_frac) -- that slice
is part of train, not val/test.

HARDWARE: the project machine has an 8 GB GPU shared with the Ollama server, so
this script first asks Ollama to unload any resident model (keep_alive=0). If
full fine-tuning runs out of GPU memory, retry with --freeze-encoder (trains only
the decision head -- the vendor's documented option for small GPUs) or a smaller
--micro-batch.

The checkpoint is written under models/ which is git-ignored: weights are never
committed; this script + the config in the report are the reproduction recipe.

API per the vendor docs (nandhakishorm.github.io/laya/reference/train/):
    finetune(data, model_dir, output_dir, config=TrainConfig(...), device="auto")
    JSONL row: {"state": str, "questions": {...}, "expected": {question_id: option_label}}
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from query_router.laya_router import BASE_MODEL_ID, LAYA_QUESTIONS, NO, YES

ROOT = Path(__file__).resolve().parents[1]
TRAIN_PATH = ROOT / "data" / "eval" / "router_train.jsonl"
WORK_DIR = ROOT / "models"
LAYA_TRAIN_JSONL = WORK_DIR / "laya_train.jsonl"


def build_laya_jsonl(src: Path = TRAIN_PATH, dst: Path = LAYA_TRAIN_JSONL) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(src, "r", encoding="utf-8") as fin, open(dst, "w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            r = json.loads(line)
            assert r["split"] == "train", "refusing to train on a non-train row"
            row = {
                "state": r["query"],
                "questions": LAYA_QUESTIONS,
                "expected": {
                    "in_scope": YES if r["in_scope"] else NO,
                    "needs_structured": YES if r["needs_structured"] else NO,
                    "needs_unstructured": YES if r["needs_unstructured"] else NO,
                },
            }
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def unload_ollama_models() -> list:
    """Free GPU memory for training. Returns the names that were unloaded."""
    unloaded = []
    try:
        import ollama
        for m in ollama.ps().models:
            ollama.generate(model=m.model, prompt="", keep_alive=0)
            unloaded.append(m.model)
    except Exception as exc:  # server not running is fine
        unloaded.append(f"(ollama not reachable or nothing loaded: {exc})")
    return unloaded


def base_checkpoint_dir() -> str:
    from huggingface_hub import snapshot_download
    return snapshot_download(BASE_MODEL_ID, ignore_patterns=["multilingual/*", "typed-decisions/*"])


def gpu_report() -> dict:
    import torch
    if not torch.cuda.is_available():
        return {"cuda": False}
    props = torch.cuda.get_device_properties(0)
    free, total = torch.cuda.mem_get_info()
    return {"cuda": True, "name": props.name, "total_gib": round(total / 2**30, 2), "free_gib": round(free / 2**30, 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--micro-batch", type=int, default=4)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--encoder-lr", type=float, default=2.5e-5)
    ap.add_argument("--head-lr", type=float, default=1e-4)
    ap.add_argument("--loss", default="rlcd", choices=["rlcd", "soft-ce"])
    ap.add_argument("--freeze-encoder", action="store_true")
    ap.add_argument("--out", default=str(WORK_DIR / "laya_router_finetuned"))
    ap.add_argument("--device", default="auto")
    args = ap.parse_args()

    from laya.train import TrainConfig, finetune

    n = build_laya_jsonl()
    unloaded = unload_ollama_models()
    time.sleep(2)
    gpu = gpu_report()
    base = base_checkpoint_dir()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    cfg = TrainConfig(
        epochs=args.epochs, micro_batch=args.micro_batch, grad_accum=args.grad_accum,
        encoder_lr=args.encoder_lr, head_lr=args.head_lr, loss=args.loss,
        freeze_encoder=args.freeze_encoder,
    )
    print(f"train rows: {n}  base: {base}\n gpu: {gpu}\n ollama unloaded: {unloaded}\n config: {cfg}", flush=True)

    start = time.time()
    report = finetune(str(LAYA_TRAIN_JSONL), base, str(out), cfg, device=args.device)
    elapsed = time.time() - start

    summary = {
        "base_model": BASE_MODEL_ID, "base_snapshot_dir": base, "train_rows": n,
        "gpu": gpu, "ollama_unloaded": unloaded, "train_seconds": round(elapsed, 1),
        "config": {k: getattr(cfg, k) for k in ("epochs", "micro_batch", "grad_accum", "encoder_lr", "head_lr",
                                                  "loss", "freeze_encoder", "calib_frac", "calib_max", "seed")},
        "laya_report": report,
    }
    with open(out / "training_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"done in {elapsed:.0f}s -> {out}", flush=True)


if __name__ == "__main__":
    main()
