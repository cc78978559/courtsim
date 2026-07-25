# Complete game rules v1

Status: implemented as the opt-in `nba-v1` rule boundary.

The probability model remains frozen at `demo-v1.12 / demo-1.4.0`. Game rules are a separate,
versioned layer so rule changes do not silently alter a promoted model baseline.

## Overtime

`GameClockConfig.overtime_enabled` activates deterministic overtime. A tied final regulation
period starts an overtime period using `overtime_seconds`; random addresses continue from the next
possession index. Team and final-two-minute foul counts reset at every overtime boundary.

The ledger ends with `OVERTIME` when a winner exists. `max_overtimes` is an explicit safety bound;
a still-tied game ends as `OVERTIME_LIMIT`, never masquerading as a completed win.

## Player eligibility

`GameRules.player_foul_limit` defaults to six. Teams may provide `bench_profiles` in deterministic
roster order. After each completed possession, an ineligible active player is replaced by the first
legal bench player. The active five and their profiles are rematerialized together. If a team
cannot field five legal players, the ledger ends explicitly as `NO_LEGAL_LINEUP`.

## Offensive fouls

`OffensiveFoulSegmentResult` records the responsible offender and fouled defender. It ends the
possession with `OFFENSIVE_FOUL`, attributes one personal foul and one turnover to the offender, and
remains distinct from ordinary turnover events in serialization and audits.

## Team-foul penalty

`nba-v1` uses a fifth-period-foul regulation penalty, a fourth-period-foul overtime penalty, and a
second foul in the final two minutes. The period and final-two-minute counters are independent and
reset at period boundaries. Ordinary and intentional non-shooting fouls enter the same canonical
free-throw and retained-ball continuation.

## Technical fouls

`TechnicalFoulSegmentResult` records the technical type, responsible side and optional player,
free-throw shooter, one free-throw outcome, and whether the offense retains possession. Technical
free throws create only `FTA`, `FTM`, `PTS`, and `TF` facts: no field-goal or rebound facts are
inferred. A technical against the offense can credit the opposing score without changing the
offense-oriented event ledger.

## Compatibility

Segment serialization schema v5 adds offensive and technical fouls while accepting v1-v4 events.
All new enum values are append-only. Regulation-only callers retain their previous behavior unless
they enable overtime or pass `GameRules`.
