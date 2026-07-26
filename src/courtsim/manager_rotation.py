"""White-box manager rotation and playing-time plans."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import cast

from courtsim.career import CareerPlayer, CareerStatus
from courtsim.domain.game import GameClockConfig
from courtsim.domain.plans import Lineup
from courtsim.domain.player import AbilityRatings, SizeClass
from courtsim.manager_ai import (
    DecisionContribution,
    ManagerCandidate,
    ManagerDecisionTrace,
    ManagerProfile,
    evaluate_manager_decision,
)
from courtsim.manager_learning import OpponentRotationAdjustment
from courtsim.rotations import RotationPlan, RotationStint

MANAGER_ROTATION_VERSION = "manager-rotation-v1"

_OFFENSE = {
    "perimeter_creation",
    "post_creation",
    "ball_security",
    "playmaking",
    "off_ball_movement",
    "rim_finishing",
    "midrange_shooting",
    "three_point_shooting",
    "offensive_decision",
}
_DEFENSE = {
    "point_of_attack_defense",
    "post_defense",
    "rim_protection",
    "steal_skill",
    "foul_discipline",
    "defensive_awareness",
}
_SUPPORT = {
    "screen_setting",
    "foul_drawing",
    "offensive_rebounding",
    "defensive_rebounding",
    "free_throw_shooting",
}


@dataclass(frozen=True, slots=True)
class ManagerRotationRules:
    maximum_rotation_players: int = 10
    segments_per_period: int = 4
    version: str = MANAGER_ROTATION_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.maximum_rotation_players, int)
            or isinstance(self.maximum_rotation_players, bool)
            or not 5 <= self.maximum_rotation_players <= 15
        ):
            raise ValueError("maximum_rotation_players must be from five through fifteen")
        if (
            not isinstance(self.segments_per_period, int)
            or isinstance(self.segments_per_period, bool)
            or not 1 <= self.segments_per_period <= 8
        ):
            raise ValueError("segments_per_period must be from one through eight")
        if self.version != MANAGER_ROTATION_VERSION:
            raise ValueError("unsupported manager rotation version")


@dataclass(frozen=True, slots=True)
class ManagerRotationResult:
    team_id: str
    lineup: Lineup
    rotation_order: tuple[int, ...]
    substitution_order: tuple[int, ...]
    plan: RotationPlan
    decisions: tuple[ManagerDecisionTrace, ...]
    target_seconds: tuple[tuple[int, int], ...]
    version: str = MANAGER_ROTATION_VERSION

    def __post_init__(self) -> None:
        if not self.team_id.strip():
            raise ValueError("manager rotation team_id must not be blank")
        if self.version != MANAGER_ROTATION_VERSION:
            raise ValueError("unsupported manager rotation result version")
        if self.rotation_order[:5] != self.lineup:
            raise ValueError("manager rotation lineup must lead rotation_order")
        if len(self.rotation_order) < 5 or len(self.rotation_order) != len(
            set(self.rotation_order)
        ):
            raise ValueError("manager rotation order must contain at least five unique players")
        if set(self.rotation_order) - set(self.substitution_order):
            raise ValueError("manager substitution order must cover rotation players")
        if tuple(player_id for player_id, _ in self.target_seconds) != tuple(
            sorted(self.substitution_order)
        ):
            raise ValueError("manager target seconds must cover substitution order")


def generate_manager_rotation(
    *,
    team_id: str,
    roster: tuple[CareerPlayer, ...],
    profile: ManagerProfile,
    game_config: GameClockConfig,
    rules: ManagerRotationRules | None = None,
    opponent_adjustment: OpponentRotationAdjustment | None = None,
) -> ManagerRotationResult:
    """Select a rotation and emit clock-addressed stints without mutating the roster."""
    active_rules = rules or ManagerRotationRules()
    if profile.team_id != team_id:
        raise ValueError("manager profile team does not match rotation team")
    if len(roster) < 5:
        raise ValueError("manager rotation requires at least five players")
    player_ids = tuple(player.player_id for player in roster)
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("manager rotation roster player ids must be unique")
    if any(player.status is not CareerStatus.ACTIVE for player in roster):
        raise ValueError("manager rotation roster can contain only active players")

    remaining = {player.player_id: player for player in roster}
    selected: list[CareerPlayer] = []
    decisions: list[ManagerDecisionTrace] = []
    rotation_size = min(len(roster), active_rules.maximum_rotation_players)
    for slot in range(rotation_size):
        candidates = tuple(
            _rotation_candidate(player, selected, profile, opponent_adjustment)
            for player in sorted(remaining.values(), key=lambda item: item.player_id)
        )
        trace = evaluate_manager_decision(
            decision_id=f"rotation:{team_id}:slot:{slot + 1}",
            candidates=candidates,
            reasonable_band=0.08,
            style_contribution_limit=0.04,
        )
        if trace.selected is None:
            raise ValueError("manager rotation has no eligible player")
        player_id = _candidate_player_id(trace.selected)
        selected.append(remaining.pop(player_id))
        decisions.append(trace)

    rotation_order = tuple(player.player_id for player in selected)
    excluded = tuple(
        player.player_id for player in roster if player.player_id not in set(rotation_order)
    )
    substitution_order = (*rotation_order, *excluded)
    lineup = cast(Lineup, rotation_order[:5])
    plan, target_seconds = _rotation_plan(
        lineup,
        rotation_order[5:],
        substitution_order,
        game_config,
        active_rules,
    )
    return ManagerRotationResult(
        team_id,
        lineup,
        rotation_order,
        substitution_order,
        plan,
        tuple(decisions),
        target_seconds,
    )


def _rotation_candidate(
    player: CareerPlayer,
    selected: list[CareerPlayer],
    profile: ManagerProfile,
    opponent_adjustment: OpponentRotationAdjustment | None,
) -> ManagerCandidate:
    abilities = player.profile.abilities
    offense = _group_mean(abilities, _OFFENSE) / 100
    defense = _group_mean(abilities, _DEFENSE) / 100
    support = _group_mean(abilities, _SUPPORT) / 100
    health = (100 - player.injury_burden) / 100
    fit = _size_fit(player.profile.size_class, selected)
    current = _group_mean(abilities, set(_ability_names())) / 100
    ceiling = _group_mean(player.potential, set(_ability_names())) / 100
    upside = max(0.0, ceiling - current)
    opponent = opponent_adjustment
    perimeter_defense = (abilities.point_of_attack_defense + abilities.steal_skill) / 200
    interior_defense = (
        abilities.post_defense + abilities.rim_protection + abilities.defensive_rebounding
    ) / 300
    rational = (
        _contribution("offense", offense * 0.34, "current offensive contribution"),
        _contribution("defense", defense * 0.30, "current defensive contribution"),
        _contribution("support", support * 0.14, "screening, rebounding and foul value"),
        _contribution("health", health * 0.12, "availability and injury burden"),
        _contribution("size-fit", fit * 0.10, "rotation size-class balance"),
        _contribution(
            "opponent-offense",
            (
                offense * opponent.offense_emphasis_bps / 10_000 * 0.12
                if opponent is not None
                else 0.0
            ),
            "offense emphasis learned from opponent defense",
            source="opponent-model",
        ),
        _contribution(
            "opponent-defense",
            (
                defense * opponent.defense_emphasis_bps / 10_000 * 0.12
                if opponent is not None
                else 0.0
            ),
            "defense emphasis learned from opponent offense",
            source="opponent-model",
        ),
        _contribution(
            "opponent-shot-profile",
            (
                (
                    perimeter_defense * opponent.perimeter_defense_emphasis_bps
                    + interior_defense * opponent.interior_defense_emphasis_bps
                )
                / 10_000
                * 0.10
                if opponent is not None
                else 0.0
            ),
            "perimeter and interior defense matched to opponent shot profile",
            source="opponent-model",
        ),
    )
    style = (
        _contribution(
            "win-now",
            (profile.win_now - 50) / 50 * current * 0.025,
            "manager win-now preference",
            source="personality",
        ),
        _contribution(
            "development",
            (profile.development_bias - 50) / 50 * upside * 0.08,
            "manager development preference",
            source="personality",
        ),
        _contribution(
            "star",
            (profile.star_preference - 50) / 50 * max(0.0, current - 0.65) * 0.05,
            "manager star preference",
            source="personality",
        ),
        _contribution(
            "risk",
            (profile.risk_tolerance - 50) / 50 * upside * 0.04,
            "manager upside risk tolerance",
            source="risk",
        ),
    )
    return ManagerCandidate(f"player:{player.player_id}", (), rational, style)


def _rotation_plan(
    lineup: Lineup,
    bench: tuple[int, ...],
    substitution_order: tuple[int, ...],
    config: GameClockConfig,
    rules: ManagerRotationRules,
) -> tuple[RotationPlan, tuple[tuple[int, int], ...]]:
    segment_count = min(rules.segments_per_period, config.period_seconds)
    clocks = tuple(
        config.period_seconds - (config.period_seconds * segment // segment_count)
        for segment in range(segment_count)
    )
    seconds = {player_id: 0 for player_id in substitution_order}
    stints: list[RotationStint] = []
    for period in range(1, config.regulation_periods + 1):
        lineups: list[Lineup] = [lineup]
        for segment in range(1, segment_count):
            current_ids = list(lineup)
            replacement_count = min(2, len(bench))
            for replacement in range(replacement_count):
                bench_index = ((segment - 1) * 2 + replacement) % len(bench)
                current_ids[replacement] = bench[bench_index]
            lineups.append(cast(Lineup, tuple(current_ids)))
        for index, (clock, stint_lineup) in enumerate(zip(clocks, lineups, strict=True)):
            stints.append(RotationStint(period, clock, stint_lineup))
            end_clock = clocks[index + 1] if index + 1 < len(clocks) else 0
            duration = clock - end_clock
            for player_id in stint_lineup:
                seconds[player_id] += duration
    return RotationPlan(tuple(stints)), tuple(sorted(seconds.items()))


def _size_fit(size: SizeClass, selected: list[CareerPlayer]) -> float:
    if not selected:
        return 1.0
    count = sum(player.profile.size_class is size for player in selected)
    return max(0.0, 1 - count / max(1, len(selected)))


def _group_mean(value: AbilityRatings, names: set[str]) -> float:
    ratings = tuple(
        cast(int, getattr(value, item.name))
        for item in fields(AbilityRatings)
        if item.name in names
    )
    return sum(ratings) / len(ratings)


def _ability_names() -> tuple[str, ...]:
    return tuple(item.name for item in fields(AbilityRatings))


def _contribution(
    contribution_id: str,
    value: float,
    reason: str,
    *,
    source: str = "competence",
) -> DecisionContribution:
    return DecisionContribution(
        contribution_id,
        "rotation",
        source,
        round(value, 6),
        reason,
    )


def _candidate_player_id(candidate_id: str) -> int:
    prefix, separator, value = candidate_id.partition(":")
    if prefix != "player" or separator != ":":
        raise ValueError("rotation candidate is not a player")
    return int(value)
