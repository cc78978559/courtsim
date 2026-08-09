# CourtSim 0.55 cross-machine handoff

This is the current low-context handoff for the NBA franchise branch. It supersedes
`handoff-v0.54.md`; older handoffs remain historical evidence only.

## Source boundary

- Repository: `cc78978559/courtsim`
- Local branch: `agent/integrate-trade-cap-season`
- Current local upstream before publication: `origin/main`
- Minimum v6 promotion commit: `958b22d`
- Engine package: `0.54.0`
- Frozen release registry format: `55`
- Quick simulator: `nba-quick-sim-executor-v6`
- Franchise: `nba-franchise-v6`
- Franchise artifact: `nba-franchise-artifact-v4`
- Franchise runner: `nba-franchise-runner-v4`

The work branch does not become restorable from GitHub until it is pushed explicitly. Generated
`work/` checkpoints, `.cache`, `.venv`, coverage files, downloaded data, and event ledgers are
outside the Git boundary and must not be committed.

## Publish the prepared branch

Current readiness: **local gate passed; publication pending**. On 2026-08-09 all 662 collected
tests passed and total coverage was `85.28%` against the unchanged frozen `85%` minimum. The
complete `tools.cmd check` passed. The branch remains local until the explicit push below; do not
describe it as remotely recoverable before that push succeeds.

Run from a clean source tree after the complete local gate passes:

```powershell
.\tools.cmd project-status
.\tools.cmd check
git status --short --branch
git push -u origin agent/integrate-trade-cap-season
```

The first push intentionally creates the remote work branch and changes its upstream from
`origin/main` to `origin/agent/integrate-trade-cap-season`. It does not merge into `main` and does
not create a release tag. Review the pushed branch or open a pull request before merging.

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
rerun the frozen commands; the tracked receipt remains the release decision record.

## Franchise checkpoint transfer and migration

Copy the complete franchise run directory outside Git, including `manifest.json` and all retained
`.json`/`.json.gz` checkpoints. Verify it on the destination:

```powershell
.\tools.cmd nba-franchise-status <run-directory>\manifest.json
```

Artifact v4 reads artifact v1-v3 envelopes and migrates franchise v3-v5 state identities to v6.
Runner v4 migrates v2/v3 manifests and preserves each checkpoint's recorded seed version. Pruned
checkpoint metadata remains valid and does not require an already-pruned file.

## Capability boundary

Implemented but not yet the canonical franchise default:

- `draft-obligation-ledger-v3` is a read-only conservative freeze/Stepien audit layer;
- `three-team-market-v2` provides contract-condition negotiation trees; franchise v6 still binds
  the released `three-team-market-v1` market;
- route, creation-mode, and tactical-action vocabularies are observable but do not yet constitute
  a passed causal tactical intervention system; and
- player-level calibration tooling exists, but identity coverage is below its promotion gate.

## Minimal reading order

1. `docs/current-state.md`
2. `governance/current-release.json`
3. `PROJECT_STATUS.md`
4. `docs/nba-quick-sim-executor-v6.md`
5. `experiments/promotion/nba-quick-sim-executor-v6.json`
6. only the source and focused contract document for the next task

Use `docs/tooling-efficiency-v1.md` for local command routing. Do not load historical phase files,
large checkpoints, or event JSONL into a model context unless investigating a specific event chain.
