# CourtSim 0.55 cross-machine handoff

This is the current low-context handoff for the NBA franchise branch. It supersedes
`handoff-v0.54.md`; older handoffs remain historical evidence only.

## Source boundary

- Repository: `cc78978559/courtsim`
- Local branch: `agent/integrate-trade-cap-season`
- Remote WIP branch: `origin/agent/integrate-trade-cap-season`
- Stacked local manager-promotion branch: `agent/nba-manager-promotion-v1`
- WIP integration baseline: v7 freeze commit `4081f97` or newer
- Frozen engine package: `0.54.0`
- WIP candidate package: `0.55.0.dev0`
- Frozen release registry format: `55`
- Frozen quick simulator: `nba-quick-sim-executor-v6`
- WIP quick-sim candidate: `nba-quick-sim-executor-v7`
- Franchise: `nba-franchise-v6`
- Franchise artifact: `nba-franchise-artifact-v4`
- WIP franchise runner: `nba-franchise-runner-v5` / manifest schema 3
- Frozen franchise runner: `nba-franchise-runner-v4` / manifest schema 2

The work branch is restorable from GitHub and intentionally remains unmerged. Generated
`work/` checkpoints, `.cache`, `.venv`, coverage files, downloaded data, and event ledgers are
outside the Git boundary and must not be committed.

The stacked `agent/nba-manager-promotion-v1` branch adds the thirty-team focal-policy experiment
described in `docs/nba-manager-promotion-v1.md`. Publish it only as a WIP branch and Draft PR stacked
on PR #45. Until that push and remote CI complete, its ignored `work/manager-promotion/` cells are
not remotely backed up. The policy remains Shadow even if a future candidate receipt passes.

The second long-management repair batch also makes manager learning tenure-aware, clears
non-conflicting bilateral and three-team trades together, and records substantive three-team
contract counteroffers and failed negotiations. These remain WIP candidate capabilities and do
not alter the frozen release registry.

## Publish the prepared branch

Current readiness: **remote WIP backup, not a release**. The branch contains the post-v6 calendar,
offseason, obligation, Bird-rights, retention, Finals, three-team negotiation, and real-roster
integration work. It has not been merged, tagged, or promoted in `governance/current-release.json`.
The v7 freeze commit passed a fresh CPython 3.12 clean-checkout gate: 694 tests collected, 692
passed, two environment-specific skips, formatting, lint, strict mypy, and the unchanged 85%
coverage threshold. Isolated sdist/wheel construction and a fresh wheel install smoke passed.
Remote CI run `31888541136` passed Ubuntu, Windows, and package-smoke jobs for freeze commit
`4081f97`. The candidate may now be considered for a separate merge review, but is not merged,
tagged, or released.

Run from a clean source tree after the complete local gate passes:

```powershell
.\tools.cmd project-status
.\tools.cmd check
git status --short --branch
git push -u origin agent/integrate-trade-cap-season
```

Subsequent pushes update only `origin/agent/integrate-trade-cap-season`. Do not merge into `main`,
create a release tag, or rewrite the frozen release registry as part of WIP backup maintenance.

## Restore on another Windows machine

```powershell
git clone https://github.com/cc78978559/courtsim.git
cd courtsim
git switch --track origin/agent/integrate-trade-cap-season
.\tools.cmd bootstrap
.\tools.cmd project-status
.\tools.cmd check-fast
.\tools.cmd check-franchise
```

`project-status` must report release format `55`, `release.hashes_ok=true`, no mismatches, and the
four versions listed above. Run `tools.cmd check` before changing a schema, promoting another
component, merging, or tagging.

## v6 promotion evidence

The tracked evidence chain is:

1. `experiments/gates/postseason-schedule-v6-long-holdout-v1.json` freezes the 30-season design;
2. `experiments/gates/nba-full-engine-strength035-reality-long-v1.json` freezes the reality gate;
3. `experiments/gates/quick-sim-engine-consistency-strength035-long-v1.json` freezes the paired
   aggregate/full-engine gate;
4. `experiments/promotion/nba-quick-sim-executor-v6.json` records both passed outcomes and hashes;
5. `governance/nba-quick-sim-executor-v6.json` pins the promotion receipt hash; and
6. `governance/current-release.json` pins the executor and downstream franchise artifacts.

