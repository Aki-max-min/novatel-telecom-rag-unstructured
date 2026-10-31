"""
RuleRouter -- keyword / regex / schema-term heuristics. The ablation baseline.

Cue lists are derived from the DATABASE SCHEMA (table/entity nouns, status
vocabularies) and from generic question phrasing ("how many", "how do I"),
NOT from the held-out router_test queries. Weak by design: it cannot understand
paraphrase, and it cannot tell a telecom question the corpus covers from one it
does not (so near-domain traps pass as in-scope).

Output probabilities are coarse (0.9 / 0.1 for strong evidence, 0.65 / 0.35 when
only a weak cue fired) so the shared confidence logic still works.
"""

from __future__ import annotations

import re

from query_router.base import BaseRouter

# --- structured side: entity nouns from the 28 tables and their status vocab ---
ENTITY_RE = re.compile(
    r"\b(invoices?|bills?|billing records?|tickets?|recharges?|recharge transactions?|transactions?|payments?|"
    r"kyc records?|kyc|sims?|esims?|esim profiles?|sites?|alarms?|orders?|port(?:ing)? requests?|ports?|"
    r"fraud cases?|escalation cases?|escalations?|subscriptions?|customers?|outlets?|devices?|vas|"
    r"value[- ]added services?|ott subscriptions?|roaming records?|fib(?:er|re) connections?|connections?|"
    r"plans?|accounts?|circles?|cases?)\b", re.I)
STATUS_RE = re.compile(
    r"\b(overdue|unpaid|paid|pending|failed|success(?:ful)?|refunded|open|closed|in progress|inprogress|blocked|"
    r"inactive|active|suspended|expired|accepted|rejected|cancell?ed|fulfilled|resolved|investigating|"
    r"under investigation|outage|down|critical|major|minor|prepaid|postpaid)\b", re.I)
COUNT_RE = re.compile(
    r"\b(how many|count of|count the|the count|total number|number of|how much (?:was|is|did)|"
    r"list (?:all|every|the)|show (?:me )?(?:all|every|the)|show (?:me )?|which (?:customers?|sites?|plans?|"
    r"tickets?|sims?|invoices?|orders?)|pull up|give me the|what (?:was|is) the (?:latest|last|most recent)|"
    r"latest|most recent|last two|last three)\b", re.I)
CUSTOMER_REF_RE = re.compile(r"\bcustomer\s*(?:id|no\.?|number)?\s*#?\s*\d{3,}\b", re.I)

# --- unstructured side: procedure / policy / regulation cues ---
DOC_CUE_RE = re.compile(
    r"\b(how (?:do|can|could|should|would) (?:i|we|you|a customer|customers|operators?)|how to|what should i|"
    r"what do i do|what happens (?:if|to|when)|steps?|procedure|process|policy|policies|rules?|regulations?|"
    r"regulator(?:y)?|trai|guidelines?|guidance|sop|faq|manual|documentation|release notes?|tariff catalogue|"
    r"what (?:is|are) (?:the )?(?:standard|process|procedure|policy|rules?|timeline|difference)|"
    r"what does .{0,60}\bsay\b|explain|why (?:does|is|do|did) my|what rights|where can (?:a )?customers?|"
    r"required to|requirements?|eligib|entitle|obligations?|timeline|escalate)\b", re.I)
POLICY_WORDS_RE = re.compile(
    r"\b(policy|policies|rules?|regulations?|procedure|process|guidelines?|sop|terms|penalt(?:y|ies)|"
    r"late fees?|re-?verification|reactivat\w+|refund (?:policy|procedure|process)|escalation (?:process|timeline|procedure)|"
    r"what does .{0,60}\bsay\b|what happens|how (?:is|are) .{0,40}(?:handled|resolved|defined))\b", re.I)

