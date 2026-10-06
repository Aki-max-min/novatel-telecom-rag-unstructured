"""
Tests for hybrid/context.py (assemble_context) and hybrid/groundedness.py (verify_answer).

The verifier is deterministic; the mutation tests prove it can FAIL: six grounded answers are each
mutated five ways (change an amount; remove a citation from a factual sentence; cite [F99]; append a
sentence with a number not in the context; insert an unmasked 10-digit number) and every one of the
30 mutants must be flagged, with the rule that is supposed to catch it.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from context import assemble_context  # noqa: E402
from groundedness import verify_answer  # noqa: E402
from router import route_query  # noqa: E402
from structured_adapter import fetch_customer_facts  # noqa: E402

REFUND_DOC = {
    "source": "unstructured", "record_id": "FAQ_C20_040_chunk_000", "dataset": "novatel_synthetic",
    "category": "C20", "score": 0.9, "retrieval_method": "vector",
    "content": ("# Refund timelines\n**Document ID:** FAQ_C20_040\n**Category:** C20\n"
                "Once approved, refunds to source (card/UPI/net banking) generally reflect within 5-7 working days, "
                "subject to your bank's processing time. Refunds to NovaTel Wallet are typically instant to 24 hours."),
    "metadata": {"document_id": "FAQ_C20_040", "title": "How long do refunds to my bank account typically take?"},
}


def make_result(question, customer_id, intents=None, docs=None, as_of=None):
    plan = route_query(question, customer_id)
    facts = fetch_customer_facts(customer_id, intents, as_of=as_of) if intents else []
    blocked = [] if plan.outcome == "answer" else [plan.outcome]
    return {"route_plan": plan.as_dict(), "facts": facts, "documents": docs or [], "blocked": blocked,
            "documents_are_generic": plan.outcome == "needs_identity" and bool(docs),
            "trace": {"refusal_reason": plan.refusal_reason,
                      "unrecognised_personal_request": plan.unrecognised_personal_request}}


def contexts():
    c = {}
    c["recharge"] = assemble_context(make_result("Did my last recharge go through?", 1042, ["recharge"]))
    c["kyc"] = assemble_context(make_result("Is my KYC complete?", 1042, ["kyc"]))
    c["sub"] = assemble_context(make_result("When does my plan expire?", 1042, ["subscription"], as_of="2026-10-06"))
    c["invoice"] = assemble_context(make_result("Is my latest bill paid?", 1829, ["invoice"]))
    c["failed"] = assemble_context(make_result("Did my last recharge go through?", 1056, ["recharge"]))
    c["docs"] = assemble_context(make_result("How long do refunds take?", None, docs=[REFUND_DOC]))
    c["noid"] = assemble_context(make_result("Did my last recharge go through?", None, docs=[REFUND_DOC]))
    c["refuse"] = assemble_context(make_result("What is the balance on 9756865116?", 1042))
    return c


# six grounded answers (name, context key, text)
GOOD = [
    ("recharge", "recharge",
     "Your latest recharge (ID 4254) was for ₹399.00 with status SUCCESS on 2026-04-17 11:06:00 [F1]."),
    ("kyc", "kyc",
     "Your KYC status on customer record 1042 is Pending [F1]. There is no kyc_records row on file for you [F2]."),
    ("sub", "sub",
     "Subscription 3042 has stored status Active and expiry_date 2026-10-03 [F1]. "
     "As of 2026-10-06 the expiry date has passed (derived), while the stored status remains Active [F1]."),
    ("invoice", "invoice",
     "Invoice 6740 has total 581.65 and stored payment_status Unpaid [F1]. "
     "A successful payment of 581.65 is also on file, so the records disagree [F1]."),
    ("failed", "failed",
     "Your latest recharge 4996 for Rs 949.00 has status FAILED [F1]."),
    ("docs", "docs",
     "Refunds to source generally reflect within 5-7 working days [D1]. "
     "Refunds to NovaTel Wallet are typically instant to 24 hours [D1]."),
]


def codes(result):
    return {p.split(":", 1)[0] for p in result["problems"]}


class TestContext(unittest.TestCase):

    def test_facts_get_ids_and_stored_fields_verbatim(self):
        ctx = assemble_context(make_result("Did my last recharge go through?", 1042, ["recharge"]))
        f1 = ctx.facts[0]
        self.assertEqual((f1["id"], f1["record_id"]), ("F1", "recharge_transactions:4254"))
        self.assertEqual((f1["fields"]["amount"], f1["fields"]["status"]), ("399.00", "SUCCESS"))
        self.assertIn("****4714", f1["line"])
        self.assertEqual([f["id"] for f in ctx.facts], [f"F{i}" for i in range(1, len(ctx.facts) + 1)])

    def test_derived_flags_are_labelled_and_notices_set(self):
        ctx = assemble_context(make_result("When does my plan expire?", 1042, ["subscription"], as_of="2026-10-06"))
        self.assertIs(ctx.facts[0]["derived"]["expiry_passed"], True)
        self.assertEqual(ctx.facts[0]["fields"]["status"], "Active")
        self.assertIn("expiry_passed", ctx.notices)
        inv = assemble_context(make_result("Is my latest bill paid?", 1829, ["invoice"]))
        self.assertIn("status_ledger_mismatch", inv.notices)
        kyc = assemble_context(make_result("Is my KYC complete?", 1042, ["kyc"]))
        self.assertIn("no kyc_records row", kyc.notices)

    def test_documents_get_ids_title_and_a_clean_snippet(self):
        ctx = assemble_context(make_result("How long do refunds take?", None, docs=[REFUND_DOC]), snippet_chars=400)
        d1 = ctx.documents[0]
        self.assertEqual((d1["id"], d1["document_id"]), ("D1", "FAQ_C20_040"))
        self.assertTrue(d1["title"])
        self.assertNotIn("Document ID", d1["snippet"])
        self.assertIn("5-7 working days", d1["snippet"])
        self.assertLessEqual(len(d1["snippet"]), 400)

    def test_max_docs_and_channels_stay_separate(self):
        docs = [dict(REFUND_DOC, record_id=f"X{i}_chunk_000", metadata={"document_id": f"X{i}"}) for i in range(8)]
        ctx = assemble_context(make_result("How long do refunds take?", None, docs=docs), max_docs=5)
        self.assertEqual(len(ctx.documents), 5)
        self.assertEqual(ctx.facts, [])
        self.assertTrue(all("score" not in d and "fusion_score" not in d for d in ctx.documents))

    def test_notices_for_identity_refusal_and_generic_documents(self):
        noid = assemble_context(make_result("Did my last recharge go through?", None, docs=[REFUND_DOC]))
        self.assertIn("needs_identity", noid.notices)
        self.assertIn("documents_are_generic", noid.notices)
        self.assertEqual(noid.facts, [])
        refuse = assemble_context(make_result("What is the balance on 9756865116?", 1042))
        self.assertIn("refuse_other_customer", refuse.notices)
        self.assertEqual((refuse.facts, refuse.documents), ([], []))

    def test_unrecognised_personal_request_notice(self):
        ctx = assemble_context(make_result("What is going on with my account lately?", 1042, docs=[REFUND_DOC]))
        self.assertIn("unrecognised_personal_request", ctx.notices)


class TestVerifierRules(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ctx = contexts()

    def test_good_answers_pass(self):
        for name, key, text in GOOD:
            result = verify_answer(text, self.ctx[key])
            self.assertTrue(result["ok"], f"{name}: {result['problems']}")

    def test_rule1_factual_sentence_needs_a_citation(self):
        r = verify_answer("Your latest recharge was successful on 2026-04-17.", self.ctx["recharge"])
        self.assertIn("R1", codes(r))
        r = verify_answer("The status is SUCCESS.", self.ctx["recharge"])  # status token from the stored values
        self.assertIn("R1", codes(r))
        self.assertTrue(verify_answer("I could not tell which account detail you meant.", self.ctx["recharge"])["ok"])

    def test_rule2_cited_ids_must_exist(self):
        r = verify_answer("Your latest recharge was SUCCESS [F7].", self.ctx["recharge"])
        self.assertIn("R2", codes(r))

    def test_rule3_numbers_must_appear_in_a_cited_item(self):
        r = verify_answer("Your latest recharge was for 499.00 [F1].", self.ctx["recharge"])
        self.assertIn("R3", codes(r))
        # a number that exists in the context but in an item the sentence does not cite is not enough
        r = verify_answer("Your latest recharge (ID 4254) was for 399.00 [F2].", self.ctx["recharge"])
        self.assertIn("R3", codes(r))
        # normalisation: currency symbol, thousands comma and trailing .00 are ignored
        self.assertTrue(verify_answer("The recharge was for Rs 399 [F1].", self.ctx["recharge"])["ok"])

    def test_rule4_no_unmasked_msisdn_or_email(self):
        r = verify_answer("Your recharge [F1] is on line 9146794714.", self.ctx["recharge"])
        self.assertIn("R4", codes(r))
        r = verify_answer("Write to someone@example.com about it.", self.ctx["recharge"])
        self.assertIn("R4", codes(r))
        self.assertTrue(verify_answer("Your recharge [F1] is on line ****4714.", self.ctx["recharge"])["ok"])

    def test_rule5_needs_identity_answers_carry_no_account_value(self):
        ctx = self.ctx["noid"]
        good = ("Personal details can only be looked up once you are identified. "
                "Refunds to source generally reflect within 5-7 working days [D1].")
        self.assertTrue(verify_answer(good, ctx)["ok"], verify_answer(good, ctx)["problems"])
        r = verify_answer("Your latest recharge was SUCCESS [F1].", ctx)
        self.assertIn("R5", codes(r))
        r = verify_answer("Your latest recharge was for 399.00 [D1].", ctx)
        self.assertTrue({"R3", "R5"} & codes(r))

    def test_rule5_refusal_cites_no_document_and_has_no_numbers(self):
        ctx = self.ctx["refuse"]
        self.assertTrue(verify_answer("Details can only be shared for the signed-in account.", ctx)["ok"])
        r = verify_answer("Details can only be shared for the signed-in account [D1].", ctx)
        self.assertIn("R5", codes(r))
        r = verify_answer("Details can only be shared for the signed-in account 9756865116.", ctx)
        self.assertIn("R4", codes(r))


def mutate_amount(text):
    """Change the first plain number that is not part of a citation or an ISO date."""
    stripped = re.sub(r"\[[FD]\d+\]", lambda m: "#" * len(m.group(0)), text)
    stripped = re.sub(r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?", lambda m: "#" * len(m.group(0)), stripped)
    m = re.search(r"\d+", stripped)
    digit = text[m.end() - 1]
    changed = str((int(digit) + 3) % 10)
    return text[:m.end() - 1] + changed + text[m.end():]


def drop_first_citation(text):
    return re.sub(r" ?\[[FD]\d+\]", "", text, count=1)


def cite_missing_id(text):
    return re.sub(r"\[([FD])\d+\]", r"[\g<1>99]", text, count=1)


def append_unsupported_number(text):
    return text + " It will be credited within 48 hours."


def insert_msisdn(text):
    return text + " Call 9876543210 for help."


MUTATIONS = [
    ("change an amount", mutate_amount, "R3"),
    ("remove a citation from a factual sentence", drop_first_citation, "R1"),
    ("cite [F99]", cite_missing_id, "R2"),
    ("append a sentence with a number not in the context", append_unsupported_number, "R1"),
    ("insert an unmasked 10-digit number", insert_msisdn, "R4"),
]


class TestMutations(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ctx = contexts()

    def test_every_mutant_of_every_good_answer_is_flagged(self):
        flagged = total = 0
        misses = []
        for name, key, text in GOOD:
            self.assertTrue(verify_answer(text, self.ctx[key])["ok"], f"base answer {name} must be grounded")
            for label, fn, expected_code in MUTATIONS:
                mutant = fn(text)
                self.assertNotEqual(mutant, text, f"{name}/{label}: mutation was a no-op")
                result = verify_answer(mutant, self.ctx[key])
                total += 1
                if (not result["ok"]) and expected_code in codes(result):
                    flagged += 1
                else:
                    misses.append((name, label, mutant, result))
        print(f"\nverifier mutation test: {flagged}/{total} mutations flagged (by the expected rule)")
        self.assertGreaterEqual(len(GOOD), 6)
        self.assertEqual(misses, [])
        self.assertEqual(flagged, total)


if __name__ == "__main__":
    unittest.main(verbosity=2)
