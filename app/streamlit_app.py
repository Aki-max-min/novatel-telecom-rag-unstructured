"""
NOVATEL KNOWLEDGE QUEST -- pixel-art / retro-arcade front end for the NovaTel RAG system.

Run:  streamlit run app/streamlit_app.py

This file is presentation only. Every pipeline decision (routing, retrieval, fusion, abstention, generation,
citation verification) is made by integration.qa.system.answer_query(query, config); the UI renders the
returned dict. All text that comes from documents, the database or the model is HTML-escaped before it is
placed in markup. No sprites or trademarked artwork: only CSS, system/Google fonts and unicode.
"""

from __future__ import annotations

import html
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from integration.qa.config import QAConfig  # noqa: E402
from integration.qa.system import answer_query, get_unstructured  # noqa: E402
from query_router.registry import router_names, router_status  # noqa: E402

DEMO_FILE = ROOT / "demo" / "demo_questions.json"
ROUTE_STYLE = {
    "structured": ("DATABASE", "#00e5ff"),
    "unstructured": ("DOCUMENTS", "#b388ff"),
    "hybrid": ("HYBRID", "#ffd600"),
    "out_of_scope": ("OUT OF SCOPE", "#ff5252"),
}
STATUS_STYLE = {"SUPPORTED": "#00e676", "WEAK": "#ffd600", "UNSUPPORTED": "#ff5252"}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap');
:root { --bg:#0d0b1e; --panel:#1a1636; --ink:#e8e6ff; --dim:#9a97c4; --cyan:#00e5ff; --pink:#ff2e93;
        --lime:#00e676; --amber:#ffd600; --red:#ff5252; --violet:#b388ff; }
html, body, [class*="stApp"] { background: var(--bg) !important; color: var(--ink); }
.stApp, .stMarkdown, p, li, label, .stTextInput input, .stTextArea textarea, .stSelectbox, .stCheckbox {
  font-family: 'VT323', 'Courier New', monospace !important; font-size: 1.25rem; }
h1, h2, h3, .pixel { font-family: 'Press Start 2P', 'Courier New', monospace !important; letter-spacing: 1px; }
.title { font-family:'Press Start 2P','Courier New',monospace; color: var(--cyan); font-size: 1.5rem; line-height: 2.2rem;
         text-shadow: 4px 4px 0 var(--pink); margin: .4rem 0 .2rem 0; }
.cursor { display:inline-block; width:.8rem; height:1.4rem; background:var(--lime); margin-left:.5rem;
          vertical-align:middle; animation: blink 1s steps(1) infinite; }
@keyframes blink { 50% { opacity: 0; } }
.sub { color: var(--dim); font-size:1.15rem; margin-bottom:1rem; }
.box { background: var(--panel); border: 4px solid var(--ink); box-shadow: 6px 6px 0 #000; padding: .8rem 1rem; margin: .8rem 0; }
.badge { display:inline-block; font-family:'Press Start 2P','Courier New',monospace; font-size:.7rem; padding:.35rem .5rem;
         border:3px solid #000; box-shadow:3px 3px 0 #000; margin:.15rem .35rem .15rem 0; color:#000; }
.cite { display:inline-block; font-family:'Press Start 2P','Courier New',monospace; font-size:.55rem; padding:.15rem .3rem;
        border:2px solid #000; margin-left:.3rem; color:#000; vertical-align:middle; }
.sentence { font-size:1.35rem; line-height:1.7rem; margin:.45rem 0; padding-left:.6rem; border-left:6px solid var(--dim); }
.sentence.SUPPORTED { border-left-color: var(--lime); } .sentence.WEAK { border-left-color: var(--amber); }
.sentence.UNSUPPORTED { border-left-color: var(--red); }
.legend span { margin-right:1rem; }
.idk { border-color: var(--red); text-align:center; }
.idk .big { font-family:'Press Start 2P','Courier New',monospace; font-size:1.2rem; color: var(--red); text-shadow:3px 3px 0 #000; }
.half { border-color: var(--amber); }
.dim { color: var(--dim); }
.kv { font-size:1.05rem; color: var(--dim); }
.evtext { font-size:1.05rem; white-space:pre-wrap; background:#0a0818; border:2px dashed var(--dim); padding:.5rem; }
.mark { background:#4a3f00; }
div.stButton > button { font-family:'Press Start 2P','Courier New',monospace !important; font-size:.75rem; background: var(--pink);
  color:#fff; border:4px solid #000; box-shadow:5px 5px 0 #000; border-radius:0; padding:.7rem 1rem; }
div.stButton > button:hover { background: var(--cyan); color:#000; }
section[data-testid="stSidebar"] { background:#120f2b; border-right:4px solid var(--ink); }
.stTextArea textarea, .stTextInput input { background:#0a0818 !important; color: var(--ink) !important; border:4px solid var(--ink) !important; border-radius:0 !important; }
</style>
"""


def esc(text) -> str:
    return html.escape("" if text is None else str(text))


# ---------------------------------------------------------------------------
# cached resources
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def warm_up():
    """Load the FAISS index, encoder and CrossEncoder once per server process."""
    get_unstructured()
    return True


@st.cache_data(show_spinner=False)
def router_choices() -> list[dict]:
    rows = []
    for name in router_names():
        ok, reason = router_status(name) if name != "auto" else (True, "")
        rows.append({"name": name, "available": ok, "reason": reason})
    return rows


@st.cache_data(show_spinner=False)
def load_demo() -> list[dict]:
    if not DEMO_FILE.exists():
        return []
    return json.loads(DEMO_FILE.read_text(encoding="utf-8")).get("questions", [])


# ---------------------------------------------------------------------------
# rendering helpers
# ---------------------------------------------------------------------------
def badge(text: str, colour: str) -> str:
    return f'<span class="badge" style="background:{colour}">{esc(text)}</span>'


def render_route(result: dict) -> None:
    route = result["route"]
    final = route.get("final_route") or route.get("label")
    label, colour = ROUTE_STYLE.get(final, (str(final).upper(), "#ffffff"))
    parts = [badge(f"ROUTE: {label}", colour)]
    if route.get("confidence") is not None and not route.get("forced"):
        parts.append(badge(f"CONFIDENCE {route['confidence']:.2f}", "#e8e6ff"))
    parts.append(badge(f"ROUTER: {result.get('router_name') or 'n/a'}", "#ff2e93"))
    st.markdown("".join(parts), unsafe_allow_html=True)

    notes = []
    if route.get("forced"):
        notes.append("Route FORCED from the sidebar (ablation) - the router was not consulted.")
    low = route.get("low_confidence_to_hybrid")
    if low:
        notes.append(f"Router said <b>{esc(low['original_label'])}</b> with confidence {low['confidence']:.2f} "
                     f"(below the calibrated {low['threshold']:.2f}) - treated as HYBRID.")
    for s in (route.get("chain_skipped") or []):
        notes.append(f"Skipped router <b>{esc(s['router'])}</b>: {esc(s['reason'])}")
    for e in route.get("errors") or []:
        notes.append(f"Router error: {esc(e)}")
    if route.get("emergency_fallback"):
        notes.append(f"Emergency fallback used: {esc(route['emergency_fallback'])}")
    fb = result.get("fallback") or {}
    if fb.get("occurred"):
        outcome = "recovered" if fb.get("recovered") else "did not help"
        notes.append(f"Safety net: {esc(fb.get('from_route'))} evidence was weak, so the other source was tried ({outcome}).")
    for n in notes:
        st.markdown(f'<div class="kv">&gt; {n}</div>', unsafe_allow_html=True)


def render_hybrid(result: dict) -> None:
    d = result.get("hybrid_diagnostics")
    if not d:
        return
    rows = (
        f"<div><b>DATABASE SUB-QUERY</b>: {esc(d.get('structured_sub_query') or 'none produced')}"
        f" <span class='dim'>({esc(d.get('decomposer_method'))}; found: {d.get('structured_half_found')})</span></div>"
        f"<div><b>DOCUMENT SUB-QUERY</b>: {esc(d.get('unstructured_sub_query'))}"
        f" <span class='dim'>(found: {d.get('unstructured_half_found')})</span></div>"
        f"<div class='dim'>cited sources: {esc(', '.join(d.get('sources_cited_in_answer') or []) or 'none')}</div>"
    )
    st.markdown(f'<div class="box">{rows}</div>', unsafe_allow_html=True)


def render_abstention(result: dict) -> None:
    ab = result.get("abstention") or {}
    st.markdown(
        '<div class="box idk"><div class="big">I DON\'T KNOW THAT ONE</div>'
        f'<p>{esc(result["answer_text"])}</p>'
        f'<div class="kv">stopped at layer {esc(ab.get("layer"))}: {esc(ab.get("reason"))}</div></div>',
        unsafe_allow_html=True)


def render_answer(result: dict) -> None:
    if not result["sentences"] and not result.get("unanswered"):
        st.markdown(f'<div class="box">{esc(result["answer_text"])}</div>', unsafe_allow_html=True)
        return
    out = ['<div class="box">']
    for s in result["sentences"]:
        status = s["support_status"]
        cites = "".join(f'<span class="cite" style="background:{STATUS_STYLE[status]}">{esc(c)}</span>'
                        for c in s["citations"]) or '<span class="cite" style="background:#ff5252">NO CITATION</span>'
        out.append(f'<div class="sentence {status}">{esc(s["text"])} {cites}'
                   f'<span class="kv"> &nbsp;{esc(status)}</span></div>')
    out.append("</div>")
    st.markdown("".join(out), unsafe_allow_html=True)
    st.markdown(
        '<div class="kv legend"><span style="color:#00e676">&#9632; SUPPORTED</span>'
        '<span style="color:#ffd600">&#9632; WEAK</span><span style="color:#ff5252">&#9632; UNSUPPORTED</span> '
        '- verified against the cited evidence only</div>', unsafe_allow_html=True)
    for part in result.get("unanswered") or []:
        st.markdown(f'<div class="box half"><span class="pixel" style="color:#ffd600">PARTLY ANSWERED</span><br>'
                    f'The evidence does not cover: {esc(part)}</div>', unsafe_allow_html=True)


def _evidence_label(e: dict) -> str:
    mark = "CITED" if e.get("cited") else "context"
    return f"[{e['evidence_id']}] {e['label']}  ({mark})"


def render_evidence(result: dict, debug: bool) -> None:
    evidence = result.get("evidence") or []
    if not evidence:
        return
    st.markdown('<h3>EVIDENCE</h3>', unsafe_allow_html=True)
    db = [e for e in evidence if e["source"] == "structured"]
    docs = [e for e in evidence if e["source"] != "structured"]
    for title, items in (("DATABASE RECORDS", db), ("DOCUMENT PASSAGES", docs)):
        if not items:
            continue
        st.markdown(f'<div class="pixel" style="font-size:.8rem;margin-top:.8rem">{title} ({len(items)})</div>',
                    unsafe_allow_html=True)
        for e in items:
            with st.expander(_evidence_label(e), expanded=bool(e.get("cited")) and len(items) <= 2):
                meta = []
                if e["kind"] == "table_row":
                    meta += [f"table: {e.get('table')}", f"row: {e.get('row_id') or 'aggregate count'}",
                             f"columns: {', '.join(e.get('columns_used') or [])[:200]}"]
                    if e.get("query_or_lookup"):
                        meta.append(f"lookup: {e['query_or_lookup']}")
                else:
                    meta += [f"source: {e.get('corpus')}", f"document: {e.get('document_id')}",
                             f"chunk: {e.get('chunk_id')}",
                             f"page: {e.get('page_number') if e.get('page_number') is not None else 'n/a (not mapped)'}"]
                    if e.get("source_authority"):
                        meta.append(f"authority: {e['source_authority']}")
                    if e.get("ontology_concepts"):
                        meta.append(f"ontology: {', '.join(map(str, e['ontology_concepts']))}")
                    if e.get("relationships"):
                        meta.append(f"graph links: {', '.join(map(str, e['relationships']))}")
                if e.get("origin_subquery"):
                    meta.append(f"origin: {e['origin_subquery']}")
                st.markdown("".join(f'<div class="kv">{esc(m)}</div>' for m in meta), unsafe_allow_html=True)
                text = e["text"]
                for span in e.get("supporting_spans") or []:
                    if span and span in text:
                        text = text.replace(span, "\u0001" + span + "\u0002", 1)
                shown = esc(text[:3000]).replace("\u0001", '<span class="mark">').replace("\u0002", "</span>")
                st.markdown(f'<div class="evtext">{shown}</div>', unsafe_allow_html=True)
                if e.get("supporting_spans"):
                    st.caption("highlighted = the passage the verifier matched to the answer sentence")
                if debug:
                    st.json({"raw_scores": e.get("raw_scores"), "retrieval_method": e.get("retrieval_method"),
                             "dataset": e.get("dataset")})


def render_timings(result: dict) -> None:
    t = result.get("timings") or {}
    st.markdown('<div class="kv">' + " | ".join(f"{k.replace('_ms', '')}: {v:.0f} ms" for k, v in t.items()) + "</div>",
                unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------
def build_config(sidebar: dict) -> QAConfig:
    cfg = QAConfig(
        router=sidebar["router"], forced_route=sidebar["forced_route"],
        use_ontology=sidebar["use_ontology"], use_doc_graph=sidebar["use_doc_graph"], use_colpali=sidebar["use_colpali"],
        top_k_structured=sidebar["top_k_structured"], top_k_unstructured=sidebar["top_k_unstructured"],
        verifier=sidebar["verifier"], drop_unsupported=sidebar["drop_unsupported"], debug=sidebar["debug"],
    )
    return cfg


def sidebar_controls() -> dict:
    st.sidebar.markdown('<div class="pixel" style="font-size:.8rem">PLAYER SETTINGS</div>', unsafe_allow_html=True)
    choices = router_choices()
    labels = {c["name"]: (c["name"] if c["available"] else f"{c['name']}  [UNAVAILABLE]") for c in choices}
    names = [c["name"] for c in choices if c["available"]]
    default = names.index("auto") if "auto" in names else 0
    router = st.sidebar.selectbox("Router", names, index=default, format_func=lambda n: labels[n],
                                  help="'auto' = fine-tuned Laya, else embedding router, else rule router.")
    unavailable = [c for c in choices if not c["available"]]
    if unavailable:
        with st.sidebar.expander(f"Unavailable routers ({len(unavailable)})"):
            for c in unavailable:
                st.markdown(f"**{c['name']}**: {c['reason']}")
    forced = st.sidebar.selectbox("Force route (ablation)", ["router decides", "structured", "unstructured", "hybrid"])
    st.sidebar.markdown('<div class="pixel" style="font-size:.7rem;margin-top:1rem">RETRIEVAL POWER-UPS</div>',
                        unsafe_allow_html=True)
    use_ontology = st.sidebar.checkbox("Ontology concept boost", False)
    use_graph = st.sidebar.checkbox("Document graph expansion", False,
                                    help="Needs knowledge_graph/output/graph.json (python -m knowledge_graph.graph_builder).")
    use_colpali = st.sidebar.checkbox("ColPali page retrieval", False, disabled=True,
                                      help="Availability-gated: needs a free GPU that the local LLM currently occupies.")
    st.sidebar.checkbox("Structured KG", False, disabled=True, help="In the repo but not wired into retrieval.")
    tk_s = st.sidebar.slider("Top-k database rows", 1, 20, 10)
    tk_u = st.sidebar.slider("Top-k document chunks", 1, 10, 5)
    verifier = st.sidebar.selectbox("Citation verifier", ["nli", "lexical"], help="nli = entailment model (CPU, slower).")
    drop = st.sidebar.checkbox("Hide unsupported sentences", False)
    debug = st.sidebar.checkbox("Debug panel", False)

    demos = load_demo()
    if demos:
        st.sidebar.markdown('<div class="pixel" style="font-size:.7rem;margin-top:1rem">DEMO QUESTS</div>',
                            unsafe_allow_html=True)
        for i, d in enumerate(demos):
            if st.sidebar.button(f"{d['kind'][:4].upper()} - {d['question'][:34]}", key=f"demo{i}"):
                st.session_state["query"] = d["question"]
                st.session_state["autorun"] = True
    return {"router": router, "forced_route": None if forced == "router decides" else forced,
            "use_ontology": use_ontology, "use_doc_graph": use_graph, "use_colpali": use_colpali,
            "top_k_structured": tk_s, "top_k_unstructured": tk_u, "verifier": verifier,
            "drop_unsupported": drop, "debug": debug}


def main() -> None:
    st.set_page_config(page_title="NovaTel Knowledge Quest", page_icon="\U0001F579", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown('<div class="title">NOVATEL KNOWLEDGE QUEST<span class="cursor"></span></div>', unsafe_allow_html=True)
    st.markdown('<div class="sub">Ask about customers, policies or regulations. Every sentence is cited and checked. '
                'No evidence = "I don\'t know".</div>', unsafe_allow_html=True)

    settings = sidebar_controls()
    st.session_state.setdefault("query", "")
    st.text_area("INSERT QUESTION", key="query", height=90, placeholder="e.g. Customer 1025 has an overdue invoice - what late fee rules apply?")
    ask = st.button("ASK ▶")
    run = ask or st.session_state.pop("autorun", False)

    if run and st.session_state["query"].strip():
        try:
            with st.spinner("LOADING LEVEL... (first question loads the models)"):
                warm_up()
            with st.spinner("THINKING..."):
                st.session_state["result"] = answer_query(st.session_state["query"].strip(), build_config(settings))
                st.session_state["error"] = None
        except Exception as exc:  # noqa: BLE001
            st.session_state["error"] = f"{type(exc).__name__}: {exc}"
            st.session_state["trace"] = traceback.format_exc()
            st.session_state["result"] = None

    if st.session_state.get("error"):
        st.markdown(f'<div class="box idk"><div class="big">GAME OVER</div><p>{esc(st.session_state["error"])}</p></div>',
                    unsafe_allow_html=True)
        if settings["debug"]:
            st.code(st.session_state.get("trace", ""))
        return

    result = st.session_state.get("result")
    if not result:
        return
    if result.get("error"):
        st.warning(result["error"])

    render_route(result)
    render_hybrid(result)
    if result["abstained"]:
        render_abstention(result)
    else:
        render_answer(result)
    render_evidence(result, settings["debug"])
    render_timings(result)
    if settings["debug"]:
        with st.expander("DEBUG: full result"):
            st.json({k: v for k, v in result.items() if k not in ("evidence",)})


main()
