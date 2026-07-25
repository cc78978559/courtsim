"""Validated league rosters and deterministic player transfers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import cast

from courtsim.domain.player import PlayerProfile
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.rotations import RotationPlan, RotationStint

ROSTER_VERSION = "roster-v1"


@dataclass(frozen=True, slots=True)
class RosterRules:
    minimum_players: int = 5
    maximum_players: int = 15
    version: str = ROSTER_VERSION

    def __post_init__(self) -> None:
        if self.version != ROSTER_VERSION:
            raise ValueError(f"unsupported roster version: {self.version}")
        if (
            not isinstance(self.minimum_players, int)
            or isinstance(self.minimum_players, bool)
            or not isinstance(self.maximum_players, int)
            or isinstance(self.maximum_players, bool)
            or self.minimum_players < 5
            or self.maximum_players < self.minimum_players
        ):
            raise ValueError("roster size bounds must be integers with 5 <= minimum <= maximum")


@dataclass(frozen=True, slots=True)
class PlayerTransfer:
    transaction_id: int
    effective_day: int
    player_id: int
    from_team_id: str
    to_team_id: str

    def __post_init__(self) -> None:
        values = (self.transaction_id, self.effective_day, self.player_id)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("transfer identifiers and day must be integers")
        if self.transaction_id < 0 or self.player_id < 0 or self.effective_day < 1:
            raise ValueError("transfer identifiers must be non-negative and day positive")
        if not self.from_team_id.strip() or not self.to_team_id.strip():
            raise ValueError("transfer team ids must not be blank")
        if self.from_team_id == self.to_team_id:
            raise ValueError("transfer teams must be distinct")


@dataclass(frozen=True, slots=True)
class TransferPlan:
    transfers: tuple[PlayerTransfer, ...]
    version: str = ROSTER_VERSION

    def __post_init__(self) -> None:
        if self.version != ROSTER_VERSION:
            raise ValueError(f"unsupported roster version: {self.version}")
        transaction_ids = tuple(item.transaction_id for item in self.transfers)
        if len(transaction_ids) != len(set(transaction_ids)):
            raise ValueError("transaction ids must be unique")
        if self.transfers != tuple(
            sorted(
                self.transfers,
                key=lambda item: (item.effective_day, item.transaction_id),
            )
        ):
            raise ValueError("transfers must be ordered by effective day and transaction id")


@dataclass(frozen=True, slots=True)
class RosterSnapshot:
    team_id: str
    player_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.team_id.strip():
            raise ValueError("roster team_id must not be blank")
        if any(
            not isinstance(player_id, int) or isinstance(player_id, bool) or player_id < 0
            for player_id in self.player_ids
        ) or len(self.player_ids) != len(set(self.player_ids)):
            raise ValueError("roster player ids must be unique non-negative integers")


def roster_snapshots(teams: Mapping[str, GameTeam]) -> tuple[RosterSnapshot, ...]:
    return tuple(RosterSnapshot(team_id, teams[team_id].roster_order) for team_id in sorted(teams))


def validate_league_rosters(
    teams: Mapping[str, GameTeam],
    rules: RosterRules,
) -> None:
    if set(teams) != {team.team_id for team in teams.values()}:
        raise ValueError("roster mapping keys must match team ids")
    player_ids = [player_id for team in teams.values() for player_id in team.roster_order]
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("every league player must have exactly one team owner")
    if any(
        not rules.minimum_players <= len(team.roster_order) <= rules.maximum_players
        for team in teams.values()
    ):
        raise ValueError("team roster size is outside the configured bounds")


def _filled_lineup(target: tuple[int, ...], roster_order: tuple[int, ...]) -> tuple[int, ...]:
    selected = [player_id for player_id in target if player_id in roster_order]
    selected.extend(player_id for player_id in roster_order if player_id not in selected)
    if len(selected) < 5:
        raise ValueError("a transaction cannot leave fewer than five players")
    return tuple(selected[:5])


def _without_player(team: GameTeam, player_id: int) -> tuple[GameTeam, PlayerProfile]:
    profiles = {profile.player_id: profile for profile in team.roster_profiles}
    if player_id not in profiles:
        raise ValueError("transfer source does not own player")
    roster_order = tuple(item for item in team.roster_order if item != player_id)
    lineup = cast(tuple[int, int, int, int, int], _filled_lineup(team.lineup, roster_order))
    rotation_plan = (
        RotationPlan(
            tuple(
                RotationStint(
                    stint.period,
                    stint.start_clock_seconds,
                    cast(
                        tuple[int, int, int, int, int],
                        _filled_lineup(stint.lineup, roster_order),
                    ),
                )
                for stint in team.rotation_plan.stints
            )
        )
        if team.rotation_plan is not None
        else None
    )
    active = cast(ProfileLineup, tuple(profiles[item] for item in lineup))
    bench = tuple(profiles[item] for item in roster_order if item not in lineup)
    updated = replace(
        team,
        lineup=lineup,
        profiles=active,
        bench_profiles=bench,
        substitution_order=roster_order,
        rotation_plan=rotation_plan,
    )
    return updated, profiles[player_id]


def apply_player_transfer(
    teams: Mapping[str, GameTeam],
    transfer: PlayerTransfer,
    rules: RosterRules,
) -> dict[str, GameTeam]:
    if transfer.from_team_id not in teams or transfer.to_team_id not in teams:
        raise ValueError("transfer references an unknown team")
    source = teams[transfer.from_team_id]
    destination = teams[transfer.to_team_id]
    if len(source.roster_order) - 1 < rules.minimum_players:
        raise ValueError("transfer would leave source below the roster minimum")
    if len(destination.roster_order) + 1 > rules.maximum_players:
        raise ValueError("transfer would put destination above the roster maximum")
    updated_source, profile = _without_player(source, transfer.player_id)
    if transfer.player_id in destination.roster_order:
        raise ValueError("transfer destination already owns player")
    updated_destination = replace(
        destination,
        bench_profiles=(*destination.bench_profiles, profile),
        substitution_order=(*destination.roster_order, transfer.player_id),
    )
    updated = dict(teams)
    updated[transfer.from_team_id] = updated_source
    updated[transfer.to_team_id] = updated_destination
    validate_league_rosters(updated, rules)
    return updated
