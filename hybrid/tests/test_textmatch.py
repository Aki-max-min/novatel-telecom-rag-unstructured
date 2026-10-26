"""
Property tests for hybrid/textmatch.py. The cases are GENERATED from the keyword lists that
query_gate.py and router.py actually use - not from any benchmark question:

  * every inflecting keyword matches its singular AND its plural / -ed / -ing forms;
  * a near miss does not match: a prefix ("re" + keyword: "reticket") and a non-inflection
    suffix (keyword + "et": "planet", "ticketet");
  * exact (inflect=False) lists match only the exact word;
  * intentionally open stems ("expir*") match anything that starts with the stem.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import query_gate  # noqa: E402
import router  # noqa: E402
from textmatch import compile_terms, has_term  # noqa: E402

INFLECTING_LISTS = {
    "query_gate.KEYWORD_CONCEPT_MAP": list(query_gate.KEYWORD_CONCEPT_MAP),
    "query_gate.PERSONAL_FACT_TERMS": query_gate.PERSONAL_FACT_TERMS,
    "query_gate.POSSESSIVE_NUMBER_TERMS": query_gate.POSSESSIVE_NUMBER_TERMS,
    "query_gate.COMMUNICATION_CHANNELS": query_gate.COMMUNICATION_CHANNELS,
    "query_gate.COMBO_RULES.any_of": [t for r in query_gate.COMBO_RULES for t in r["any_of"]],
    "query_gate.COMBO_RULES.and_any_of": [t for r in query_gate.COMBO_RULES for t in r["and_any_of"]],
    **{f"router.INTENT_TERMS[{k}]": v for k, v in router.INTENT_TERMS.items()},
}
EXACT_LISTS = {
    "query_gate.FIRST_PERSON_TERMS": query_gate.FIRST_PERSON_TERMS,
    "query_gate.POSSESSIVE_TERMS": query_gate.POSSESSIVE_TERMS,
    "query_gate.UNSOLICITED_QUALIFIERS": query_gate.UNSOLICITED_QUALIFIERS,
    "router.THIRD_PARTY_TERMS": router.THIRD_PARTY_TERMS,
}


def forms(term):
    """singular, plural, -ed, -ing forms of the LAST word, following the matcher's rules."""
    if len(term) > 2 and term.endswith("e"):
        return [term, term + "s", term + "d", term[:-1] + "ing"]
    if len(term) > 2 and term.endswith("y") and term[-2] not in "aeiou":
        return [term, term[:-1] + "ies", term[:-1] + "ied", term[:-1] + "ying"]
    return [term, term + "s", term + "ed", term + "ing"]


class TestTextMatchProperties(unittest.TestCase):

    def test_every_inflecting_keyword_matches_singular_and_inflected_and_not_near_misses(self):
        checked, failures = 0, []
        for list_name, terms in INFLECTING_LISTS.items():
            for term in terms:
                if term.endswith("*"):
                    continue  # open stems are tested separately
                for form in forms(term):
                    checked += 1
                    if not has_term(f"please check the {form} today", [term]):
                        failures.append(f"{list_name}: '{term}' should match '{form}'")
                for near in ("re" + term, term + "et"):
                    checked += 1
                    if has_term(f"please check the {near} today", [term]):
                        failures.append(f"{list_name}: '{term}' must NOT match near miss '{near}'")
        print(f"\ntextmatch property test: {checked} keyword checks, {len(failures)} failures")
        self.assertGreater(checked, 500)
        self.assertEqual(failures, [])

    def test_exact_lists_match_only_the_exact_word(self):
        failures = []
        for list_name, terms in EXACT_LISTS.items():
            for term in terms:
                if not has_term(f"about {term} here", [term], inflect=False):
                    failures.append(f"{list_name}: '{term}' exact match failed")
                for near in (term + "s", "re" + term, term + "et"):
                    if has_term(f"about {near} here", [term], inflect=False):
                        failures.append(f"{list_name}: '{term}' must not match '{near}' when inflect=False")
        self.assertEqual(failures, [])

    def test_open_stem_is_explicit(self):
        for word in ("expire", "expires", "expired", "expiry", "expiration", "expiring"):
            self.assertTrue(has_term(f"it {word} soon", ["expir*"]), word)
        self.assertFalse(has_term("it reexpired soon", ["expir*"]))

    def test_the_motivating_bug_plural_equals_singular(self):
        for singular in ("ticket", "complaint", "invoice", "payment", "bill", "plan", "order", "recharge"):
            self.assertTrue(has_term(f"are my {singular} fine", [singular]))
            self.assertTrue(has_term(f"are my {singular}s fine", [singular]))
        self.assertFalse(has_term("the planet is far", ["plan"]))
        self.assertFalse(has_term("one billion people", ["bill"]))
        self.assertFalse(has_term("we reticket it", ["ticket"]))

    def test_hyphen_and_space_are_flexible(self):
        for text in ("a top-up", "a top up", "a topup", "two top-ups", "top ups"):
            self.assertTrue(has_term(text, ["top-up"]), text)
        for text in ("data usage", "data-usage", "data  usage limits"):
            self.assertTrue(has_term(text, ["data usage"]), text)

    def test_no_bare_substring_matching(self):
        self.assertFalse(has_term("replan", ["plan"]))
        self.assertFalse(has_term("simulation", ["sim"]))
        self.assertTrue(has_term("two SIMs", ["sim"]))

    def test_compile_is_cached(self):
        self.assertIs(compile_terms(["plan"]), compile_terms(["plan"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
