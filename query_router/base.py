"""
Shared router interface.

Why this package is called `query_router` and not `router`: hybrid/ (Person B)
imports its own module with a bare `from router import route_query` after
putting hybrid/ on sys.path, so a top-level package named `router` would be
shadowed by (or would shadow) hybrid/router.py depending on import order.

A router is MULTI-LABEL, not a single-label classifier: it answers three
independent questions about the query --
    in_scope            is this something a NovaTel knowledge-base assistant covers?
    needs_structured    does it need specific records/counts from the SQL database?
    needs_unstructured  does it need policy / procedure / regulation documents?
-- and the single `label` is DERIVED from those flags:
    not in_scope                     -> "out_of_scope"
    needs_structured and needs_unstr -> "hybrid"
    only one flag                    -> that route
    in_scope but NEITHER flag        -> "hybrid"  (inconsistent output; the safe
                                         choice is to retrieve from both and let
                                         the abstention gate decide; flagged in
                                         extra["flags_inconsistent"])
A binary structured/unstructured router would make integrated questions
impossible, which is why this is not one.

Confidence of a decision is conservative: the minimum, over the heads that
matter for the derived label, of max(p, 1-p). For out_of_scope only the
in_scope head matters.
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Optional

LABELS = ("structured", "unstructured", "hybrid", "out_of_scope")
DEFAULT_FLAG_THRESHOLD = 0.5


class RouterUnavailable(RuntimeError):
    """The router cannot run in this environment (missing model/server/weights)."""


def derive_label(in_scope: bool, needs_structured: bool, needs_unstructured: bool) -> tuple[str, bool]:
    """Returns (label, flags_inconsistent)."""
    if not in_scope:
        return "out_of_scope", False
    if needs_structured and needs_unstructured:
        return "hybrid", False
    if needs_structured:
        return "structured", False
    if needs_unstructured:
        return "unstructured", False
    return "hybrid", True


def head_confidence(p_in_scope: float, p_structured: float, p_unstructured: float, label: str) -> float:
    conf = lambda p: max(p, 1.0 - p)
    if label == "out_of_scope":
        return conf(p_in_scope)
    return min(conf(p_in_scope), conf(p_structured), conf(p_unstructured))


@dataclass
class RouteDecision:
    in_scope: bool
    needs_structured: bool
    needs_unstructured: bool
    label: str
    confidence: float
    reasoning: Optional[str]
    sub_queries: dict
    router_name: str
    model_id: str
    latency_ms: float
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_probs(
        cls,
        p_in_scope: float,
        p_structured: float,
        p_unstructured: float,
        *,
        router_name: str,
        model_id: str,
        latency_ms: float = 0.0,
        reasoning: Optional[str] = None,
        threshold: float = DEFAULT_FLAG_THRESHOLD,
        extra: Optional[dict] = None,
    ) -> "RouteDecision":
        in_scope = p_in_scope >= threshold
        needs_s = p_structured >= threshold
        needs_u = p_unstructured >= threshold
        label, inconsistent = derive_label(in_scope, needs_s, needs_u)
        merged = {"p_in_scope": round(float(p_in_scope), 4), "p_structured": round(float(p_structured), 4),
                  "p_unstructured": round(float(p_unstructured), 4)}
        if inconsistent:
            merged["flags_inconsistent"] = True
        merged.update(extra or {})
        return cls(
            in_scope=in_scope,
            needs_structured=needs_s and in_scope,
            needs_unstructured=needs_u and in_scope,
            label=label,
            confidence=round(head_confidence(p_in_scope, p_structured, p_unstructured, label), 4),
            reasoning=reasoning,
            sub_queries={"structured": None, "unstructured": None},
            router_name=router_name,
            model_id=model_id,
            latency_ms=round(latency_ms, 2),
            extra=merged,
        )

    @classmethod
    def from_label(cls, label: str, **kwargs) -> "RouteDecision":
        """Build from a hard label (used by tests and as the abstention shortcut)."""
        flags = {
            "structured": (1.0, 1.0, 0.0), "unstructured": (1.0, 0.0, 1.0),
            "hybrid": (1.0, 1.0, 1.0), "out_of_scope": (0.0, 0.0, 0.0),
        }[label]
        return cls.from_probs(*flags, **kwargs)


class BaseRouter(ABC):
    """One interface for every router implementation."""

    name: str = "base"
    model_id: str = "n/a"
    size_params: Optional[int] = None  # reported in the comparison table; None = not applicable

    def available(self) -> tuple[bool, str]:
        """(usable, reason-if-not). Must not raise."""
        return True, ""

    @abstractmethod
    def _predict(self, query: str) -> dict:
        """Return {"p_in_scope","p_structured","p_unstructured", optional "reasoning","extra"}."""

    def route(self, query: str) -> RouteDecision:
        ok, reason = self.available()
        if not ok:
            raise RouterUnavailable(f"{self.name}: {reason}")
        start = time.perf_counter()
        out = self._predict(query)
        elapsed = (time.perf_counter() - start) * 1000.0
        return RouteDecision.from_probs(
            out["p_in_scope"], out["p_structured"], out["p_unstructured"],
            router_name=self.name, model_id=self.model_id, latency_ms=elapsed,
            reasoning=out.get("reasoning"), extra=out.get("extra"),
        )


# ---------------------------------------------------------------------------
# JSON repair (for LLM routers / decomposer)
# ---------------------------------------------------------------------------
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def parse_json_object(text: str) -> dict:
    """Extract and repair one JSON object from LLM output.

    Handles markdown fences, leading/trailing prose, trailing commas, single
    quotes and Python-style True/False/None. Raises ValueError (never guesses)
    if no object can be recovered.
    """
    if text is None:
        raise ValueError("empty LLM output")
    candidate = text.strip()
    fence = _FENCE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()

    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object in output: {text[:120]!r}")
    candidate = candidate[start:end + 1]

    attempts = [candidate]
    repaired = re.sub(r",\s*([}\]])", r"\1", candidate)                       # trailing commas
    attempts.append(repaired)
    swapped = re.sub(r"\bTrue\b", "true", re.sub(r"\bFalse\b", "false", re.sub(r"\bNone\b", "null", repaired)))
    attempts.append(swapped)
    attempts.append(swapped.replace("'", '"'))                                  # single quotes

    last_error = None
    for attempt in attempts:
        try:
            value = json.loads(attempt)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError as exc:
            last_error = exc
    raise ValueError(f"unrepairable JSON ({last_error}): {text[:160]!r}")


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value >= 0.5
    return str(value).strip().lower() in {"true", "yes", "y", "1"}
