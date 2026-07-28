# CourtSim manager objective v1

`manager-objective-v1` selects one annual strategic objective for every team before manager
decisions begin.

The white-box candidates are contend, develop, rebuild, cap relief, and balanced. Their scores
use current roster ability, potential, average age, payroll pressure, future first-round picks,
and the original manager personality. Every component remains visible in the audit.

The selected objective creates a bounded effective manager profile. It never mutates the
original profile. The effective profile is then shared by draft, free agency, trade, and
rotation policies so those decisions pursue one coherent team direction.

Objectives are recomputed each season from the current league state. This allows a rebuilding
team to become a contender as its roster changes without requiring opaque state or hidden
weights.
