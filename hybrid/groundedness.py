"""
Deterministic groundedness verifier (E13 Phase 9a): verify_answer(answer_text, context) -> {ok, problems}.

No model is involved. Every problem string starts with the rule code that raised it:

  R1  a factual sentence - one containing a digit, a currency symbol, or a status token taken from the stored
      values in the context - must carry at least one citation [F#] or [D#]
  R2  every cited id must exist in the context
  R3  every number or date in a sentence, after normalisation (currency symbol, thousands comma, trailing
      zeros of a decimal removed), must appear in the text of at least one item CITED BY THAT SENTENCE
  R4  no unmasked 10-digit sequence and no e-mail address anywhere in the answer
  R5  needs_identity: no [F#] citation (the answer contains no account value);
      refuse_other_customer: no citation at all and no digit (it shares nothing and cites nothing)

Sentence-level checking is deliberately strict: a number that exists somewhere in the context but in an item the
sentence does not cite is still a problem.
"""

import re
from decimal import Decimal, InvalidOperation

_CITATION = re.compile(r"\[([FD]\d+)\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME = re.compile(r"\d{2}:\d{2}(?::\d{2})?")
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_MSISDN = re.compile(r"(?<!\d)\d{10}(?!\d)|(?<!\d)\d{5}[ -]\d{5}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CURRENCY = re.compile(r"[₹$€£]|\bRs\.?(?=\s*\d)", re.I)


def _norm_number(raw: str) -> str:
    raw = raw.replace(",", "")
    try:
        d = Decimal(raw)
    except InvalidOperation:
        return raw
    text = format(d.normalize(), "f")
    return text


def numeric_tokens(text: str) -> set:
    """Dates, times and numbers in a text, normalised. Dates/times are kept whole and removed before numbers."""
    tokens = set()
    for rx, prefix in ((_DATE, "date:"), (_TIME, "time:")):
        for m in rx.findall(text):
            tokens.add(prefix + m)
        text = rx.sub(" ", text)
    for m in _NUMBER.findall(text):
        tokens.add(_norm_number(m))
    return tokens


def _status_tokens(context) -> set:
    tokens = set()
    for fact in context.facts:
        for key, value in fact["fields"].items():
            if "status" in key and isinstance(value, str) and value.isalpha() and len(value) >= 3:
                tokens.add(value)
    return tokens


def split_sentences(text: str) -> list:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s and s.strip()]


def verify_answer(answer_text: str, context) -> dict:
    problems = []
    valid_ids = context.ids()
    statuses = _status_tokens(context)
    status_rx = re.compile(r"\b(?:" + "|".join(re.escape(s) for s in sorted(statuses)) + r")\b") if statuses else None

    # R4 - whole answer
    if _MSISDN.search(answer_text or ""):
        problems.append("R4: unmasked 10-digit number in the answer")
    if _EMAIL.search(answer_text or ""):
        problems.append("R4: e-mail address in the answer")

    all_cited = _CITATION.findall(answer_text or "")

    # R5 - outcome-specific
    if context.outcome == "needs_identity":
        if any(c.startswith("F") for c in all_cited):
            problems.append("R5: needs_identity answer cites an account fact")
    if context.outcome == "refuse_other_customer":
        if all_cited:
            problems.append("R5: refuse_other_customer answer cites a document or fact")
        if re.search(r"\d", _CITATION.sub("", answer_text or "")):
            problems.append("R5: refuse_other_customer answer contains a number")

    for sentence in split_sentences(answer_text):
        cited = _CITATION.findall(sentence)
        bare = _CITATION.sub("", sentence)
        numbers = numeric_tokens(bare)

        factual = bool(re.search(r"\d", bare) or _CURRENCY.search(bare) or (status_rx and status_rx.search(bare)))
        if factual and not cited:                                               # R1
            problems.append(f"R1: factual sentence without a citation: {sentence!r}")

        for cid in cited:                                                       # R2
            if cid not in valid_ids:
                problems.append(f"R2: unknown id [{cid}] cited in: {sentence!r}")

        support = set()
        for cid in cited:
            item = context.item(cid)
            if item is not None:
                support |= numeric_tokens(item["text"])
        for token in sorted(numbers):                                           # R3
            if token not in support:
                problems.append(f"R3: number/date {token.split(':', 1)[-1]!r} is not in any item cited by: {sentence!r}")

    return {"ok": not problems, "problems": problems}
