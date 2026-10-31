"""
Common Evidence Interface.

Both retrievers emit the existing Common Result Schema with exactly the same 8
core keys (source, record_id, dataset, category, score, retrieval_method,
content, metadata). Nothing is added at the top level: everything new lives in
`metadata`, which carries the extended provenance keys

    document_id, chunk_id, page_number, table_name, row_id, columns_used,
    query_or_lookup, entity_id, ontology_concepts, relationships, raw_scores,
    provenance, origin_subquery            (+ evidence_id, fusion once fused)

Keys that do not apply to a source stay None (structured evidence has no
chunk_id; unstructured evidence has no table_name), they are never invented.

Scores from different sources are NEVER combined numerically. `score` keeps the
source's own number (1.0 for an exact SQL match; the CrossEncoder logit for a
document chunk) purely for display; only ranks reach fusion, and every raw score
component is preserved verbatim under metadata["raw_scores"].
"""

from __future__ import annotations

import datetime as _dt
import decimal as _dec

CORE_KEYS = ("source", "record_id", "dataset", "category", "score", "retrieval_method", "content", "metadata")
EXTENDED_METADATA_KEYS = (
    "document_id", "chunk_id", "page_number", "table_name", "row_id", "columns_used", "query_or_lookup",
    "entity_id", "ontology_concepts", "relationships", "raw_scores", "provenance", "origin_subquery",
)

SYNTHETIC_DATASET = "novatel_synthetic"
PUBLIC_DATASET = "trai_public"
CORPUS_LABEL = {SYNTHETIC_DATASET: "NovaTel Synthetic", PUBLIC_DATASET: "TRAI public"}


def jsonable(value):
    """Make a DB value JSON-safe without changing its meaning."""
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, _dec.Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return value


def blank_metadata() -> dict:
    return {k: None for k in EXTENDED_METADATA_KEYS}


def build_lookup_sql(parsed: dict | None, table: str, result_method: str, record_id) -> str | None:
    """The SQL the structured retriever's DataLoader actually ran (see structured/data_loader.py)."""
    if not parsed:
        return None
    column, value = parsed.get("filter_column"), parsed.get("filter_value")
    method = parsed.get("method")
    if method == "aggregate":
        base = f"SELECT COUNT(*) FROM {table}"
        return base + (f" WHERE {column} = '{value}'" if column else "")
    if column is not None:
        return f"SELECT * FROM {table} WHERE {column} = '{value}'"
    return None


def structured_evidence(result: dict, *, parsed: dict | None, sub_query: str, origin: str, primary_key: str | None) -> dict:
    """Wrap one StructuredRetriever result in the extended schema (core keys unchanged)."""
    row = jsonable(dict(result.get("metadata") or {}))
    table = result["dataset"]
    is_aggregate = result.get("retrieval_method") == "aggregate"
    record_id = result.get("record_id")
    if record_id is None and is_aggregate:
        record_id = f"{table}:aggregate"
    md = dict(row)  # row values stay readable at the top of metadata (StructuredRetriever's own convention)
    md.update(blank_metadata())
    md.update({
        "table_name": table,
        "row_id": None if is_aggregate else (str(record_id) if record_id is not None else None),
        "columns_used": sorted(row.keys()),
        "query_or_lookup": build_lookup_sql(parsed, table, result.get("retrieval_method"), record_id),
        "raw_scores": {"structured_match": result.get("score")},
        "origin_subquery": origin,
        "provenance": {"kind": "table_row", "table": table, "primary_key": primary_key,
                       "row_id": None if is_aggregate else str(record_id), "aggregate": is_aggregate,
                       "sub_query": sub_query},
    })
    return {
        "source": "structured",
        "record_id": str(record_id),
        "dataset": table,
        "category": result.get("category", ""),
        "score": result.get("score", 1.0),
        "retrieval_method": result.get("retrieval_method", "exact_filter"),
        "content": result["content"],
        "metadata": md,
    }


def unstructured_evidence(*, document_id: str, chunk_id: str, dataset: str, category: str, content: str,
                          title: str, retrieval_method: str, raw_scores: dict, score: float, sub_query: str,
                          origin: str, page_number=None, source_authority: str | None = None,
                          document_type: str | None = None, ontology_concepts=None, relationships=None) -> dict:
    md = blank_metadata()
    md.update({
        "document_id": document_id,
        "chunk_id": chunk_id,
        "page_number": page_number,
        "raw_scores": raw_scores,
        "origin_subquery": origin,
        "ontology_concepts": ontology_concepts,
        "relationships": relationships,
        "title": title,
        "document_type": document_type,
        "source_authority": source_authority,
        "provenance": {"kind": "document_chunk", "corpus": CORPUS_LABEL.get(dataset, dataset),
                       "document_id": document_id, "chunk_id": chunk_id, "title": title,
                       "page_number": page_number, "source_authority": source_authority, "sub_query": sub_query},
    })
    return {
        "source": "unstructured",
        "record_id": chunk_id,
        "dataset": dataset,
        "category": category,
        "score": float(score),
        "retrieval_method": retrieval_method,
        "content": content,
        "metadata": md,
    }


def assign_evidence_ids(fused: list[dict]) -> list[dict]:
    """Stable E1..En ids in fused rank order. Returned list holds shallow copies."""
    out = []
    for i, item in enumerate(fused, start=1):
        e = dict(item)
        e["metadata"] = dict(item["metadata"])
        e["metadata"]["evidence_id"] = f"E{i}"
        out.append(e)
    return out


def evidence_id(item: dict) -> str:
    return item["metadata"]["evidence_id"]


def validate_core(item: dict) -> list[str]:
    """Problems (empty list == conforms to the Common Result Schema)."""
    problems = [f"missing core key: {k}" for k in CORE_KEYS if k not in item]
    if "metadata" in item:
        problems += [f"missing metadata key: {k}" for k in EXTENDED_METADATA_KEYS if k not in item["metadata"]]
    return problems
