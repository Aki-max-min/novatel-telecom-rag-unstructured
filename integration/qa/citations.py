"""
Sentence-level citations: parsing, provenance resolution, and VERIFICATION.

Parsing
    The generator is asked for one short atomic sentence per line, each ending
    in [E#] tags. Real models drift (tags before the full stop, several
    sentences on one line, bullets), so the parser normalises those first. A
    citation naming an id that was NOT supplied is never accepted: it is recorded
    in `invalid_citations` and dropped.

Verification (per sentence, against ONLY the evidence it cites)
    1. numbers  : every number in the sentence (after removing thousands commas,
                  trailing decimal zeros and leading zeros) must occur in the cited
                  evidence. A missing number is a hard UNSUPPORTED.
    2. lexical  : share of the sentence's content-word stems found in the cited text.
    3. NLI      : max entailment probability of the sentence against the best few
                  2-sentence WINDOWS of each cited evidence block (windows are
                  pre-ranked by lexical overlap to bound cost). The winning window is
                  returned as the exact supporting text span. NLI model:
                  MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli (CPU, deterministic).
    Status:  SUPPORTED / WEAK / UNSUPPORTED, thresholds from QAConfig.
    A sentence with no valid citation is UNSUPPORTED ("no citation").

A verifier is a heuristic, not an oracle: NLI can miss paraphrase and can be
fooled by topically-similar text. See the mutation-test results in the report for
measured detection and false-flag rates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from integration.qa.config import QAConfig

CITE_RE = re.compile(r"\[(E\d+)\]")
_CITE_RUN = r"(?:\s*\[E\d+\])+"
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_STOP = set("""a an the and or but if then of to in on at for from by with without about as is are was were be been
being do does did have has had i me my we our you your it its this that these those there here what which who when
where why how can could should would will may might must not no yes so than too very just also into out up per any
each other some such only own same s t they them their he she his her""".split())

INSUFFICIENT_MARKER = "INSUFFICIENT_EVIDENCE"
NOT_ANSWERED_RE = re.compile(r"^\s*NOT[ _]ANSW\w*\s*:\s*(.+)$", re.I)  # tolerant: local models mistype the marker

SUPPORTED, WEAK, UNSUPPORTED = "SUPPORTED", "WEAK", "UNSUPPORTED"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _normalise_line(line: str) -> str:
    line = re.sub(r"^\s*(?:[-*•]+|\d{1,2}[.)])\s+", "", line)              # bullets / "1." numbering
    line = re.sub(r"\*\*|__|`", "", line)                                         # markdown emphasis
    # citations written BEFORE the full stop ("... Active [E1].") -> after it ("... Active. [E1]")
    line = re.sub(rf"({_CITE_RUN})\s*([.!?])", r"\2\1", line)
    return line.strip()


def split_sentences(line: str) -> list[str]:
    """Split a normalised line into sentence chunks, keeping each sentence's trailing tags with it."""
    parts = re.split(rf"(?<=\])\s+(?=[A-Z0-9\"'(])|(?<=[.!?])\s+(?=[A-Z0-9\"'(])", line)
    out, buf = [], ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if re.fullmatch(_CITE_RUN, p.strip()):       # stray tag-only fragment belongs to the previous sentence
            buf = (buf + " " + p).strip()
            continue
        if buf:
            out.append(buf)
        buf = p
    if buf:
        out.append(buf)
    return out


def parse_answer(raw: str, valid_ids: set[str]) -> dict:
    """-> {sentences:[{text,citations,invalid_citations}], unanswered:[str], insufficient:bool}"""
    text = (raw or "").strip()
    if INSUFFICIENT_MARKER in text.upper().replace(" ", "_") and len(text) < 80:
        return {"sentences": [], "unanswered": [], "insufficient": True}

    sentences, unanswered = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = NOT_ANSWERED_RE.match(line)
        if m:
            unanswered.append(re.sub(_CITE_RUN, "", m.group(1)).strip())
            continue
        for chunk in split_sentences(_normalise_line(line)):
            ids = CITE_RE.findall(chunk)
            clean = re.sub(_CITE_RUN, "", chunk)
            clean = re.sub(r"\s+", " ", clean).strip()
            if not clean:
                continue
            ordered, seen = [], set()
            for i in ids:
                if i not in seen:
                    ordered.append(i)
                    seen.add(i)
            sentences.append({
                "text": clean,
                "citations": [i for i in ordered if i in valid_ids],
                "invalid_citations": [i for i in ordered if i not in valid_ids],
            })
    return {"sentences": sentences, "unanswered": unanswered, "insufficient": False}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def canonical_number(token: str) -> str:
    t = token.replace(",", "")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    t = t.lstrip("0") or "0"
    return t


