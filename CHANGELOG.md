# Changelog

## [0.26.0] - 2026-07-26

- Hide true prospect potential behind deterministic, team-specific field-level scouting reports.
- Reduce scouting uncertainty through repeated exposure and feed estimates into Shadow drafting.
- Add Non-Bird, Early Bird, and Full Bird signings with first- and second-apron enforcement.
- Add tiered salary matching plus atomic, expiring, partially consumable trade exceptions.
- Generate a deterministic 30-team, 1,230-game schedule with 82 games per team.
- Resolve both conference play-ins and a derived 16-team, 15-series playoff bracket.
- Persist opponent observations across seasons and compile them into white-box rotation changes.

## [0.22.0] - 2026-07-26

- Rank each hub team's bounded candidate lane by aggregate net player-salary imbalance.
- Preserve round-robin hub coverage while prioritizing packages more likely to salary-match.
- Record salary imbalance on every three-team evaluation and in league adapter audits.
- Use lower salary imbalance as the stable tie-breaker between equal-gain approved offers.
- Retain a governed switch for deterministic comparison with lexical candidate ordering.

## [0.21.0] - 2026-07-26

- Add hub-and-spoke three-team packages with two incoming and two outgoing hub players.
- Allocate separate bounded cyclic and hub candidate budgets with round-robin hub coverage.
- Escalate rejected proposals through traceable one-pick and two-pick counteroffer rounds.
- Preserve the 64-evaluation per-trio ceiling while mixing all candidate families.
- Expose negotiation rounds and parent-offer chains in league adapter audits.

## [0.20.0] - 2026-07-26

- Discover deterministic cyclic player routes across every three-team combination.
- Search bounded future-pick compensation when an initial cycle is rejected.
- Rank positive-surplus three-team offers and lock participants against conflicts.
- Compare bilateral and three-team plans on combined rational gain before execution.
- Integrate the winning market into the real preseason Shadow league adapter with replay audits.

## [0.19.0] - 2026-07-26

- Add native three-team offers with explicit player and pick routes.
- Validate all participant rosters, payrolls, salary matching, ownership, and Stepien safety.
- Move every routed player contract and draft asset in one atomic state transition.
- Reuse the white-box per-team evaluator and require unanimous three-manager approval.
- Add complete routed-offer replay audits without sequential bilateral intermediates.

## [0.18.0] - 2026-07-26

- Add a deterministic weighted first-round lottery with address-isolated draw records.
- Preserve reverse standings for undrawn teams and every later draft round.
- Enforce a future first-round Stepien consecutive-gap legality gate on trades.
- Generate bounded two-for-one player packages in both trade directions.
- Mix direct, multi-player, pick-counter, and player-for-pick candidates within fixed budgets.

## [0.17.0] - 2026-07-26

- Add persistent future-pick identities, ownership, years, rounds, and strict ledger JSON.
- Maintain a rolling three-draft asset horizon in multi-season league state.
- Resolve top-N protection, bounded obligation deferral, and one-way better-slot swaps.
- Convert settled future assets into canonical current draft picks using reverse standings.
- Allow preseason white-box trade markets to include persisted future picks.

## [0.16.0] - 2026-07-26

- Generate deterministic direct, pick-counter, and player-for-pick trade candidates.
- Rank independently approved offers by combined rational gain and stable identity.
- Lock teams, players, and picks to prevent conflicting simultaneous transactions.
- Suppress zero-surplus trade churn and replay every cleared offer through the canonical engine.
- Run the trade market in the Shadow arm of real multi-season league experiments.

## [0.15.0] - 2026-07-26

- Add atomic bilateral trades for players, contracts, and draft-pick ownership.
- Enforce asset ownership, roster bounds, salary caps, and configurable salary matching.
- Add replay-derived trade audits with no partial state transitions.
- Add independent white-box approval by both managers with a rational-gain floor.
- Reuse MythicMons market architecture while replacing all domain-specific valuation signals.

## [0.14.0] - 2026-07-26

- Add white-box starter and rotation-player selection with bounded manager personality.
- Add clock-addressed legal lineup segments, complete substitution order, and target seconds.
- Preserve non-rotation roster players as emergency substitutes.
- Apply manager rotations to regular-season and playoff teams in real league experiments.
- Feed official rookie and bench playing time back into career growth and retirement summaries.

## [0.13.0] - 2026-07-26

- Add deterministic annual prospect classes with reserved stable player identities.
- Generate field-level current abilities, potential ceilings, archetypes, ages, size classes,
  and development traits from isolated semantic random addresses.
- Preserve preloaded complete classes, reject ambiguous partial classes, and detect ID collisions.
- Inject identical annual classes into incumbent/Shadow league experiments and retain their
  complete audit payload.

## [0.12.0] - 2026-07-26

