# CourtSim v0.54 franchise storage and transaction contracts

Version `0.54.0` introduces three coordinated boundaries.

Franchise checkpoints use artifact schema 2 and may be stored as deterministic gzip
files. The runner manifest keeps a contiguous metadata prefix while a retention policy
keeps the initial checkpoint, the latest configured count, and periodic anchors.
Unneeded checkpoint files are pruned while their seed and digest metadata remain.
Artifact schemas 1 and runner manifest schema 1 are migrated on read.

Draft assets use ordered, non-overlapping selection ranges. A matched condition may
defer the obligation, convert it to a configured round in the next draft, or let the
original team retain it. NBA franchise composition seeds seven future draft years and
uses conservative Stepien accounting: a conditional incoming first is not treated as
a guaranteed first-round pick.

Bilateral negotiations support four through eight rounds, with five rounds as the
default. Round three may add owned-pick compensation; later rounds add binding salary
and remaining-years conditions for included player contracts. Canonical execution
rechecks those conditions atomically.
