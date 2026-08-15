"""Build source-pinned real-player NBA rosters for formal quick simulation."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import cast

from courtsim.analysis.nba_player_calibration import classify_player_role
from courtsim.analysis.nba_player_targets import NBAPlayerTarget, NBAPlayerTargetSet
from courtsim.domain.plans import Lineup
from courtsim.domain.player import PlayerProfile, PlayRoleMix, ShotZoneMix
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.randomness import derive_seed
from courtsim.rotations import RotationPlan, RotationStint

NBA_REAL_ROSTER_VERSION = "nba-real-roster-v1"
_ZONE_BASELINE_RATING_OFFSETS = (12, -24, 12)

ESPN_TEAM_NAMES = {
    "1": "Atlanta Hawks",
    "2": "Boston Celtics",
    "3": "New Orleans Pelicans",
    "4": "Chicago Bulls",
    "5": "Cleveland Cavaliers",
    "6": "Dallas Mavericks",
    "7": "Denver Nuggets",
    "8": "Detroit Pistons",
    "9": "Golden State Warriors",
    "10": "Houston Rockets",
    "11": "Indiana Pacers",
    "12": "LA Clippers",
    "13": "Los Angeles Lakers",
    "14": "Miami Heat",
    "15": "Milwaukee Bucks",
    "16": "Minnesota Timberwolves",
    "17": "Brooklyn Nets",
    "18": "New York Knicks",
    "19": "Orlando Magic",
    "20": "Philadelphia 76ers",
    "21": "Phoenix Suns",
    "22": "Portland Trail Blazers",
    "23": "Sacramento Kings",
    "24": "San Antonio Spurs",
    "25": "Oklahoma City Thunder",
    "26": "Utah Jazz",
    "27": "Washington Wizards",
    "28": "Toronto Raptors",
    "29": "Memphis Grizzlies",
    "30": "Charlotte Hornets",
}


class NbaRealRosterError(ValueError):
    pass


def build_nba_real_roster_teams(
    targets: NBAPlayerTargetSet,
    templates: tuple[PlayerProfile, ...],
    team_ids: tuple[str, ...],
) -> tuple[GameTeam, ...]:
    """Materialize real identities and target-shaped profiles without hidden name matching."""
    if len(templates) != 5 or len(team_ids) != 30 or len(set(team_ids)) != 30:
        raise NbaRealRosterError("real NBA rosters require five templates and thirty teams")
    if set(ESPN_TEAM_NAMES.values()) != set(team_ids):
        raise NbaRealRosterError("real NBA roster team crosswalk differs from alignment")
    players_by_team: dict[str, list[NBAPlayerTarget]] = {team_id: [] for team_id in team_ids}
    for target in targets.players:
        team_id = ESPN_TEAM_NAMES.get(target.team_id)
        if team_id is None:
            raise NbaRealRosterError("real NBA roster contains an unknown ESPN team id")
        players_by_team[team_id].append(target)
    teams = []
    for team_id in team_ids:
        target_players = sorted(
            players_by_team[team_id],
            key=lambda item: (-item.minutes_per_game, item.nba_player_id),
        )
        if len(target_players) < 10:
            raise NbaRealRosterError("real NBA roster requires ten eligible players per team")
        target_players = target_players[:15]
        team_usage = _weighted_mean(
            tuple(
                (item.usage_rate, item.games_played * item.minutes_per_game)
                for item in target_players
            )
        )
        team_zone_shares = cast(
            tuple[float, float, float],
            tuple(
                _weighted_mean(
                    tuple(
                        (item.shot_zone_shares[zone_index], item.field_goal_attempt_share)
                        for item in target_players
                    )
                )
                for zone_index in range(3)
            ),
        )
        profiles = tuple(
            _target_profile(
                target,
                templates[index % len(templates)],
                team_usage,
                team_zone_shares,
            )
            for index, target in enumerate(target_players)
        )
        rotation_profiles = profiles[:10]
        rotation_plan = _target_rotation_plan(target_players[:10])
        teams.append(
            GameTeam(
                team_id,
                cast(Lineup, tuple(item.player_id for item in rotation_profiles[:5])),
                cast(ProfileLineup, rotation_profiles[:5]),
                bench_profiles=profiles[5:],
                rotation_plan=rotation_plan,
                substitution_order=tuple(item.player_id for item in profiles),
            )
        )
    identities = tuple(player_id for team in teams for player_id in team.roster_order)
    if len(identities) != len(set(identities)):
        raise NbaRealRosterError("real NBA roster player ids must be league-unique")
    return tuple(teams)


def build_nba_real_game_team(
    team: GameTeam,
    targets: NBAPlayerTargetSet,
    *,
    game_id: int,
    master_seed: int,
) -> GameTeam:
    """Sample a deterministic target-shaped active rotation from all 15 roster positions."""
    target_by_id = {item.nba_player_id: item for item in targets.players}
    roster_targets = [target_by_id[player_id] for player_id in team.roster_order]
    league_appearance = sum(min(1.0, item.games_played / 82.0) for item in targets.players) / len(
        targets.players
    )
    league_minutes = sum(item.minutes_per_game for item in targets.players) / len(targets.players)
    minute_targets = {
        item.nba_player_id: _shrunk_value(
            item.minutes_per_game,
            league_minutes,
            item.games_played,
        )
        for item in roster_targets
    }
    ordered = sorted(
        roster_targets,
        key=lambda item: (-minute_targets[item.nba_player_id], item.nba_player_id),
    )
    active = [
        item
        for item in ordered
        if derive_seed(
            master_seed,
            NBA_REAL_ROSTER_VERSION,
            team.team_id,
            game_id,
            item.nba_player_id,
            "appearance",
        )
        % 10_000
        < round(
            10_000
            * _shrunk_value(
                min(1.0, item.games_played / 82.0),
                league_appearance,
                item.games_played,
            )
        )
    ]
    active_ids = {item.nba_player_id for item in active}
    for item in ordered:
        if len(active) >= 5:
            break
        if item.nba_player_id not in active_ids:
            active.append(item)
            active_ids.add(item.nba_player_id)
    active.sort(key=lambda item: (-minute_targets[item.nba_player_id], item.nba_player_id))
    profile_by_id = {item.player_id: item for item in team.roster_profiles}
    lineup_ids = cast(Lineup, tuple(item.nba_player_id for item in active[:5]))
    substitution_order = tuple(
        item.nba_player_id for item in (*active, *(item for item in ordered if item not in active))
    )
    return GameTeam(
        team.team_id,
        lineup_ids,
        cast(ProfileLineup, tuple(profile_by_id[player_id] for player_id in lineup_ids)),
        team.offense_strategy,
        team.defense_strategy,
        team.tempo_strategy,
        tuple(
            profile_by_id[player_id]
            for player_id in substitution_order
            if player_id not in lineup_ids
        ),
        substitution_order,
        _target_rotation_plan(active, minute_targets),
    )


def _target_profile(
    target: NBAPlayerTarget,
    template: PlayerProfile,
    team_usage: float,
    team_zone_shares: tuple[float, float, float],
) -> PlayerProfile:
    rim_pct, mid_pct, three_pct = target.shot_zone_percentages
    abilities = replace(
        template.abilities,
        rim_finishing=_percentage_rating(rim_pct, -30),
        midrange_shooting=_percentage_rating(mid_pct, -5),
        three_point_shooting=_percentage_rating(three_pct, 10),
    )
    tendencies = replace(
        template.tendencies,
        offensive_involvement=_relative_usage_rating(target.usage_rate, team_usage),
        play_role_mix=PlayRoleMix(50, 50, 50, 50, 50),
        shoot_vs_pass=50,
        shot_zone_mix=ShotZoneMix(
            *_relative_zone_ratings(target.shot_zone_shares, team_zone_shares)
        ),
    )
    return replace(
        template,
        player_id=target.nba_player_id,
        name=target.player_name,
        abilities=abilities,
        tendencies=tendencies,
        nominal_role_tags=(classify_player_role(target).upper().replace("-", "_"),),
    )


def _target_rotation_plan(
    targets: list[NBAPlayerTarget],
    minute_targets: dict[int, float] | None = None,
) -> RotationPlan:
    if not 5 <= len(targets) <= 15:
        raise NbaRealRosterError("real NBA rotation requires five through fifteen player targets")
    raw = [
        (
            minute_targets[item.nba_player_id]
            if minute_targets is not None
            else item.minutes_per_game
        )
        / 3
        for item in targets
    ]
    scale = 80 / sum(raw)
    counts = [max(1, min(16, round(value * scale))) for value in raw]
    while sum(counts) != 80:
        direction = 1 if sum(counts) < 80 else -1
        candidates = [
            index
            for index, count in enumerate(counts)
            if (direction > 0 and count < 16) or (direction < 0 and count > 1)
        ]
        index = max(
            candidates,
            key=lambda item: direction * (raw[item] * scale - counts[item]),
        )
        counts[index] += direction
    remaining = dict(zip((item.nba_player_id for item in targets), counts, strict=True))
    stints = []
    addresses = ((period, clock) for period in range(1, 5) for clock in (720, 540, 360, 180))
    for stint_index, (period, clock) in enumerate(addresses):
        slots_left = 16 - stint_index
        mandatory = [player_id for player_id, count in remaining.items() if count == slots_left]
        optional = sorted(
            (player_id for player_id in remaining if player_id not in mandatory),
            key=lambda player_id: (-remaining[player_id], player_id),
        )
        selected = (*mandatory, *optional[: 5 - len(mandatory)])
        if len(selected) != 5:
            raise NbaRealRosterError("real NBA rotation apportionment is infeasible")
        lineup = cast(Lineup, tuple(selected))
        stints.append(RotationStint(period, clock, lineup))
        for player_id in selected:
            remaining[player_id] -= 1
    if any(remaining.values()):
        raise NbaRealRosterError("real NBA rotation minutes do not balance")
    return RotationPlan(tuple(stints))


def _shrunk_value(value: float, league_mean: float, sample_games: int) -> float:
    reliability = sample_games / (sample_games + 20.0)
    return reliability * value + (1.0 - reliability) * league_mean


def _percentage_rating(value: float, offset: float = 0.0) -> int:
    return _rating(40 + (value - 0.25) * 160 + offset)


def _relative_usage_rating(value: float, baseline: float) -> int:
    return _rating(50 + 18 * math.log(max(value, 0.01) / max(baseline, 0.01)) / 0.35)


def _relative_zone_ratings(
    shares: tuple[float, float, float],
    baselines: tuple[float, float, float],
) -> tuple[int, int, int]:
    contrasts = tuple(
        math.log(max(share, 0.005) / max(baseline, 0.005))
        for share, baseline in zip(shares, baselines, strict=True)
    )
    mean = math.fsum(contrasts) / len(contrasts)
    return cast(
        tuple[int, int, int],
        tuple(
            _rating(50 + 15 * (contrast - mean) / 0.75 + offset)
            for contrast, offset in zip(contrasts, _ZONE_BASELINE_RATING_OFFSETS, strict=True)
        ),
    )


def _weighted_mean(values: tuple[tuple[float, float], ...]) -> float:
    total = math.fsum(weight for _, weight in values)
    return math.fsum(value * weight for value, weight in values) / total


def _rating(value: float) -> int:
    return max(0, min(100, round(value)))