The full engine completed 30 seasons and the paired aggregate path completed 30. Reality metrics
passed 6/6; mean team-rank Spearman was `0.7929` against `0.75`; champion seed mean was `1.9333`.
Exact run, resume, and final-gate commands are in `docs/v6-long-holdout-runbook.md`.

The compact promotion receipt is sufficient for Git transfer. To preserve the large local run as
well, separately copy these ignored files together:

```text
work/quick-sim/long-holdout-v6-strength035-v1.json
work/quick-sim/long-holdout-v6-strength035-v1.manifest.json
work/quick-sim/long-holdout-v6-strength035-v1-aggregate.json
work/quick-sim/long-holdout-v6-strength035-v1-aggregate.manifest.json
work/quick-sim/long-holdout-v6-strength035-v1-reality-gate.json
work/quick-sim/long-holdout-v6-strength035-v1-consistency.json
```

Do not transfer a checkpoint without its adjacent manifest. If the large files are unavailable,
rerun the frozen commands. Their exact inputs are tracked and verified by:

```powershell
.\tools.cmd hydrate-long-test
```

The tracked receipt remains the historical release decision record and does not promote later WIP
schedule, Finals, or real-roster semantics.

## Franchise checkpoint transfer and migration

Copy the complete franchise run directory outside Git, including `manifest.json` and all retained
`.json`/`.json.gz` checkpoints. Verify it on the destination:

```powershell
.\tools.cmd nba-franchise-status <run-directory>\manifest.json
```

Artifact v4 reads artifact v1-v3 envelopes and migrates franchise v3-v5 state identities to v6.
Runner v4 migrates v2/v3 manifests and preserves each checkpoint's recorded seed version. Pruned
checkpoint metadata remains valid and does not require an already-pruned file. Runner schema 3
also binds the canonical execution configuration hash. Retention stages replacement files, commits
the new manifest, and only then garbage-collects paths referenced by the old manifest.

## Capability boundary

Implemented on this WIP branch but not promoted as a release:

- `draft-obligation-ledger-v3` freezes assets in bilateral and three-team generation/execution and
  is re-derived after settlement to release resolved obligations;
- the released `three-team-market-v1` outer clearing contract now carries and executes
  `three-team-market-v2` condition trees with four-to-eight-round bounds;
- Bird Rights accrue, transfer, clear, and authorize AI over-cap signings through the persisted
  `CapLedger`;
- the unchanged 1,230-game NBA matchup matrix spans 174 days/164 game dates and is gated for daily
  volume, league off days, a separate All-Star break, back-to-backs, consecutive games, and rest;
- `--player-rosters` loads 451 source-pinned targets, caps team rosters at fifteen, samples
  low-frequency depth appearances with low-sample shrinkage, and records possession-free player
  season aggregates;
- route, creation-mode, and tactical-action vocabularies are observable but do not yet constitute
  a passed causal tactical intervention system; and
- the real-roster macro, player, and paired-engine gates completed and passed their frozen 30-season
  v7 holdout; the resulting receipt is a local WIP candidate, not a release promotion.

The v7 candidate froze one disjoint 30-season master seed and a paired aggregate batch in
`experiments/gates/real-player-v7-long-holdout-v1.json`. Exact resume and gate commands are in
`docs/v7-long-holdout-runbook.md`; all three gates passed. The candidate receipt marks v6 as
superseded for current semantics while leaving the historical v6 receipt and frozen release
registry untouched. Do not merge, tag, or publish a release before remote CI and a separate review.
Remote CI has now passed; the separate merge/release decision remains intentionally unmade.

## Minimal reading order

1. `docs/current-state.md`
2. `governance/current-release.json`
3. `PROJECT_STATUS.md`
4. `docs/nba-quick-sim-executor-v6.md`
5. `experiments/promotion/nba-quick-sim-executor-v6.json`
6. only the source and focused contract document for the next task

Use `docs/tooling-efficiency-v1.md` for local command routing. Do not load historical phase files,
large checkpoints, or event JSONL into a model context unless investigating a specific event chain.
