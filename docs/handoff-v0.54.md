# CourtSim 0.54 cross-machine handoff (archived)

This is a historical snapshot. Use `handoff-v0.55.md` for the current branch map,
released v6 postseason scheduler, and GitHub transfer instructions.

## Source boundary

- Repository: `cc78978559/courtsim`
- Working branch: `agent/integrate-trade-cap-season`
- Release registry: `governance/current-release.json`
- Engine: `0.54.0`
- Franchise contracts: `nba-franchise-v5`, artifact v3, runner v3
- Generated `work/` checkpoints are excluded from Git and require separate transfer.

Do not assume `main` contains this branch. Do not copy `.venv`, caches, coverage data,
or generated event ledgers through Git.

## Restore

```powershell
git clone https://github.com/cc78978559/courtsim.git
cd courtsim
git switch --track origin/agent/integrate-trade-cap-season
.\tools.cmd bootstrap
.\tools.cmd project-status
.\tools.cmd check-fast
```

Before release or further schema changes, run:

```powershell
.\tools.cmd check
```

`project-status` must report the intended branch, a clean workspace after checkout,
the expected upstream, and `release.hashes_ok=true`.

## Franchise checkpoint transfer

Copy the complete run directory outside Git, including `manifest.json` and retained
`.json`/`.json.gz` checkpoints. Then run:

```powershell
.\tools.cmd nba-franchise-status <run-directory>\manifest.json
```

The command verifies manifest continuity, deterministic season seeds, retained file
digests, embedded state digests, league identity, compression metadata, and the latest
checkpoint. Pruned checkpoint metadata remains valid and does not require the deleted file.

## Minimal reading order

1. `docs/current-state.md`
2. `governance/current-release.json`
3. `PROJECT_STATUS.md`
4. `docs/nba-franchise-storage-and-transactions-v0.54.md`
5. only the source files directly related to the next task

Use `docs/tooling-efficiency-v1.md` for command routing. Avoid loading all historical
phase documents into an agent context.
