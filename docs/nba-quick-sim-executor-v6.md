# CourtSim NBA quick-simulation executor v6

`nba-quick-sim-executor-v6` is the released 30-team quick-season executor. It corrects the v5
postseason calendar: independent play-in conferences, play-in opening games, and playoff series
in the same round now share their proper start dates. A following round starts only after its
latest feeder series has ended plus the configured round rest. The persisted game ledger is
sorted chronologically with `game_index` as a deterministic tie-break.

The release keeps v5 available only as an explicit legacy execution version. The CLI and
franchise engine default to v6.

## Promotion evidence

The evaluation design was frozen before execution in
`experiments/gates/postseason-schedule-v6-long-holdout-v1.json`. It used 30 paired aggregate and
full-engine seasons with batch id `long-holdout-v6-strength035-v1` and unseen master seed
`20261210`. No interim metric-based stopping or threshold changes were allowed.

The full-engine NBA reality gate passed all six metrics:

| Metric | Observed | Frozen range |
| --- | ---: | ---: |
| win-rate standard deviation | 0.1170 | 0.1002–0.1808 |
| pace per team | 98.5559 | 97.8058–104.6501 |
| offensive rating | 111.5670 | 107.5329–118.2985 |
| point-differential standard deviation | 5.6852 | 2.4465–7.3934 |
| playoff upset rate | 0.3422 | 0.2500–0.6167 |
| champion seed mean | 1.9333 | 1.0000–3.0000 |

The paired engine-consistency gate also passed. Mean team-rank Spearman was `0.7929` against a
minimum of `0.75`; all four continuous paired MAEs and both postseason distribution-mean errors
were within their frozen limits. The formal reports are generated locally under `work/quick-sim`
and remain reproducible from the commands in `v6-long-holdout-runbook.md`.
The tracked compact receipt is `experiments/promotion/nba-quick-sim-executor-v6.json`; governance
pins its hash so the promotion evidence cannot change silently.

## Franchise integration

`nba-franchise-v6` consumes the v6 executor, so play-in and playoff fatigue, injury return dates,
manager-learning samples, career summaries, lottery results, and offseason transitions now use
the corrected postseason calendar. Artifact v4 migrates v3-v5 franchise states, and runner v4
migrates runner v2/v3 manifests while preserving the recorded per-checkpoint seed version.
