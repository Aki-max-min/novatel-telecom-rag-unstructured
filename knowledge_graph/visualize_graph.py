"""Renders a readable subgraph of the NovaTel knowledge graph for screenshots.

A picture of all 363 nodes is a hairball, so the default view is one category:
its documents plus every Service, Channel, VerificationMethod, Requirement and
Location those documents mention. That is small enough to read and shows both
graph layers at once.

Two outputs land in ``knowledge_graph/output/``:

* ``subgraph_<CATEGORY>.html`` - interactive (pyvis), drag and hover
* ``subgraph_<CATEGORY>.png``  - static (matplotlib), for slides

Layout uses a fixed random seed, so the same graph renders the same way twice.

Usage::

    python -m knowledge_graph.visualize_graph                  # C17 (KYC)
    python -m knowledge_graph.visualize_graph --category C05
    python -m knowledge_graph.visualize_graph --service-map    # services + channels
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import networkx as nx

from knowledge_graph.entity_extractor import OUTPUT_DIR
from knowledge_graph.graph_builder import CONTENT_NODE_LABELS, GRAPHML_PATH

#: One colour per node label, shared by both renderers.
LABEL_COLORS: Dict[str, str] = {
    "Document": "#4C78A8",
    "Category": "#F58518",
    "Department": "#54A24B",
    "DocumentType": "#B279A2",
    "CustomerScope": "#9D755D",
    "Tag": "#BAB0AC",
    "SourceAuthority": "#79706E",
    "Dataset": "#D3D3D3",
    "Service": "#E45756",
    "Channel": "#72B7B2",
    "VerificationMethod": "#EECA3B",
    "Requirement": "#FF9DA6",
    "Location": "#8C564B",
}

LABEL_SIZES: Dict[str, int] = {
    "Category": 34,
    "Service": 26,
    "Document": 18,
}
DEFAULT_SIZE = 20


def load_graph(path: Path = GRAPHML_PATH) -> nx.DiGraph:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build the graph first: python -m knowledge_graph.graph_builder"
        )
    return nx.read_graphml(path)


def category_subgraph(graph: nx.DiGraph, category_code: str) -> nx.DiGraph:
    """A category, its documents, and every content concept they mention."""
    category = f"Category::{category_code}"
    if category not in graph:
        raise KeyError(f"category {category_code!r} is not in the graph")

    documents = [
        source
        for source, _, attributes in graph.in_edges(category, data=True)
        if attributes.get("type") == "BELONGS_TO_CATEGORY"
    ]

    keep = {category, *documents}
    for document in documents:
        for _, target, attributes in graph.out_edges(document, data=True):
            if str(attributes.get("type", "")).startswith("MENTIONS_"):
                keep.add(target)

    subgraph = graph.subgraph(keep).copy()
    # Keep only the edges that explain this view: membership and mentions.
    drop = [
        (source, target)
        for source, target, attributes in subgraph.edges(data=True)
        if attributes.get("type") != "BELONGS_TO_CATEGORY"
        and not str(attributes.get("type", "")).startswith("MENTIONS_")
    ]
    subgraph.remove_edges_from(drop)
    return subgraph


def service_map_subgraph(graph: nx.DiGraph) -> nx.DiGraph:
    """Every Service with the Channels/Verifications/Requirements it co-occurs with."""
    keep = {
        node
        for node, attributes in graph.nodes(data=True)
        if attributes.get("label") in CONTENT_NODE_LABELS
    }
    subgraph = graph.subgraph(keep).copy()
    drop = [
        (source, target)
        for source, target, attributes in subgraph.edges(data=True)
        if attributes.get("type")
        not in ("AVAILABLE_VIA", "REQUIRES_VERIFICATION", "REQUIRES_DOCUMENT")
    ]
    subgraph.remove_edges_from(drop)
    subgraph.remove_nodes_from([node for node in subgraph if subgraph.degree(node) == 0])
    return subgraph


def _node_label(graph: nx.DiGraph, node: str) -> str:
    attributes = graph.nodes[node]
    key = attributes.get("key", node)
    if attributes.get("label") == "Category":
        return f"{key}\n{attributes.get('name', '')}"
    return str(key)


def _tooltip(graph: nx.DiGraph, node: str) -> str:
    attributes = graph.nodes[node]
    lines = [f"{attributes.get('label')}: {attributes.get('key')}"]
    for field in ("title", "name", "document_type", "department", "document_frequency"):
        value = attributes.get(field)
        if value not in (None, ""):
            lines.append(f"{field}: {value}")
    return "\n".join(lines)


def render_pyvis(graph: nx.DiGraph, path: Path, title: str) -> Optional[Path]:
    """Interactive HTML. Returns None if pyvis is not installed."""
    try:
        from pyvis.network import Network
    except ImportError:
        return None

    network = Network(
        height="820px",
        width="100%",
        directed=True,
        bgcolor="#ffffff",
        font_color="#222222",
        cdn_resources="in_line",
    )
    network.heading = title
    for node, attributes in graph.nodes(data=True):
        label = attributes.get("label", "?")
        network.add_node(
            node,
            label=_node_label(graph, node).replace("\n", " "),
            title=_tooltip(graph, node),
            color=LABEL_COLORS.get(label, "#CCCCCC"),
            size=LABEL_SIZES.get(label, DEFAULT_SIZE),
            shape="dot",
        )
    for source, target, attributes in graph.edges(data=True):
        edge_type = attributes.get("type", "")
        evidence = attributes.get("evidence", "")
        network.add_edge(
            source,
            target,
            title=f"{edge_type}\n{evidence}" if evidence else edge_type,
            label="",
            color="#B8B8B8",
        )
    network.barnes_hut(gravity=-12000, spring_length=180)
    path.parent.mkdir(parents=True, exist_ok=True)
    # pyvis writes with the platform default encoding, which is cp1252 here and
    # chokes on the en dashes in document titles. Generate, then write as UTF-8.
    html = network.generate_html(notebook=False)
    if "charset" not in html[:600].lower():
        html = html.replace("<head>", '<head>\n<meta charset="utf-8">', 1)
    path.write_text(html, encoding="utf-8")
    return path


def render_matplotlib(graph: nx.DiGraph, path: Path, title: str) -> Optional[Path]:
    """Static PNG. Returns None if matplotlib is not installed."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.patches as mpatches
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    # Fixed seed so the same subgraph always renders the same picture.
    positions = nx.spring_layout(graph, seed=42, k=0.55, iterations=180)
    labels_present = sorted(
        {graph.nodes[node].get("label", "?") for node in graph.nodes},
        key=lambda name: list(LABEL_COLORS).index(name) if name in LABEL_COLORS else 99,
    )

    figure, axes = plt.subplots(figsize=(18, 12))
    for label in labels_present:
        nodes = [n for n in graph.nodes if graph.nodes[n].get("label") == label]
        nx.draw_networkx_nodes(
            graph,
            positions,
            nodelist=nodes,
            node_color=LABEL_COLORS.get(label, "#CCCCCC"),
            node_size=[LABEL_SIZES.get(label, DEFAULT_SIZE) * 45 for _ in nodes],
            edgecolors="#33333355",
            linewidths=0.6,
            ax=axes,
        )
    nx.draw_networkx_edges(
        graph,
        positions,
        edge_color="#9A9A9A",
        arrows=True,
        arrowsize=9,
        width=0.7,
        alpha=0.55,
        ax=axes,
    )
    nx.draw_networkx_labels(
        graph,
        positions,
        labels={node: _node_label(graph, node) for node in graph.nodes},
        font_size=7,
        ax=axes,
    )
    axes.legend(
        handles=[
            mpatches.Patch(color=LABEL_COLORS.get(label, "#CCCCCC"), label=label)
            for label in labels_present
        ],
        loc="upper left",
        fontsize=9,
        frameon=True,
    )
    axes.set_title(title, fontsize=14)
    axes.axis("off")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return path