def numbers_in(text: str) -> set[str]:
    return {canonical_number(m) for m in _NUM_RE.findall(re.sub(_CITE_RUN, " ", text or ""))}


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOP and len(w) > 2}


def lexical_overlap(sentence: str, evidence_text: str) -> float:
    s = _stems(sentence)
    if not s:
        return 0.0
    return len(s & _stems(evidence_text)) / len(s)


def verbalise_structured(item: dict) -> str:
    """Row -> short declarative text so NLI can compare it with a natural-language sentence."""
    md = item["metadata"]
    table = md.get("table_name") or item["dataset"]
    skip = {"table_name", "row_id", "columns_used", "query_or_lookup", "raw_scores", "origin_subquery", "provenance",
            "document_id", "chunk_id", "page_number", "entity_id", "ontology_concepts", "relationships",
            "evidence_id", "fusion", "page_range", "page_overlap", "title", "document_type", "source_authority"}
    cols = [c for c in (md.get("columns_used") or []) if c not in skip]
    parts = [f"{c.replace('_', ' ')} is {md[c]}" for c in cols if c in md and md[c] is not None]
    if item.get("retrieval_method") == "aggregate":
        return item["content"]
    return f"In the {table.replace('_', ' ')} table, row {md.get('row_id')}: " + "; ".join(parts) + "."


def evidence_text(item: dict) -> str:
    if item["source"] == "structured":
        return item["content"] + " " + verbalise_structured(item)
    return item["content"]


def _windows(text: str, size: int = 2, cap: int = 60) -> list[str]:
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+|\s\|\s", text) if s and s.strip()]
    if not sents:
        return [text[:1200]] if text else []
    wins = [" ".join(sents[i:i + size]) for i in range(max(1, len(sents) - size + 1))]
    return wins[:cap]


# ---------------------------------------------------------------------------
# NLI (shared, lazily loaded, CPU)
# ---------------------------------------------------------------------------
def _nli():
    from integration.eval.faithfulness_nli import _get_pipeline
    return _get_pipeline()


def entailment(premise: str, hypothesis: str) -> tuple[float, str]:
    pipe = _nli()
    result = pipe(premise[:1800], text_pair=hypothesis, truncation=True)
    if result and isinstance(result[0], list):
        result = result[0]
    scores = {r["label"].lower(): r["score"] for r in result}
    return float(scores.get("entailment", 0.0)), max(scores, key=scores.get)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
