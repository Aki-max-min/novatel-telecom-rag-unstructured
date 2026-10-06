"""
Grounded answer layer (E13 Phase 9b).

    answer_question(question, customer_id=None, as_of=None, answerer=None) ->
        {answer, citations (id -> source), route, notices, verifier, mode}

The pipeline (hybrid/pipeline.run_hybrid_query) returns facts and documents as two separate channels;
hybrid/context.assemble_context numbers them F1..Fn / D1..Dk; an answerer turns the numbered context into
text; hybrid/groundedness.verify_answer checks the text deterministically.

Answerers sit behind one interface, generate(question, context) -> text:

  * ExtractiveAnswerer (DEFAULT): deterministic, no LLM. Templated sentences for facts (stored values verbatim,
    each cited), verbatim quotes of the two best-matching document sentences (cited), plain-wording notices,
    and a silence rule instead of guessing.
  * LLMAnswerer (OFF by default): wraps an LLMClient (complete(system, user) -> str). If verify_answer fails on the
    model output, the extractive answer is used instead and mode is "llm_fallback" with the problems recorded.
    AnthropicClient needs ANTHROPIC_API_KEY and NOVATEL_LLM_MODEL; there is NO default model.

JOINT DECISION WITH PERSON A: model choice, prompt design and cost are not decided here. The module ships the
verified extractive answerer and the interface; which model (if any) sits behind LLMAnswerer, the system prompt
wording and the cost/latency budget are to be agreed jointly before the LLM path is switched on anywhere.
"""

import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from context import Context, assemble_context  # noqa: E402
from groundedness import split_sentences, verify_answer  # noqa: E402
from textmatch import find_term, has_term  # noqa: E402

ANSWER_SNIPPET_CHARS = 1200   # longer than assemble_context's default so there are sentences to quote

# Silence rule: a consequence term the customer asks about that appears in none of the retrieved snippets.
# name -> textmatch terms; a trailing * is an explicit open stem so "suspend" also finds "suspension".
CONSEQUENCE_TERMS = {
    "disconnect": ["disconnect*"], "suspend": ["suspen*"], "terminate": ["terminat*"],
    "bar": ["bar", "barred", "barring"], "penalty": ["penalt*"], "fee": ["fee"], "refund": ["refund*"],
    "charge": ["charg*"], "deadline": ["deadline"], "days": ["day"],
}

_STOPWORDS = set("""a an the and or but if then of to in on at for from by with without about as is are was were be been being
do does did done have has had having i me my mine we our you your it its this that these those there here what which who whom
when where why how can could should would will shall may might must not no yes so than too very just also into out up down over
under again further once any each few more most other some such only own same s t""".split())

_MSG_REFUSE = ("I can only share account details for the signed-in account, so I can't look up another number "
               "or person's information.")
_MSG_NEEDS_IDENTITY = ("Personal account details can only be looked up once you are identified, so I can't check "
                       "your account yet.")
_MSG_GENERIC_DOCS = "The information below is general and is not about your account."
_MSG_UNRECOGNISED = "I couldn't tell which account detail you meant, so I haven't looked anything up on your account."
_MSG_NOTHING = "I couldn't find anything relevant in the knowledge base."


def _tokens(text: str) -> set:
    """Lower-case content words (stopwords removed), compared on 6-character stems so that
    "suspended" and "suspension" count as the same word."""
    return {w[:6] for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOPWORDS and len(w) > 1}