- Add a strict, deterministic league-state payload for manager experiments.
- Connect real regular seasons and sampled playoff brackets to the paired experiment runner.
- Derive career summaries and execute growth, retirement, contracts, draft, and free agency.
- Apply incumbent and white-box Shadow offseason policies with common random numbers.
- Emit complete season/playoff/offseason audit payloads and normalized manager outcomes.

## [0.11.0] - 2026-07-26

- Add resumable incumbent/Shadow manager experiment orchestration across independent sources.
- Carry isolated arm state through exact multi-season horizons from one shared initial state.
- Persist source/arm/season cells with request, state, and execution digests.
- Reuse only verified completed cells after interruption and reject conflicting plans.
- Recompute manager evidence from stored outcomes and bind plans, cells, reports, and manifests.

## [0.10.0] - 2026-07-26

- Add exact-address paired incumbent/Shadow manager outcomes across multiple seasons.
- Add source-isolated evidence gates for utility, win rate, loss frequency, and worst-source
  safety.
- Prevent sample-count-only promotion and repeated-seed pseudo-replication.
- Add evidence digests and a strict JSON manager policy release registry.
- Add evidence-required activation, explicit rejection, retirement, and safety rollback.

## [0.9.0] - 2026-07-26

- Add a generic white-box manager decision contract with hard rejections, rational scoring,
  a reasonable-choice band, and bounded personality contributions.
- Add validated manager profiles, deterministic candidate ordering, incumbent comparisons,
  and immutable decision ledgers.
- Add non-executing draft and free-agency Shadow policies that emit canonical `DraftPlan`
  and `MarketPlan` values for replay through the existing rule engines.
- Enforce roster and salary-cap legality before manager style can influence a choice.

## [0.8.0] - 2026-07-26

- Add immutable player career state with field-level potential and no global overall rating.
- Add player-addressed annual ability growth, age decline, injury burden, and retirement.
- Add explicit draft-pick ownership, ordered selections, roster insertion, and rookie contracts.
- Add a canonical offseason pipeline for retirement, expirations, draft, and free agency.
- Add strict offseason JSON, full replay audits, and frozen career/draft governance.

## [0.7.0] - 2026-07-26

- Add a deterministic four-team playoff bracket with 1/3/5/7-game series.
- Enforce canonical seed pairings, game addresses, and configurable home-court patterns.
- Derive series winners, advancement, finals, and champion from the game ledger.
- Add strict playoff JSON, bracket replay audits, and frozen playoff governance.

## [0.6.0] - 2026-07-25

- Add canonical multi-year player contracts with salary and term limits.
- Add team payroll and salary-cap validation tied to roster ownership.
- Add deterministic contract-year advancement and expiration into free agency.
- Add ordered, atomic waiver and free-agent signing plans.
- Add strict management JSON, payroll/action audits, and frozen contract governance.

## [0.5.0] - 2026-07-25

- Add league-wide unique player ownership and configurable roster-size contracts.
- Add deterministic effective-day player transfers with complete preflight validation.
- Preserve fatigue, injury, and return state when a player changes teams.
- Rebuild source lineups and rotations while adding acquired players to destination roster order.
- Add season schema v2 transfer ledgers and initial/final roster snapshots with v1 read support.

## [0.4.0] - 2026-07-25

- Add immutable, validated multi-team schedules with stable game identifiers.
- Carry bounded fatigue between games and apply deterministic off-day recovery.
- Add isolated deterministic injury rolls, availability, return dates, and injury-safe rotations.
- Derive canonical forfeits, standings, season audits, and strict season JSON artifacts.

## [0.3.0] - 2026-07-25

- Add full-roster identity and active-lineup contracts.
- Add deterministic clock-addressed rotation schedules and canonical substitution events.
- Derive player seconds from possession lineups and serialize the complete ledger with game schema
  v2 while retaining v1 decoding.
- Add versioned, bounded fatigue load, bench recovery, explicit ability feedback, and rotation
  audits.

## [0.2.0] - 2026-07-25

- Add opt-in deterministic overtime with explicit completion and safety-limit reasons.
- Add roster-order foul-out replacement and explicit no-legal-lineup termination.
- Add canonical offensive-foul and technical-foul events with schema-v5 compatibility.
- Add the versioned `nba-v1` period, overtime, and final-two-minute team-foul rules.

All notable user-visible changes are recorded here. CourtSim follows Semantic Versioning
for the Python engine; model structure and parameter versions are tracked separately.

## [0.1.0] - 2026-07-25

### Added

- Deterministic action, possession, regulation-game, batch, replay, and audit runtimes.
- Player-aware probability model through `demo-v1.12 / demo-1.4.0`.
- Event-sourced statistics, SHA-256 manifests, experiment matrices, realism targets,
  regression gates, and artifact-governance tooling.
- Linux and Windows CI with formatting, lint, strict typing, tests, and coverage.

### Fixed

- Preserved audited file hashes across Windows checkouts.
- Restored Python 3.11 compatibility for runtime generic constructions.
- Updated default model audit and benchmark commands to use the frozen model.