# --- scope ---
TELECOM_VOCAB_RE = re.compile(
    r"\b(sim|esim|recharge|plan|bill|billing|invoice|data|network|call|calls|sms|roaming|kyc|port|porting|number|"
    r"otp|app|broadband|fib(?:er|re)|ftth|router|ont|tariff|telecom|trai|dnd|spam|operator|novatel|subscriber|"
    r"postpaid|prepaid|ticket|complaint|refund|coverage|4g|5g|volte|fraud|mobile|phone|handset|signal|outage|"
    r"customer|customers|account|payment|vas|loyalty|tier|offer|offers|iot|enterprise|connection|telemarket\w*|"
    r"promotional|unsolicited|quality of service|qos|escalat\w+|site|sites|alarm|alarms)\b", re.I)
INJECTION_RE = re.compile(
    r"(ignore (?:all |the |your )?(?:previous|above|prior)|disregard (?:your|all|the)|system prompt|"
    r"hidden (?:instructions?|prompt)|reveal (?:your|the)|print (?:your|the full)|you are now|act as an unrestricted|"
    r"system override|jailbreak|api keys?|forget everything)", re.I)
OTHER_ORG_RE = re.compile(
    r"\b(airtel|jio|reliance jio|vodafone|vi\b|vodafone idea|bsnl|mtnl|verizon|t-mobile|at&t|starlink|"
    r"comcast|orange|telstra)\b", re.I)
OFF_TOPIC_RE = re.compile(
    r"\b(weather|poem|poetry|sonnet|haiku|limerick|recipe|cricket|football|soccer|tennis|ipl|wimbledon|olympic|"
    r"formula 1|capital of|stock|share price|bitcoin|crypto|mutual fund|joke|story|song|movie|film|book|"
    r"python|javascript|sql query|regex|bash script|recursion|multiplied|times \d|square root|translate|"
    r"horoscope|diet|calories|workout|prime minister|president of|history of)\b", re.I)


class RuleRouter(BaseRouter):
    name = "rule"
    model_id = "regex/keyword heuristics (no model)"
    size_params = 0

    def _predict(self, query: str) -> dict:
        q = query or ""
        low = q.lower()

        if INJECTION_RE.search(q):
            return self._out("prompt-injection cue", p_scope=0.02)
        if OFF_TOPIC_RE.search(q) and not CUSTOMER_REF_RE.search(q):
            return self._out("off-topic cue", p_scope=0.05)
        if OTHER_ORG_RE.search(q) and "novatel" not in low:
            return self._out("other organisation named", p_scope=0.05)
        if not TELECOM_VOCAB_RE.search(q) and not CUSTOMER_REF_RE.search(q):
            return self._out("no telecom vocabulary", p_scope=0.08)

        has_customer = bool(CUSTOMER_REF_RE.search(q))
        has_entity = bool(ENTITY_RE.search(q))
        has_status = bool(STATUS_RE.search(q))
        has_count = bool(COUNT_RE.search(q))
        has_doc = bool(DOC_CUE_RE.search(q))
        has_policy = bool(POLICY_WORDS_RE.search(q))

        struct_strong = has_customer or (has_count and has_entity) or (has_status and has_entity and not has_doc)
        struct_weak = (has_status and has_entity) or has_count
        doc_strong = has_doc or has_policy

        p_s = 0.9 if struct_strong else (0.6 if struct_weak else 0.1)
        # a customer-id lookup with no policy language is a pure data question
        if has_customer and not (has_doc or has_policy):
            p_u = 0.08
        elif struct_strong and not doc_strong:
            p_u = 0.12
        elif doc_strong:
            p_u = 0.9
        else:
            # in-scope, nothing structured detected -> documents by default
            p_u = 0.7 if not struct_strong else 0.35
            if not struct_strong:
                p_s = 0.1
        if not struct_strong and not doc_strong and not struct_weak:
            p_u = 0.65
        reason = (f"customer_ref={has_customer} entity={has_entity} status={has_status} "
                  f"count={has_count} doc_cue={has_doc} policy_word={has_policy}")
        return {"p_in_scope": 0.95, "p_structured": p_s, "p_unstructured": p_u, "reasoning": reason}

    @staticmethod
    def _out(reason: str, p_scope: float) -> dict:
        return {"p_in_scope": p_scope, "p_structured": 0.0, "p_unstructured": 0.0, "reasoning": reason}