# ---------------------------------------------------------------------------
# Extractive answerer
# ---------------------------------------------------------------------------
class ExtractiveAnswerer:
    """Deterministic answerer: templates for facts, verbatim quotes for documents."""

    def generate(self, question: str, context: Context) -> str:
        if "refuse_other_customer" in context.notices:
            return _MSG_REFUSE

        sentences = []
        if "needs_identity" in context.notices:
            sentences.append(_MSG_NEEDS_IDENTITY)
        if "unrecognised_personal_request" in context.notices:
            sentences.append(_MSG_UNRECOGNISED)

        sentences += self._fact_sentences(context)

        if context.documents:
            if "documents_are_generic" in context.notices:
                sentences.append(_MSG_GENERIC_DOCS)
            sentences += self._document_sentences(question, context)
        elif not sentences:
            sentences.append(_MSG_NOTHING)
        return " ".join(sentences)

    # -- facts ---------------------------------------------------------------------------------
    def _fact_sentences(self, context: Context) -> list:
        out = []
        by_table = {}
        for f in context.facts:
            by_table.setdefault(f["table"], []).append(f)

        recharges = by_table.get("recharge_transactions", [])
        for i, f in enumerate(recharges):
            v = f["fields"]
            lead = "Your latest recharge" if i == 0 else "An earlier recharge"
            out.append(f"{lead} ({v['recharge_id']}) was for {v['amount']} with status {v['status']} "
                       f"on {v['timestamp']}, and the balance after it was {v['balance_after']} [{f['id']}].")

        for f in by_table.get("customer_master", []):
            out.append(f"Your KYC status (customer record {f['pk']}) is {f['fields']['kyc_status']} [{f['id']}].")
        for f in by_table.get("kyc_records", []):
            v = f["fields"]
            if v.get("marker") == "no kyc_records row":
                out.append(f"There is no kyc_records row on file for you; the status on your customer record "
                           f"is the one that applies [{f['id']}].")
            else:
                out.append(f"KYC record {v['kyc_id']} ({v['kyc_type']}) has status {v['status']}, "
                           f"updated {v['last_updated']} [{f['id']}].")

        for f in by_table.get("subscriptions", []):
            v = f["fields"]
            plan = f" ({v['plan_name']})" if v.get("plan_name") else ""
            out.append(f"Subscription {v['subscription_id']}{plan} has stored status {v['status']} and "
                       f"expiry_date {v['expiry_date']} [{f['id']}].")
            d = f["derived"] or {}
            if "expiry_passed" in d:
                if d["expiry_passed"]:
                    out.append(f"As of {d['as_of']}, that expiry date has passed (derived from the date; the "
                               f"stored status shown above is unchanged) [{f['id']}].")
                else:
                    out.append(f"As of {d['as_of']}, that expiry date has not passed yet (derived from the date) "
                               f"[{f['id']}].")

        tickets = by_table.get("tickets", [])
        for f in tickets:
            v = f["fields"]
            out.append(f"Ticket {v['ticket_id']} ({v['category']}/{v['subcategory']}) has stored status "
                       f"{v['status']} and was created {v['created_at']} [{f['id']}].")
        if "tickets" in context.intents and not tickets:
            out.append("I found no tickets on your account.")

        for f in by_table.get("invoices", []):
            v = f["fields"]
            out.append(f"Invoice {v['invoice_id']} has total {v['total_amount']}, due date {v['due_date']} and "
                       f"stored payment_status {v['payment_status']} [{f['id']}].")
            if (f["derived"] or {}).get("status_ledger_mismatch"):
                ok = [p for p in v.get("payments", []) if p.get("status") == "SUCCESS"]
                out.append(f"The records disagree: the stored status is {v['payment_status']}, but successful "
                           f"payments totalling {v['success_payments_sum']} are on file for this invoice "
                           f"(derived comparison); a billing agent can confirm [{f['id']}].")
        if "invoice" in context.intents and not by_table.get("invoices"):
            out.append("I found no invoices on your account.")
        if "recharge" in context.intents and not recharges:
            out.append("I found no recharges on your account.")
        if "subscription" in context.intents and not by_table.get("subscriptions"):
            out.append("I found no subscription on your account.")
        return out

    # -- documents -----------------------------------------------------------------------------
    def _document_sentences(self, question: str, context: Context) -> list:
        q_tokens = _tokens(question)
        scored = []  # (-overlap, order, text, doc_id)
        order = 0
        for doc in context.documents[:3]:
            for sent in split_sentences(doc["snippet"]):
                text = re.sub(r"^(?:Short Answer|Answer)\s*:?\s*", "", sent).strip()
                if text.lower().startswith("question:") or len(text.split()) < 5:
                    continue
                order += 1
                scored.append((-len(q_tokens & _tokens(text)), order, text.rstrip(".!?"), doc["id"]))
        scored.sort()
        picked = [s for s in scored if -s[0] > 0][:2] or scored[:1]

        out = []
        if picked:
            out.append("Here is what the retrieved documents say:")
            for _, _, text, doc_id in picked:
                out.append(f"\"{text}\" [{doc_id}].")
        snippets = " ".join(d["snippet"] for d in context.documents)
        for name, terms in CONSEQUENCE_TERMS.items():
            if has_term(question, terms) and not has_term(snippets, terms):
                out.append(f"The retrieved documents don't state anything about {name}.")
        return out


