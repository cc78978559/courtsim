# White-box manager rotation v1

Status: local release candidate, 2026-07-26.

## Purpose

`manager-rotation-v1` converts manager preferences and the current career roster into an
auditable starting lineup, rotation group, substitution order, clock-addressed `RotationPlan`,
and target playing-time ledger.

## Player selection

Each rotation slot is selected through the common white-box decision contract. Rational
contributions include:

- current offensive contribution;
- current defensive contribution;
- screening, rebounding and foul value;
- availability and injury burden;
- size-class balance with players already selected.

Candidates materially outside the reasonable band cannot be rescued by personality. Inside
the band, bounded win-now, development, star, and risk preferences may distinguish otherwise
defensible choices. Every slot retains all candidate contributions and the selected identity.

## Playing-time plan

The first five selected players form the starting lineup. Up to ten players enter the normal
rotation by default; remaining roster players stay in substitution order as zero-target
emergency replacements.

Each regulation period is divided into up to four clock-addressed segments. Bench players cycle
through two lineup positions while the plan preserves five legal players at every address.
Target seconds are derived from the exact segment ledger and sum to five player-seconds per
game-second. Actual minutes may differ because of injuries, foul-outs, forfeits, or runtime
replacement rules.

## League integration

`manager-league-adapter-v1` generates one plan per team before the regular season. The same plan
is retained for sampled playoff games in that season. Complete rotation decisions are embedded
in the manager experiment audit payload.

Drafted young players appended to the roster can enter the normal rotation immediately. Their
official `playing_time` then feeds `PlayerSeasonSummary`, allowing minutes, growth, injury
burden, decline and retirement to form a real multi-season feedback loop.

## Known limits

- Rotation decisions are season-level and do not adapt to individual opponents.
- No load management, hot-hand response, playoff-specific shortening, position labels, or
  explicit usage hierarchy is modeled.
- Bench lineups replace at most two starters per segment.
- The policy uses transparent ability groups rather than calibrated plus-minus or lineup
  synergy estimates.
