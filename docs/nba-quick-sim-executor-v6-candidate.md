# CourtSim NBA quick-simulation executor v6 candidate

Status: **candidate only; not promoted**.

## Correctness change

The v5 postseason executor advanced one shared calendar while simulating unrelated series
serially. Consequently, later series in the same round started after earlier series had ended,
and teams on an early bracket path could receive weeks of artificial rest. The v6 candidate:

- starts the Eastern and Western play-in tournaments on the same day;
- starts the 7/8 and 9/10 play-in openers on the same day;
- starts every series in a playoff round on the same day; and
- starts the next round after the latest feeder series finishes, plus the configured rest.

The event ledger is sorted by `(day, game_index)` after simulation so serialization remains
deterministic even though independent series share calendar dates.

## Frozen evaluation

The candidate plan was frozen in
`experiments/gates/postseason-schedule-v6-holdout-v1.json`. Development used master seed
`20261110`; the five-season holdout used unseen master seed `20261120` and batch id
`holdout-v6-strength035-v1`.

Reproduce a v6 run by adding the explicit CLI option
`--executor-version nba-quick-sim-executor-v6` to `nba-quick-sim-run`. Omitting the option keeps
the released v5 behavior. The selected version is pinned in the run manifest and therefore also
participates in resume validation.

The v3 aggregate/full-engine consistency gate passed all metrics. Mean team-rank Spearman was
`0.7951` (minimum `0.75`). The four regular-season paired MAEs passed, as did the two
postseason distribution-mean errors.

The separate full-engine reality gate failed one of six metrics:

| Metric | Observed | Frozen range | Result |
| --- | ---: | ---: | --- |
| win-rate standard deviation | 0.1158 | 0.1002–0.1808 | pass |
| pace per team | 98.6012 | 97.8058–104.6501 | pass |
| offensive rating | 111.5510 | 107.5329–118.2985 | pass |
| point-differential standard deviation | 5.8323 | 2.4465–7.3934 | pass |
| playoff upset rate | 0.4400 | 0.2500–0.6167 | pass |
| champion seed mean | 3.2000 | 1.0000–3.0000 | **fail** |

The five champion seeds were `2, 7, 4, 2, 1`. Removing the single No. 7 seed changes the mean
to `2.25`, demonstrating high finite-sample sensitivity, but it does not change the formal
outcome. The reality source contains only three champion observations (all No. 1 seeds), and its
frozen guardband already expands their mean from `1.0` to an allowed maximum of `3.0`.

## Promotion decision

Do not relax the frozen threshold or add seasons after inspecting this result and then call the
same batch a clean holdout. The v6 code remains outside `governance/current-release.json`, whose
released executor is v5. A future promotion needs a predeclared new evaluation design with enough
championship observations, an eligible unseen seed set, and an explicit rule for low-count
postseason metrics. Until then, report v6 as a correctness candidate with a passed engine-
consistency gate and a marginally failed reality gate.
