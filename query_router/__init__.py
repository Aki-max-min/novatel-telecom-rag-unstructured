"""Query routing for the NovaTel integrated RAG (structured | unstructured | hybrid | out_of_scope)."""

from query_router.base import (  # noqa: F401
    LABELS,
    BaseRouter,
    RouteDecision,
    RouterUnavailable,
    derive_label,
    parse_json_object,
)
