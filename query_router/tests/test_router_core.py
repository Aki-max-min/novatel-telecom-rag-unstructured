"""Router interface, label derivation, JSON repair, fallback chain, Laya wrapper (mocked). No models loaded."""

import pytest

from query_router import registry
from query_router.base import (BaseRouter, RouteDecision, RouterUnavailable, derive_label, head_confidence,
                               parse_json_object)
from query_router.laya_router import LayaRouter, p_yes_from_answer


# ---- label derivation ------------------------------------------------------
@pytest.mark.parametrize("flags,expected", [
    ((False, True, True), "out_of_scope"), ((False, False, False), "out_of_scope"),
    ((True, True, True), "hybrid"), ((True, True, False), "structured"),
    ((True, False, True), "unstructured"),
])
def test_derive_label(flags, expected):
    assert derive_label(*flags)[0] == expected


def test_in_scope_with_no_flag_is_hybrid_and_marked_inconsistent():
    assert derive_label(True, False, False) == ("hybrid", True)


def test_from_label_roundtrip_and_schema_keys():
    for label in ("structured", "unstructured", "hybrid", "out_of_scope"):
        d = RouteDecision.from_label(label, router_name="t", model_id="m")
        assert d.label == label
        assert set(d.as_dict()) >= {"in_scope", "needs_structured", "needs_unstructured", "label", "confidence",
                                    "reasoning", "sub_queries", "router_name", "model_id", "latency_ms"}
        assert set(d.sub_queries) == {"structured", "unstructured"}


def test_oos_clears_need_flags():
    d = RouteDecision.from_probs(0.1, 0.9, 0.9, router_name="t", model_id="m")
    assert d.label == "out_of_scope" and not d.needs_structured and not d.needs_unstructured


def test_confidence_is_weakest_head():
    assert head_confidence(0.99, 0.55, 0.99, "hybrid") == pytest.approx(0.55)
    assert head_confidence(0.02, 0.5, 0.5, "out_of_scope") == pytest.approx(0.98)


# ---- JSON repair --------------------------------------------------------------
@pytest.mark.parametrize("raw", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    'Sure! Here you go: {"a": 1} hope that helps',
    '{"a": 1,}',
    "{'a': 1}",
])
def test_parse_json_object_repairs(raw):
    assert parse_json_object(raw) == {"a": 1}


def test_parse_json_python_literals():
    assert parse_json_object("{'a': True, 'b': None}") == {"a": True, "b": None}


@pytest.mark.parametrize("raw", ["no json here", "", None, "{broken"])
def test_parse_json_unrepairable_raises(raw):
    with pytest.raises(ValueError):
        parse_json_object(raw)


# ---- fallback chain ------------------------------------------------------------
class _Fake(BaseRouter):
    def __init__(self, name, probs=None, fail=False):
        self.name, self.model_id, self._probs, self._fail = name, name, probs, fail

    def available(self):
        return (False, "down") if self._fail else (True, "")

    def _predict(self, query):
        return {"p_in_scope": self._probs[0], "p_structured": self._probs[1], "p_unstructured": self._probs[2]}


def test_auto_router_skips_unavailable_and_records_it(monkeypatch):
    fakes = {"a": _Fake("a", fail=True), "b": _Fake("b", (0.9, 0.9, 0.1)), "c": _Fake("c", (0.9, 0.1, 0.9))}
    monkeypatch.setattr(registry, "build_router", lambda name, cfg=None: fakes[name])
    d = registry.AutoRouter(("a", "b", "c")).route("anything")
    assert d.router_name == "b" and d.label == "structured"
    assert d.extra["chain_skipped"][0]["router"] == "a"


def test_auto_router_all_fail_raises(monkeypatch):
    fakes = {"a": _Fake("a", fail=True), "b": _Fake("b", fail=True)}
    monkeypatch.setattr(registry, "build_router", lambda name, cfg=None: fakes[name])
    with pytest.raises(RouterUnavailable):
        registry.AutoRouter(("a", "b")).route("x")


def test_unknown_router_name_is_an_error():
    with pytest.raises(KeyError):
        registry.build_router("definitely_not_a_router")


def test_rule_router_always_available_and_deterministic():
    r = registry.build_router("rule")
    assert r.available()[0]
    a, b = r.route("What is the weather in Paris?"), r.route("What is the weather in Paris?")
    assert a.label == b.label == "out_of_scope"


# ---- Laya wrapper (mock agent: no weights) -----------------------------------------
def test_p_yes_prefers_explicit_probabilities():
    assert p_yes_from_answer({"choice": "no", "confidence": 0.9, "probabilities": {"yes": 0.7, "no": 0.3}}) \
        == pytest.approx(0.7)


def test_p_yes_falls_back_to_choice_and_confidence():
    assert p_yes_from_answer({"choice": "yes", "confidence": 0.8}) == pytest.approx(0.8)
    assert p_yes_from_answer({"choice": "no", "confidence": 0.8}) == pytest.approx(0.2)


class _Agent:
    def predict(self, query, questions):
        probs = {"in_scope": 0.95, "needs_structured": 0.9, "needs_unstructured": 0.8}
        return {"answers": {h: {"choice": "yes", "probabilities": {"yes": probs[h], "no": 1 - probs[h]}}
                            for h in questions}}


def test_laya_router_uses_agent_and_returns_hybrid():
    router = LayaRouter(mode="zero_shot")
    router._agent = _Agent()
    d = router.route("Customer 1025 has an overdue invoice - what late-fee policy applies?")
    assert d.label == "hybrid" and d.router_name == "laya_zeroshot"
    assert d.confidence == pytest.approx(0.8)


def test_laya_finetuned_unavailable_without_checkpoint(tmp_path):
    router = LayaRouter(mode="fine_tuned", checkpoint=tmp_path / "missing")
    ok, reason = router.available()
    assert not ok and "not found" in reason
    with pytest.raises(RouterUnavailable):
        router.route("x")
