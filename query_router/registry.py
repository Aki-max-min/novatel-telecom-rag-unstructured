"""
Router registry, ensemble, and the automatic fallback chain.

Every router implements query_router.base.BaseRouter. `build_router(name)` is the
single place that maps a config string to an implementation; the UI and the
backend both go through it, so a router that cannot load is reported as
UNAVAILABLE (with the reason) rather than silently replaced.

AutoRouter walks a configured chain, e.g.
    laya_finetuned -> embedding -> rule
and returns the first router that both loads AND produces a decision. The
decision's `router_name` is always the router that ACTUALLY answered, and
`extra["chain_skipped"]` lists the routers that were tried and why they were
skipped -- the UI shows this so the user can see which router decided.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from query_router.base import BaseRouter, RouteDecision, RouterUnavailable
from query_router.embedding_router import EmbeddingPrototypeRouter
from query_router.laya_router import LayaRouter
from query_router.nli_router import ZeroShotNLIRouter
from query_router.ollama_router import OllamaLLMRouter, RouterError
from query_router.rule_router import RuleRouter
from query_router.setfit_router import SetFitRouter

# Default chain is set from the held-out evaluation (see docs / report): the
# fine-tuned Laya first (if its checkpoint exists), then the cheapest router that
# beat the rule baseline, then the rule router as the always-available floor.
DEFAULT_CHAIN = ("laya_finetuned", "embedding", "rule")

_INSTANCES: dict = {}


def _factories(cfg: dict) -> dict[str, Callable[[], BaseRouter]]:
    return {
        "laya_finetuned": lambda: LayaRouter("fine_tuned", cfg.get("laya_checkpoint")),
        "laya_zeroshot": lambda: LayaRouter("zero_shot"),
        "ollama_qwen3b": lambda: OllamaLLMRouter("qwen2.5:3b-instruct"),
        "ollama_llama3b": lambda: OllamaLLMRouter("llama3.2:3b"),
        "ollama": lambda: OllamaLLMRouter(cfg.get("ollama_router_model", "qwen2.5:3b-instruct")),
        "zeroshot_nli": lambda: ZeroShotNLIRouter(),
        "embedding": lambda: EmbeddingPrototypeRouter(allow_fallback_model=True),
        "setfit": lambda: SetFitRouter(),
        "rule": lambda: RuleRouter(),
    }


def router_names() -> list[str]:
    return list(_factories({}).keys()) + ["ensemble", "auto"]


def build_router(name: str, cfg: Optional[dict] = None) -> BaseRouter:
    cfg = cfg or {}
    if name == "auto":
        return AutoRouter(cfg.get("chain", DEFAULT_CHAIN), cfg)
    if name == "ensemble":
        return EnsembleRouter(cfg.get("ensemble_members", ("laya_finetuned", "embedding")), cfg=cfg)
    key = (name, tuple(sorted((k, str(v)) for k, v in cfg.items())))
    if key not in _INSTANCES:
        factories = _factories(cfg)
        if name not in factories:
            raise KeyError(f"unknown router '{name}'. Known: {router_names()}")
        _INSTANCES[key] = factories[name]()
    return _INSTANCES[key]


def router_status(name: str, cfg: Optional[dict] = None) -> tuple[bool, str]:
    """(available, reason) without raising -- used by the UI to disable choices."""
    try:
        return build_router(name, cfg).available()
    except Exception as exc:  # pragma: no cover
        return False, str(exc)


class AutoRouter(BaseRouter):
    name = "auto"

    def __init__(self, chain, cfg: Optional[dict] = None):
        self.chain = tuple(chain)
        self.cfg = cfg or {}
        self.model_id = "fallback chain: " + " -> ".join(self.chain)

    def available(self):
        for name in self.chain:
            ok, _ = router_status(name, self.cfg)
            if ok:
                return True, ""
        return False, "no router in the chain is available"

    def _predict(self, query: str) -> dict:  # not used; route() is overridden
        raise NotImplementedError

    def route(self, query: str) -> RouteDecision:
        skipped = []
        for name in self.chain:
            try:
                router = build_router(name, self.cfg)
                decision = router.route(query)
            except (RouterUnavailable, RouterError, Exception) as exc:  # noqa: BLE001
                skipped.append({"router": name, "reason": str(exc)[:200]})
                continue
            decision.extra["chain_skipped"] = skipped
            decision.extra["chain"] = list(self.chain)
            return decision
        raise RouterUnavailable("every router in the chain failed: " + "; ".join(f"{s['router']}: {s['reason']}" for s in skipped))


class EnsembleRouter(BaseRouter):
    """Weighted mean of member head-probabilities. A failing member is skipped."""

    name = "ensemble"

    def __init__(self, members, weights=None, cfg: Optional[dict] = None):
        self.members = tuple(members)
        self.weights = tuple(weights) if weights else tuple(1.0 for _ in self.members)
        self.cfg = cfg or {}
        self.model_id = "ensemble(" + "+".join(self.members) + ")"
        self.name = "ensemble"

    def available(self):
        for m in self.members:
            ok, _ = router_status(m, self.cfg)
            if ok:
                return True, ""
        return False, "no ensemble member is available"

    def _predict(self, query: str) -> dict:
        total_w, acc = 0.0, [0.0, 0.0, 0.0]
        used, skipped = [], []
        for member, w in zip(self.members, self.weights):
            try:
                d = build_router(member, self.cfg).route(query)
            except Exception as exc:  # noqa: BLE001
                skipped.append({"router": member, "reason": str(exc)[:120]})
                continue
            acc[0] += w * d.extra["p_in_scope"]
            acc[1] += w * d.extra["p_structured"]
            acc[2] += w * d.extra["p_unstructured"]
            total_w += w
            used.append(member)
        if total_w == 0:
            raise RouterUnavailable("no ensemble member produced a decision")
        return {"p_in_scope": acc[0] / total_w, "p_structured": acc[1] / total_w, "p_unstructured": acc[2] / total_w,
                "extra": {"ensemble_used": used, "ensemble_skipped": skipped}}
