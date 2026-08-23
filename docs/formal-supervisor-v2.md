# NBA manager formal supervisor v2

This is a scheduling-only WIP control plane for the already frozen manager study. It does not
change the v1 protocol, semantic plan hash, seeds, thresholds, policy status, or evidence. It must
not be used to reinterpret a partially observed holdout.

## Spec boundary

The supervisor consumes a local ignored JSON spec with version
`nba-manager-formal-supervisor-v2`. The spec binds:

- the exact forty-character frozen Git commit;
- the workspace-relative protocol path and SHA-256;
- the formal output directory and cell-atomic STOP file;
- the complete argument vector, using `{python}` for the current interpreter;
- launch/runtime resource thresholds and an optional heavy-process allowlist.

Validation rejects `--development`, `--sources`, `--seasons`, and `--seed-start`. The command must
contain exactly `--workers 1`, `--maximum-new-sources 1`, and the same protocol/STOP paths declared
by the spec. HEAD must equal the frozen commit, the worktree must be clean, the protocol hash must
match, and an existing STOP file blocks launch.

## Commands

```powershell
.\tools.cmd nba-manager-supervisor-check work/manager-promotion/supervisor-v2.json `
  --root <frozen-worktree> --output work/manager-promotion/preflight-v2.json

.\tools.cmd nba-manager-supervisor-run work/manager-promotion/supervisor-v2.json `
  work/manager-promotion/supervisor-receipt-v2.json `
  --root <frozen-worktree> --execute
```

`check` performs three 10-second-or-longer launch samples. `run` requires the explicit `--execute`
acknowledgement and repeats the same preflight before creating a child process. The default gate is
3.0 GiB free memory, at most 35% CPU, and at least 65 GiB/15% free on C:. Runtime requests a stop
after one sample below 1.25 GiB, two below 1.5 GiB, two above 85% CPU, a disk boundary, or a new
non-allowlisted process at or above 2.5 GiB working set.

The supervisor never terminates the formal child or an external process. It atomically creates the
configured STOP file, then waits for the existing experiment runner to finish its active season
cell and exit. Ctrl+C follows the same cooperative path. Receipts contain binding, resource
snapshots, stop reasons, and child exit code only; `effects_read` is always false. The supervisor
does not open cell payloads, outcomes, evidence, or arm differences.

## Governance

This implementation is not approval to launch or resume the current holdout. A project controller
must create the ignored spec from the exact frozen command and independently review its binding.
The existing formal v1 directory, Draft/Shadow state, thresholds, GitHub PRs, and release registry
remain unchanged.
