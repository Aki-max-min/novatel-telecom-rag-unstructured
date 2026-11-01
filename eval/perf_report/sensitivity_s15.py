"""
Sensitivity check (read-only; does NOT replace any headline value). S15 is the E14a negative control ("asdkjaslkdj random gibberish query"; correct behaviour =
abstain). E14a scores it with a fixed list of abstention phrases (integration/eval/base_vs_rag.ABSTENTION_MARKERS). The router arm and arm C answer it with the
system's standard abstention message ("I don't have information about that in the NovaTel knowledge base."), which is a correct abstention but is not in that list, so the
deterministic scorer gives 0. This script recomputes correctness and the paired statistics with S15 counted as correct for exactly those records, and writes the result next
to the headline so both are visible. The marker list and the headline scoring are not changed.

    python eval/perf_report/sensitivity_s15.py   ->   results/perf_report/sensitivity_s15.json
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h  # noqa: E402
import run_report as rr  # noqa: E402

from integration.qa.config import QAConfig  # noqa: E402


def main() -> None:
    qs, raw, scored = rr.load()
    msg = QAConfig().abstention_message
    fixed, adj = [], copy.deepcopy(scored)
    for key, s in adj.items():
        if key[1] == "S15" and s["correctness"] == 0 and raw[key]["answer"].strip() == msg.strip():
            s["correctness"] = 2
            fixed.append(list(key))
    runs = [1, 2, 3]
    out = {"abstention_message": msg, "records_rescored_to_2": fixed, "headline_unchanged": True, "correctness_all": {}, "paired": {}}
    for arm in ("A", "B", "B2", "router", "ontology", "docgraph", "C"):
        out["correctness_all"][arm] = {"headline": rr.mean(rr.arm_metric(arm, "all", "correctness", scored, qs, runs)),
                                       "with_S15_abstention_counted": rr.mean(rr.arm_metric(arm, "all", "correctness", adj, qs, runs)),
                                       "core22_with_S15": rr.mean(rr.arm_metric(arm, "core", "correctness", adj, qs, runs))}
    for k, (a, b) in {"CB": ("C", "B"), "CA": ("C", "A"), "CB2": ("C", "B2"), "routerB2": ("router", "B2")}.items():
        p = rr.paired(a, b, qs, adj, runs)
        out["paired"][k] = {x: p[x] for x in ("wins", "losses", "ties", "p_mcnemar_exact", "ci95_pts", "mean_diff_pts", "loss_ids")}
    (h.RES / "sensitivity_s15.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