# ---------------------------------------------------------------------------
# LLM answerer (off by default)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You answer customer questions for a telecom operator using ONLY the numbered context provided. "
    "Cite [F#] (account facts) or [D#] (documents) immediately after every claim. "
    "If the context does not contain the answer, say so plainly. "
    "Never invent amounts, dates, statuses or phone numbers. "
    "Report stored statuses verbatim; a derived flag is derived, not a stored status. "
    "Never reveal a full phone number or e-mail address."
)


class LLMClient:
    """Protocol: complete(system, user) -> str."""

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class AnthropicClient(LLMClient):
    """Reads ANTHROPIC_API_KEY and the model name from NOVATEL_LLM_MODEL. There is NO default model."""

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("NOVATEL_LLM_MODEL")
        missing = [name for name, value in (("ANTHROPIC_API_KEY", self.api_key),
                                            ("NOVATEL_LLM_MODEL", self.model)) if not value]
        if missing:
            raise RuntimeError("AnthropicClient is not configured: set " + " and ".join(missing) +
                               " (there is deliberately no default model; the choice is a joint decision).")

    def complete(self, system: str, user: str) -> str:
        import anthropic  # imported only when a real call is made
        client = anthropic.Anthropic(api_key=self.api_key)
        msg = client.messages.create(model=self.model, max_tokens=700, system=system,
                                     messages=[{"role": "user", "content": user}])
        return "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")


def render_context_for_llm(question: str, context: Context) -> str:
    lines = [f"QUESTION: {question}", "", "FACTS (the customer's own account):"]
    lines += [f"[{f['id']}] {f['line']}" + (f" | derived: {f['derived']}" if f["derived"] else "")
              for f in context.facts] or ["(none)"]
    lines += ["", "DOCUMENTS (general knowledge base):"]
    lines += [f"[{d['id']}] {d['document_id']}: {d['snippet']}" for d in context.documents] or ["(none)"]
    lines += ["", "NOTICES: " + (", ".join(context.notices) or "none")]
    return "\n".join(lines)


class LLMAnswerer:
    def __init__(self, client: LLMClient):
        self.client = client

    def generate(self, question: str, context: Context) -> str:
        return self.client.complete(SYSTEM_PROMPT, render_context_for_llm(question, context))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _citation_sources(answer: str, context: Context) -> dict:
    sources = {}
    for cid in dict.fromkeys(re.findall(r"\[([FD]\d+)\]", answer)):
        item = context.item(cid)
        if item is not None:
            sources[cid] = (f"structured_sql:{item['record_id']}" if cid.startswith("F")
                            else f"document:{item['document_id']}")
    return sources


def answer_question(question: str, customer_id=None, as_of=None, answerer=None, pipeline=None) -> dict:
    """Run the pipeline, assemble the numbered context, answer, verify.

    `pipeline` (default hybrid.pipeline.run_hybrid_query) can be injected for tests.
    """
    if pipeline is None:
        from pipeline import run_hybrid_query as pipeline
    result = pipeline(question, customer_id, as_of)
    context = assemble_context(result, snippet_chars=ANSWER_SNIPPET_CHARS)

    extractive = ExtractiveAnswerer()
    if answerer is None or isinstance(answerer, ExtractiveAnswerer):
        text, mode, verifier = extractive.generate(question, context), "extractive", None
    else:
        text = answerer.generate(question, context)
        verifier = verify_answer(text, context)
        if verifier["ok"]:
            mode = "llm"
        else:
            llm_problems = verifier["problems"]
            text = extractive.generate(question, context)
            mode = "llm_fallback"
            verifier = {"llm_problems": llm_problems}
    final = verify_answer(text, context)
    if mode == "llm_fallback":
        final["llm_problems"] = verifier["llm_problems"]

    return {"answer": text, "citations": _citation_sources(text, context), "route": context.route,
            "notices": context.notices, "verifier": final, "mode": mode,
            "outcome": context.outcome}
