# Contracts and free agency v1

CourtSim `0.6.0` adds an offseason management ledger above the roster transaction layer.
The subsystem is deterministic and does not consume simulation randomness.

## Boundary

Management state uses player IDs and roster snapshots rather than embedding player profiles.
This keeps financial facts independent from scouting and simulation ratings. Consumers join
the IDs back to their player registry before constructing the next season's `GameTeam` values.

Offseason rosters may contain fewer than five players after expirations or waivers. The
existing game layer still requires a legal five-player active lineup before simulation.

## Contract rules

Each `PlayerContract` records player ID, team ID, annual salary, and remaining years.
`ContractRules` validates:

- salary cap: 140,000,000 by default;
- salary range: 1,000,000 through 60,000,000;
- maximum term: five years;
- maximum roster: fifteen players.

Every rostered player must have exactly one active contract whose team matches roster
ownership. Free agents cannot have active contracts, and each team's payroll must remain
within the configured cap.

## Year advancement

`advance_contract_year` decrements all non-expiring terms and increments the season year.
Players with one year remaining are removed from their roster, lose the expired contract,
and enter the sorted free-agent pool. Inputs remain immutable and no random address is used.

## Market plans

A `MarketPlan` is an ordered sequence of unique action IDs:

- `WAIVE` removes a player owned by the named team, terminates the contract, and adds the
  player to free agency;
- `SIGN` removes a player from free agency, appends the player to the destination roster,
  and creates a bounded contract.

Every intermediate state is fully validated. If any action fails ownership, free-agent,
roster-capacity, salary, term, or payroll checks, no result is returned and the immutable
initial state is unchanged.

## Serialization and audit

Management schema v1 stores the exact rules, initial state, ordered actions, and final state.
The strict decoder rejects missing or unknown keys and replays the action ledger before
accepting the final state.

`audit_market` reports teams, rostered players, free agents, total and maximum team payroll,
signings, and waivers. `audit_contract_year` additionally reports expirations.

The frozen machine-readable defaults are in
[`governance/contracts-free-agency-v1.json`](../governance/contracts-free-agency-v1.json).

## Validation evidence

- focused contract, ownership, cap, expiry, waiver, signing, atomicity, JSON, and audit tests;
- deterministic duplicate year-advancement checks;
- full Ruff, strict mypy, pytest, coverage, Ubuntu CI, and Windows CI gates.
