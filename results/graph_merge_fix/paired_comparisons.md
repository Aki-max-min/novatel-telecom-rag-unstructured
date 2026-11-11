# graph_merge_fix: paired comparisons

Question level, 42 pairs; wins = first arm better on that question; exact two-sided McNemar on the discordant pairs; paired bootstrap 95% CI (10,000 question resamples, seed 20261031) in points of the per-question value. strict: fully correct in a majority of runs; partial: per-question mean score / 2; lenient: score >= 1 in a majority of runs. Fewer than 10 discordant pairs = low power: the p value cannot reach 0.05 for small w/l splits.

## Rule: strict

| comparison | wins | losses | ties | McNemar p | 95% CI (pts) | mean diff (pts) | discordant < 10 | wins on | losses on |
|---|---|---|---|---|---|---|---|---|---|
| GF vs B2 | 0 | 1 | 41 | 1.0000 | [-4.8, +0.0] | -1.6 | yes | [] | ['MH_RB_B05'] |
| GFL vs B2 | 0 | 1 | 41 | 1.0000 | [-7.1, +2.4] | -1.6 | yes | [] | ['MH_RB_B05'] |
| GFL vs GF | 0 | 0 | 42 | 1.0000 | [-2.4, +2.4] | +0.0 | yes | [] | [] |

## Rule: partial

| comparison | wins | losses | ties | McNemar p | 95% CI (pts) | mean diff (pts) | discordant < 10 | wins on | losses on |
|---|---|---|---|---|---|---|---|---|---|
| GF vs B2 | 0 | 1 | 41 | 1.0000 | [-2.4, +0.0] | -0.8 | yes | [] | ['MH_RB_B05'] |
| GFL vs B2 | 1 | 1 | 40 | 1.0000 | [-3.6, +1.2] | -0.8 | yes | ['Q20'] | ['MH_RB_B05'] |
| GFL vs GF | 1 | 1 | 40 | 1.0000 | [-1.2, +1.2] | +0.0 | yes | ['Q20'] | ['MH_RB_B05'] |

## Rule: lenient

| comparison | wins | losses | ties | McNemar p | 95% CI (pts) | mean diff (pts) | discordant < 10 | wins on | losses on |
|---|---|---|---|---|---|---|---|---|---|
| GF vs B2 | 0 | 0 | 42 | 1.0000 | [+0.0, +0.0] | +0.0 | yes | [] | [] |
| GFL vs B2 | 0 | 0 | 42 | 1.0000 | [+0.0, +0.0] | +0.0 | yes | [] | [] |
| GFL vs GF | 0 | 0 | 42 | 1.0000 | [+0.0, +0.0] | +0.0 | yes | [] | [] |
