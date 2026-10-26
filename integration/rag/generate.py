"""
Grounded-answer generation. Enforces the prompt contract: answer only from
the given evidence, cite evidence ids for every factual claim, separate
structured facts from document evidence, and abstain when evidence is
insufficient. No general-knowledge fill-in.
"""

from integration.rag.llm_client import OllamaClient

SYSTEM_PROMPT = """You are NovaTel's grounded support assistant.

Rules you MUST follow:
1. Answer ONLY using the evidence blocks provided below. Never use general
   knowledge, training data, or assumptions to fill gaps.
2. Every factual claim (a number, status, date, ID, policy detail, or count)
   must cite the evidence id(s) it came from, in square brackets, e.g. [E1]
   or [E1][E3].
3. Structured evidence (source=structured) contains exact database facts
   (e.g. a specific customer's plan or invoice). Document evidence
   (source=unstructured) contains policy/procedure/FAQ text. Keep these
   visibly separate in your answer -- state which kind of evidence each
   claim rests on.
4. If the evidence does not contain enough information to answer the
   question, say so explicitly and ABSTAIN from guessing. Do not invent an
   answer to appear helpful.
5. Be concise. Do not repeat the evidence verbatim; synthesize it.
"""

USER_TEMPLATE = """Question: {question}

Evidence:
{context_text}

Answer the question following all rules above. If evidence is empty or
insufficient, state that explicitly and abstain.
"""


def generate_answer(question: str, context_text: str, client: OllamaClient | None = None) -> dict:
    """
    Returns {"answer": str, "question": str, "context_text": str}.
    Does not itself verify citations -- integration/eval/factcheck.py does
    that deterministically after the fact.
    """
    client = client or OllamaClient()

    if not context_text.strip():
        return {
            "answer": "I don't have enough evidence to answer this question. Abstaining.",
            "question": question,
            "context_text": context_text,
        }

    user_prompt = USER_TEMPLATE.format(question=question, context_text=context_text)
    answer = client.chat(system=SYSTEM_PROMPT, user=user_prompt)

    return {"answer": answer, "question": question, "context_text": context_text}
