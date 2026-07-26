# Manager experiment runner v1

Status: local release candidate, 2026-07-26.

## Purpose

`manager-experiment-v1` is the resumable orchestration layer that generates governed
incumbent/Shadow evidence across independent league sources and multiple seasons. The runner
owns pairing, state continuity, storage, resumption, evidence evaluation, and integrity
verification. A season executor adapter owns the actual league simulation.

## Experiment plan

A plan freezes:

- experiment and candidate policy identifiers;
- unique independent master seeds;
- starting season and horizon;
- the exact sorted league team set;
- one shared initial-state payload;
- evidence weights and activation thresholds.

The plan and initial state are written before any season executes. Reusing an output directory
with a different plan is rejected.

## Paired execution

For each source, the runner creates `INCUMBENT` and `SHADOW` arms. Both begin with the exact
same initial state and master seed. Each arm then carries only its own returned state into its
next season, allowing roster, contracts, careers, and manager choices to diverge naturally
without contaminating the paired starting condition.

The executor receives an immutable request containing the experiment, policy, arm, source,
seed, season, and prior state. It must return:

- the next complete league-state payload;
- normalized metrics for every governed team;
- an audit payload linking domain-specific season and offseason artifacts.

## Resumption and integrity

Each source/arm/season is an independent cell. A completed cell is reused only when its request
digest, state hash, execution digest, team coverage, and continuity match the frozen plan.
Interrupted runs leave valid cells in place and execute only missing work on the next run.

The final report contains every cell hash and the recomputed `manager-evidence-v1` result. A
manifest binds the plan, initial state, cells, and report. Verification rejects changed files,
path escapes, missing arms, reordered cells, broken state chains, or evidence that cannot be
derived from stored outcomes.

## Safety boundary

The runner produces an activation recommendation and evidence digest only. It does not modify a
release registry or grant `ASSIST`/`ACTIVE` authority. Those remain separate, explicit actions.

## Remaining adapter work

The orchestration contract is complete. A production CourtSim adapter must still translate the
canonical league state into schedules, games, playoffs and offseason execution, then calculate
the four normalized outcome metrics from their audited ledgers.
