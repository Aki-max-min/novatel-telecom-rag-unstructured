"""
Regenerate ONE entry of integration/tests/fixtures/golden_prompts_bf41951.json (no LLM) and record why.

    .venv_colpali/Scripts/python.exe -m integration.eval.regenerate_golden_prompt --query-id Q04 --reason parser --check
    .venv_colpali/Scripts/python.exe -m integration.eval.regenerate_golden_prompt --query-id Q04 --reason parser --write

The entry is rebuilt exactly as integration/tests/test_rag_defaults_identical.py rebuilds it (default RagConfig path: structured search ->
unstructured search -> reciprocal_rank_fusion -> build_context(top_n=DEFAULT_TOP_N)). Every OTHER entry is left byte-for-byte as it was and is
re-checked against the current code: the script refuses to write when any other prompt differs. Each regeneration is appended to the fixture's
"regenerations" list (query id, reason, date, repository commit, old and new context sha256), so the fixture says that it no longer equals
what bf41951 produced for that question and why. --reason is required (for example "parser").
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "integration" / "tests" / "fixtures" / "golden_prompts_bf41951.json"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT).stdout.strip()


def rebuild(rows: list[dict]) -> dict[str, dict]:
    """query_id -> {n_blocks, evidence_ids, context_sha256} from the CURRENT code with the default configuration."""
    sys.path.insert(0, str(ROOT))
    from integration.rag.context_builder import DEFAULT_TOP_N, build_context
    from integration.rag.fuse import reciprocal_rank_fusion
    from integration.rag.pipeline import StructuredSearchAdapter, UnstructuredSearcher

    structured, unstructured = StructuredSearchAdapter(), UnstructuredSearcher()
    out = {}
    try:
        for row in rows:
            ctx = build_context(reciprocal_rank_fusion(structured.search(row["question"]), unstructured.search(row["question"])), top_n=DEFAULT_TOP_N)
            out[row["query_id"]] = {"n_blocks": len(ctx["evidence"]),
                                    "evidence_ids": [[e["source"], e["record_id"]] for e in ctx["evidence"]],
                                    "context_sha256": hashlib.sha256(ctx["context_text"].encode("utf-8")).hexdigest()}
    finally:
        structured.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query-id", required=True)
    ap.add_argument("--reason", required=True, help='why the golden changes, for example "parser"')
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report only")
    mode.add_argument("--write", action="store_true", help="update the fixture")
    args = ap.parse_args()

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    rows = golden["prompts"]
    if args.query_id not in {r["query_id"] for r in rows}:
        raise SystemExit(f"{args.query_id} is not in the fixture")
    now = rebuild(rows)
    others_changed = [r["query_id"] for r in rows if r["query_id"] != args.query_id
                      and (now[r["query_id"]]["context_sha256"] != r["context_sha256"]
                           or now[r["query_id"]]["evidence_ids"] != [list(x) for x in r["evidence_ids"]])]
    target = next(r for r in rows if r["query_id"] == args.query_id)
    new = now[args.query_id]
    print(f"{args.query_id}: old sha {target['context_sha256'][:16]} blocks {target['n_blocks']}; new sha {new['context_sha256'][:16]} blocks {new['n_blocks']}")
    print(f"old evidence: {target['evidence_ids']}\nnew evidence: {new['evidence_ids']}")
    print(f"other prompts unchanged: {len(rows) - 1 - len(others_changed)} of {len(rows) - 1}; changed: {others_changed or 'none'}")
    if others_changed:
        raise SystemExit("refusing: other prompts differ from the stored golden; nothing written")
    if not args.write:
        return 0
    entry = {"query_id": args.query_id, "reason": args.reason, "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
             "repository_commit": _git("rev-parse", "HEAD"), "old_context_sha256": target["context_sha256"], "new_context_sha256": new["context_sha256"],
             "old_evidence_ids": target["evidence_ids"], "new_evidence_ids": new["evidence_ids"]}
    target.update(new)
    golden.setdefault("regenerations", []).append(entry)
    # same serialisation as the stored file (indent 1, no trailing newline, the working copy's CRLF), so only the changed entry differs
    GOLDEN.write_bytes(json.dumps(golden, indent=1, ensure_ascii=False).replace("\n", "\r\n").encode("utf-8"))
    print(f"written: {GOLDEN.relative_to(ROOT)} ({len(golden['regenerations'])} regeneration(s) recorded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
