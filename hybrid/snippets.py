"""
Snippet cleaning for retrieved document chunks (E13 Phase 9d-2).

Real chunk text is a single line of markdown-ish text: an FAQ chunk looks like
    "Question: How do I ...? Answer: ### Short Answer Visit ... ### Key Details | Detail | Value | |---|---| | ... |"
and an SOP chunk carries an inline metadata header
    "New Connection ... Procedure Document ID: SOP_C17_KYC_VERIFICATION Category: C17 - KYC ... Last Updated: 2026-08-08 ..."
Quoting such text verbatim produced unreadable answers, so before any sentence selection the chunk is cleaned:

  1. inline header fields (Document ID / Category / Department / Customer Scope / Version / Last Updated /
     Source Authority / Channel) are removed;
  2. the leading "Question: <text>?" (the FAQ title, repeated in the document title) and the "Answer:" label are removed;
  3. markdown section headings ("### Short Answer", "### Key Details", ...) and heading markers (#) and bold markers (**)
     are removed;
  4. table rows ("| ... |", "|---|---|") are removed;
  5. if the chunk begins mid-sentence (chunk index above 0 and the first character is lower-case) the fragment up to the
     first sentence start is dropped.

Everything that remains is verbatim document text (nothing is paraphrased or reordered).
"""

import re

_FIELDS = r"(?:Document ID|Category|Department|Customer Scope|Version|Last Updated|Source Authority|Channel)"
_NEXT = rf"(?=\s+{_FIELDS}\s*:|\s*\*\*|\s*$)"
# each header field has a BOUNDED value, so a field at the end of the header can never swallow the body text
_HEADER_FIELD = re.compile("|".join([
    r"Document ID\s*:\s*[\w\-]+",
    rf"Category\s*:\s*C\d+[^:*|#]{{0,70}}?{_NEXT}",
    rf"Department\s*:\s*[^:*|#]{{1,40}}?{_NEXT}",
    r"Customer Scope\s*:\s*\w+",
    r"Version\s*:\s*[\d.]+",
    r"Last Updated\s*:\s*[\d\-]+",
    r"Source Authority\s*:\s*(?:Internal Knowledge Base|\w+)",
    r"Channel\s*:\s*\w+",
]), re.S)
_SECTION_HEADING = re.compile(
    r"#{2,}\s*(?:Short Answer|Detailed Explanation|Key Details|Example Scenario|Related Information|Conditions|"
    r"Escalation|Troubleshooting|Summary|Overview)\b", re.I)
_QUESTION_ANSWER = re.compile(r"^\s*Question\s*:.*?\?\s*Answer\s*:\s*", re.S | re.I)
_LABELS = re.compile(r"^\s*(?:Question|Answer)\s*:\s*", re.I)
# a pipe-delimited run: cells of at most 160 characters that do not contain a heading marker
_TABLE = re.compile(r"\|(?:(?:(?!###)[^|]){0,160}\|)+")
_SENTENCE_START = re.compile(r"[.!?]\s+(?=[A-Z0-9\"'(\[])")


def clean_chunk_text(content: str, chunk_index: int = 0) -> str:
    text = content or ""
    text = _HEADER_FIELD.sub(" ", text)
    text = _QUESTION_ANSWER.sub("", text)
    text = _LABELS.sub("", text)
    text = _SECTION_HEADING.sub(" ", text)
    text = text.replace("**", " ")
    text = re.sub(r"#+", " ", text)
    text = _TABLE.sub(" ", text)
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"-{3,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if chunk_index and text[:1].islower():
        m = _SENTENCE_START.search(text)
        if m:
            text = text[m.end():]
    return text


def chunk_index_of(record_id: str) -> int:
    m = re.search(r"_chunk_(\d+)$", record_id or "")
    return int(m.group(1)) if m else 0
