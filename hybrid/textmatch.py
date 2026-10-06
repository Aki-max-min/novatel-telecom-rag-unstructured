"""
One shared keyword matcher for hybrid/ (E13 Phase 8a).

Why: query_gate.py mixed word-START matching (concept patterns) with whole-word
matching (_PERSONAL_FACT ended in \\b), so plurals such as "complaints", "tickets",
"invoices" or "payments" were not recognised as personal facts while the singular was.
Every keyword list in query_gate.py and router.py now goes through this module.

Term syntax (compile_terms / has_term / find_term):
  * a term is a plain phrase: "recharge", "top-up", "data usage";
  * word-boundary at the START - never bare substring matching ("planet" is not "plan",
    "reticket" is not "ticket");
  * by default the LAST word may carry a regular inflection - s / es / ed / ing, with the
    silent-e and -y rules ("recharge" -> recharges, recharged, recharging; "expiry" -> expiries) -
    and the match must END at a word boundary after it ("billion" is not "bill");
  * hyphen / space are flexible: "top-up" also matches "top up" and "topup"; "data usage"
    also matches "data-usage";
  * an INTENTIONALLY open stem is written with a trailing "*": "expir*" matches expire, expired,
    expiry, expiration (anything starting with the stem);
  * inflect=False gives exact whole words, for pronouns and grammar words ("i", "my", "me") where
    inflection would be wrong ("i" + "s" = "is").
"""

import re
from functools import lru_cache

_SEP = re.compile(r"([\s-]+)")


def _inflected_last(word: str) -> str:
    esc = re.escape(word)
    if len(word) > 2 and word.endswith("e"):
        return re.escape(word[:-1]) + r"(?:e|es|ed|ing)"
    if len(word) > 2 and word.endswith("y") and word[-2] not in "aeiou":
        return re.escape(word[:-1]) + r"(?:y|ies|ied|ying)"
    return esc + r"(?:s|es|ed|ing)?"


def _term_pattern(term: str, inflect: bool) -> str:
    term = term.strip().lower()
    open_stem = term.endswith("*")
    if open_stem:
        term = term[:-1]
    parts = _SEP.split(term)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # separator: hyphen -> optional, space -> required
            out.append(r"[-\s]?" if "-" in part and " " not in part else r"[-\s]+")
            continue
        is_last = i == len(parts) - 1
        if open_stem and is_last:
            out.append(re.escape(part) + r"\w*")
        elif inflect and is_last:
            out.append(_inflected_last(part))
        else:
            out.append(re.escape(part))
    return "".join(out)


@lru_cache(maxsize=None)
def _compile(terms: tuple, inflect: bool):
    body = "|".join(_term_pattern(t, inflect) for t in terms)
    return re.compile(r"\b(?:" + body + r")\b", re.I)


def compile_terms(terms, inflect: bool = True):
    """Compiled regex matching any term (see module docstring for the term syntax)."""
    return _compile(tuple(terms), inflect)


def find_term(text: str, terms, inflect: bool = True):
    """First match object (earliest in the text) or None."""
    return compile_terms(terms, inflect).search(text or "")


def has_term(text: str, terms, inflect: bool = True) -> bool:
    return find_term(text, terms, inflect) is not None