@dataclass
class SentenceVerdict:
    status: str
    numbers_ok: bool
    missing_numbers: list
    lexical: float
    nli_entailment: float | None
    best_evidence_id: str | None
    supporting_span: str | None
    reason: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def verify_sentence(sentence: str, cited: list[dict], cfg: QAConfig) -> SentenceVerdict:
    """`cited` = the evidence items this sentence cites (already filtered to valid ids)."""
    if not cited:
        return SentenceVerdict(UNSUPPORTED, False, [], 0.0, None, None, None, "no valid citation")

    texts = {it["metadata"]["evidence_id"]: evidence_text(it) for it in cited}
    joined = " ".join(texts.values())

    sent_nums = numbers_in(sentence)
    ev_nums = numbers_in(joined)
    missing = sorted(n for n in sent_nums if n not in ev_nums)
    numbers_ok = not missing

    lex_by = {eid: lexical_overlap(sentence, t) for eid, t in texts.items()}
    best_lex_eid = max(lex_by, key=lex_by.get)
    lexical = lex_by[best_lex_eid]

    nli_best, span, span_eid = None, None, None
    if cfg.verifier == "nli":
        nli_best = 0.0
        for eid, text in texts.items():
            wins = _windows(text)
            ranked = sorted(wins, key=lambda w: lexical_overlap(sentence, w), reverse=True)[:3]
            for w in ranked:
                p, _label = entailment(w, sentence)
                if p > nli_best or span is None:
                    nli_best, span, span_eid = p, w, eid
    else:
        eid = best_lex_eid
        wins = _windows(texts[eid])
        span = max(wins, key=lambda w: lexical_overlap(sentence, w)) if wins else texts[eid][:400]
        span_eid = eid

    if not numbers_ok:
        return SentenceVerdict(UNSUPPORTED, False, missing, lexical, nli_best, span_eid, span,
                               f"number(s) not in cited evidence: {missing}")

    if cfg.verifier == "nli":
        if nli_best >= cfg.nli_supported_threshold:
            status, why = SUPPORTED, f"entailment {nli_best:.2f} >= {cfg.nli_supported_threshold}"
        elif nli_best >= cfg.nli_weak_threshold or lexical >= cfg.lexical_supported_threshold:
            status, why = WEAK, f"entailment {nli_best:.2f}, lexical {lexical:.2f}: partial support"
        else:
            status, why = UNSUPPORTED, f"entailment {nli_best:.2f} and lexical {lexical:.2f} both low"
    else:
        if lexical >= cfg.lexical_supported_threshold:
            status, why = SUPPORTED, f"lexical {lexical:.2f}"
        elif lexical >= cfg.lexical_weak_threshold:
            status, why = WEAK, f"lexical {lexical:.2f}"
        else:
            status, why = UNSUPPORTED, f"lexical {lexical:.2f} low"

    return SentenceVerdict(status, True, [], round(lexical, 3), None if nli_best is None else round(nli_best, 3),
                           span_eid, (span or "")[:500], why)


def verify_answer(parsed: dict, evidence_by_id: dict, cfg: QAConfig) -> list[dict]:
    """Attach a verdict to every parsed sentence. Returns the enriched sentence list."""
    out = []
    for s in parsed["sentences"]:
        cited = [evidence_by_id[i] for i in s["citations"] if i in evidence_by_id]
        v = verify_sentence(s["text"], cited, cfg)
        if s["invalid_citations"] and v.status != UNSUPPORTED:
            v.reason += f" (ignored invalid citation(s) {s['invalid_citations']})"
        out.append({**s, "support_status": v.status, "support": v.as_dict()})
    return out


# ---------------------------------------------------------------------------
# Provenance resolution for display
# ---------------------------------------------------------------------------
def resolve_provenance(item: dict) -> dict:
    """Human + machine readable provenance for one evidence item."""
    md = item["metadata"]
    base = {
        "evidence_id": md.get("evidence_id"), "source": item["source"], "dataset": item["dataset"],
        "retrieval_method": item["retrieval_method"], "score": item["score"], "raw_scores": md.get("raw_scores"),
        "origin_subquery": md.get("origin_subquery"), "text": item["content"],
    }
    if item["source"] == "structured":
        base.update({
            "kind": "table_row", "table": md.get("table_name"), "row_id": md.get("row_id"),
            "columns_used": md.get("columns_used"), "query_or_lookup": md.get("query_or_lookup"),
            "label": f"table {md.get('table_name')}"
                     + (f", row {md.get('row_id')}" if md.get("row_id") else ", aggregate count"),
        })
    else:
        prov = md.get("provenance") or {}
        page = md.get("page_number")
        rng = md.get("page_range")
        page_txt = ""
        if page is not None:
            page_txt = f", pp. {rng[0]}-{rng[-1]}" if rng and len(rng) > 1 else f", p. {page}"
        base.update({
            "kind": "document_chunk", "corpus": prov.get("corpus"), "document_id": md.get("document_id"),
            "title": md.get("title"), "chunk_id": md.get("chunk_id"), "page_number": page, "page_range": rng,
            "source_authority": md.get("source_authority"), "relationships": md.get("relationships"),
            "ontology_concepts": md.get("ontology_concepts"),
            "label": f"{prov.get('corpus')}: {md.get('document_id')} / {md.get('chunk_id')}{page_txt}",
        })
    return base
