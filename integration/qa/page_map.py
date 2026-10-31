"""
Derived chunk -> page mapping for the public TRAI PDFs.

WHY THIS EXISTS: the text chunks in data/experiments/public_pdfs/ carry no page
number (chunking ran over whole-document text). Page-level citations are
nevertheless a requirement, and the source PDFs are on disk. So each chunk is
located in the PDF by matching word 6-gram shingles of the chunk text against the
per-page text extracted with PyMuPDF. The page with the largest share of the
chunk's shingles is the chunk's page; every page holding >= 20% of the shingles
goes into `pages` (chunks can straddle a page break).

THIS IS A DERIVED VALUE, NOT A STORED ONE. Every entry records its `overlap`
(share of chunk shingles found on the chosen page) so weak matches are visible,
and build() reports how many chunks matched well. Synthetic documents have no
pages (they are .md/.json/.docx), so they get page_number = None -- never a guess.

    python -m integration.qa.page_map          # (re)build data/eval/public_chunk_page_map.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PDF_ROOT = ROOT / "data" / "raw" / "real_world" / "public_pdfs"
CHUNK_META = ROOT / "data" / "experiments" / "public_pdfs" / "vectorstore" / "chunk_metadata_enriched.json"
MAP_PATH = ROOT / "data" / "eval" / "public_chunk_page_map.json"

SHINGLE = 6
PAGE_SHARE_MIN = 0.20
GOOD_OVERLAP = 0.60

_cache = None


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _shingles(tokens: list[str]) -> set:
    return {" ".join(tokens[i:i + SHINGLE]) for i in range(max(0, len(tokens) - SHINGLE + 1))}


def _pdf_for(file_path: str) -> Path | None:
    p = PDF_ROOT / Path(file_path.replace("\\", "/"))
    if p.exists():
        return p
    matches = list(PDF_ROOT.rglob(Path(file_path.replace("\\", "/")).name))
    return matches[0] if matches else None


def build() -> dict:
    import fitz  # PyMuPDF

    with open(CHUNK_META, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    by_pdf: dict[str, list] = {}
    for c in chunks:
        by_pdf.setdefault(c["file_path"], []).append(c)

    mapping: dict[str, dict] = {}
    unmatched_pdfs = []
    for file_path, group in sorted(by_pdf.items()):
        pdf = _pdf_for(file_path)
        if pdf is None:
            unmatched_pdfs.append(file_path)
            continue
        doc = fitz.open(str(pdf))
        page_sh = [_shingles(_tokens(page.get_text())) for page in doc]
        n_pages = len(page_sh)
        doc.close()
        for c in group:
            sh = _shingles(_tokens(c["text"]))
            if not sh:
                continue
            overlaps = [len(sh & ps) / len(sh) for ps in page_sh]
            best = max(range(n_pages), key=lambda i: overlaps[i])
            pages = [i + 1 for i, o in enumerate(overlaps) if o >= PAGE_SHARE_MIN]
            mapping[c["chunk_id"]] = {
                "page": best + 1 if overlaps[best] > 0 else None,
                "pages": pages or ([best + 1] if overlaps[best] > 0 else []),
                "overlap": round(overlaps[best], 3),
                "n_pages_in_pdf": n_pages,
            }

    good = sum(1 for v in mapping.values() if v["overlap"] >= GOOD_OVERLAP)
    report = {
        "method": f"{SHINGLE}-gram shingle overlap of chunk text vs PyMuPDF per-page text (DERIVED, not stored)",
        "chunks_total": len(chunks),
        "chunks_mapped": len(mapping),
        "chunks_good_overlap_ge_0.60": good,
        "share_good": round(good / len(chunks), 4) if chunks else None,
        "pdfs_not_found": unmatched_pdfs,
    }
    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump({"report": report, "map": mapping}, f)
    return report


PAGE_MIN_OVERLAP = 0.30  # below this the match is not trusted (7 of 1162 chunks, all scattered/bogus pages)


def get_page_info(chunk_id: str) -> dict | None:
    """{'page','pages','overlap'} for a public chunk, else None.

    None for synthetic documents (no pages exist) and for the few public chunks
    whose best page matches < PAGE_MIN_OVERLAP: a page is never asserted on a weak match.
    """
    global _cache
    if _cache is None:
        _cache = json.load(open(MAP_PATH, "r", encoding="utf-8"))["map"] if MAP_PATH.exists() else {}
    info = _cache.get(chunk_id)
    if info is None or info["page"] is None or info["overlap"] < PAGE_MIN_OVERLAP:
        return None
    return info


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