def _summarise(graph: nx.DiGraph) -> str:
    counts: Dict[str, int] = {}
    for _, attributes in graph.nodes(data=True):
        label = attributes.get("label", "?")
        counts[label] = counts.get(label, 0) + 1
    return ", ".join(f"{label} {count}" for label, count in sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize part of the NovaTel graph.")
    parser.add_argument("--category", default="C17", help="Category code to render.")
    parser.add_argument(
        "--service-map",
        action="store_true",
        help="Render the Service/Channel/Verification/Requirement map instead.",
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    graph = load_graph()

    if args.service_map:
        subgraph = service_map_subgraph(graph)
        stem = "service_map"
        title = "NovaTel KG - service concept map (co-occurrence edges)"
    else:
        subgraph = category_subgraph(graph, args.category)
        name = graph.nodes[f"Category::{args.category}"].get("name", args.category)
        stem = f"subgraph_{args.category}"
        title = f"NovaTel KG - {args.category} {name}: documents and content concepts"

    print(f"subgraph: {subgraph.number_of_nodes()} nodes / {subgraph.number_of_edges()} edges")
    print(f"  {_summarise(subgraph)}")

    written: List[Tuple[str, Optional[Path]]] = [
        ("html", render_pyvis(subgraph, args.output_dir / f"{stem}.html", title)),
        ("png", render_matplotlib(subgraph, args.output_dir / f"{stem}.png", title)),
    ]
    for kind, path in written:
        if path is None:
            print(f"  {kind:<4}: skipped (renderer not installed)")
        else:
            print(f"  {kind:<4}: {path}")
    return 0 if any(path for _, path in written) else 1


if __name__ == "__main__":
    raise SystemExit(main())
