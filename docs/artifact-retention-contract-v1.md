# Artifact retention classification v1

This tool classifies local generated artifacts. It does not archive, move, or delete
anything.

## Safety model

- A policy must have `status: "draft"`. Draft status is never deletion approval.
- Precedence is fixed in code: `unsafe`, `protected`, `ignored`,
  `archive_candidate`, then `unclassified`. Rule order cannot weaken protection.
- Symlinks are always `unsafe`.
- Unmatched files remain `unclassified`; they are not silently treated as disposable.
- A retention report must be stored outside the root it scans. This avoids a report
  changing its own snapshot.
- Candidate-plan generation verifies the policy hash and rebuilds the complete report.
  A changed policy, file set, size, classification, or edited report stops the operation.
- Candidate-plan generation hashes the selected source files again. It creates only an
  archive plan; it does not invoke archive creation.
- No retention command deletes or prunes source data.

## Commands

```powershell
.\tools.ps1 artifacts-retention-audit work experiments/artifact-retention-policy-review-v1.json governance/artifacts/retention-review-v1.json
.\tools.ps1 artifacts-retention-plan governance/artifacts/retention-review-v1.json governance/artifacts/retention-candidate-plan-v1.json
.\tools.ps1 artifacts-retention-compare governance/artifacts/retention-review-v1.json governance/artifacts/retention-review-next.json governance/artifacts/retention-comparison.json --fail-on-protection-loss
```

The first command writes a deterministic classification report. The second accepts only
a fresh report and writes the existing hash-addressed archive-plan format. Archive
creation remains a separate, explicit command governed by
`docs/artifact-archive-contract-v1.md`.

The comparison command records added and removed paths, size changes, category
transitions, and rule changes. A path that was `protected` and is no longer protected
is a protection loss. With `--fail-on-protection-loss`, the comparison report is still
written for diagnosis and the command returns exit code 10. Moving an unprotected path
into `archive_candidate` is also listed explicitly as an archive-candidate expansion.

## Review interpretation

- `protected`: must not enter the candidate plan.
- `archive_candidate`: eligible for a plan, not authorized for archival or deletion.
- `ignored`: intentionally outside this policy's archive review, not disposable.
- `unclassified`: requires a policy decision.
- `unsafe`: cannot be planned by this workflow.

The repository policy in `experiments/artifact-retention-policy-review-v1.json` is a
conservative draft. Changes to its protected sets should be reviewed as policy changes,
not routine cleanup.
