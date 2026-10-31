"""
Grounded generation with sentence-level citations.

The generator is handed NUMBERED EVIDENCE blocks ([E1]..[En]) with provenance
and is told, in a strict format contract, to write short atomic sentences, one
per line, each ending in the ids of the evidence that supports it. The contract
also covers the two honesty rules the system depends on:

  * INSUFFICIENT_EVIDENCE   -- emitted verbatim when the evidence cannot answer.
  * NOT ANSWERED: <part>    -- the half-answerable rule: when only PART of a
                               (hybrid) question is supported, answer that part and
                               state explicitly which part was not covered; the gap
                               is never filled from model knowledge.

The model is only the writer. Whether its sentences are actually supported is
decided afterwards, independently, by integration/qa/citations.py.

Reuses the generator the baseline RAG already uses (local Ollama, qwen2.5:7b-instruct
by default, temperature 0, fixed seed) via integration/rag/llm_client.OllamaClient.
"""

from __future__ import annotations

from integration.qa.config import QAConfig
from integration.rag.llm_client import OllamaClient

SYSTEM_TEMPLATE = """You are NovaTel's grounded support assistant. You answer ONLY from the numbered EVIDENCE blocks.

OUTPUT FORMAT (strict):
- Write short, atomic sentences. ONE sentence per line. No headings, no bullets, no markdown, no preamble.
- End EVERY sentence with the id(s) of the evidence that supports it, e.g. "Roaming must be activated before you travel. [E2]" or "... [E1][E3]".
- Cite only ids that appear in the EVIDENCE. Never invent an id.
- Copy every number, date, id, status and amount exactly as written in the cited evidence.
- DATABASE evidence holds exact records and counts; DOCUMENT evidence holds policy, procedure and regulation text. Use database evidence only for facts about records or counts, and document evidence only for rules and procedures. Never state a customer's data from a document, or a policy from a record.
- Use at most {max_sentences} sentences.
- If the evidence does not contain what is needed to answer, output exactly: INSUFFICIENT_EVIDENCE
- If only PART of the question can be answered from the evidence, answer that part, then add ONE final line: NOT ANSWERED: <the part the evidence does not cover>
- Never use outside knowledge. Never guess."""

USER_TEMPLATE = """QUESTION: {question}
{parts}
EVIDENCE:
{evidence}

Write the answer now, following the format exactly."""


def format_evidence_block(item: dict, max_chars: int = 2200) -> str:
    md = item["metadata"]
    eid = md["evidence_id"]
    if item["source"] == "structured":
        where = f"table {md.get('table_name')}" + (f", row {md.get('row_id')}" if md.get("row_id") else ", aggregate count")
        return f"[{eid}] DATABASE | {where}\n{item['content']}"
    prov = md.get("provenance") or {}
    page = md.get("page_number")
    page_txt = f", p. {page}" if page is not None else ""
    where = f"{prov.get('corpus')}, {md.get('document_id')}{page_txt}"
    return f"[{eid}] DOCUMENT | {where}\n{item['content'][:max_chars]}"


def build_messages(question: str, evidence: list[dict], cfg: QAConfig, sub_queries: dict | None = None) -> tuple[str, str]:
    parts = ""
    if sub_queries and sub_queries.get("structured") and sub_queries.get("unstructured"):
        parts = (f"QUESTION PARTS: (a) data part: {sub_queries['structured']}  "
                 f"(b) rules/procedure part: {sub_queries['unstructured']}\n")
    system = SYSTEM_TEMPLATE.format(max_sentences=cfg.max_answer_sentences)
    user = USER_TEMPLATE.format(
        question=question, parts=parts,
        evidence="\n\n".join(format_evidence_block(e) for e in evidence),
    )
    return system, user


def generate(question: str, evidence: list[dict], cfg: QAConfig, sub_queries: dict | None = None,
             client: OllamaClient | None = None) -> str:
    client = client or OllamaClient(model=cfg.generator_model)
    system, user = build_messages(question, evidence, cfg, sub_queries)
    return client.chat(system=system, user=user)
