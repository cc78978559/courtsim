"""Strict schema-v1 JSON for immutable player profiles."""

import json
from dataclasses import fields
from typing import Any, NoReturn, cast

from courtsim.domain.player import (
    AbilityRatings,
    PlayerProfile,
    PlayRoleMix,
    ShotZoneMix,
    SizeClass,
    TendencyRatings,
)


class PlayerSerializationError(ValueError):
    pass


def _fail(message: str) -> NoReturn:
    raise PlayerSerializationError(message)


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _exact(obj: dict[str, Any], keys: set[str], field: str) -> None:
    if set(obj) != keys:
        _fail(f"{field} keys must be exactly {sorted(keys)}")


def _integer(obj: dict[str, Any], key: str) -> int:
    value = obj[key]
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(f"{key} must be an integer")
    return value


def _rating_kwargs(value: object, model: type[Any], field: str) -> dict[str, int]:
    obj = _object(value, field)
    names = {item.name for item in fields(model)}
    _exact(obj, names, field)
    return {name: _integer(obj, name) for name in names}


def player_profile_to_dict(profile: PlayerProfile) -> dict[str, object]:
    abilities = {
        field.name: getattr(profile.abilities, field.name) for field in fields(AbilityRatings)
    }
    play_role_mix = {
        field.name: getattr(profile.tendencies.play_role_mix, field.name)
        for field in fields(PlayRoleMix)
    }
    shot_zone_mix = {
        field.name: getattr(profile.tendencies.shot_zone_mix, field.name)
        for field in fields(ShotZoneMix)
    }
    tendencies: dict[str, object] = {
        "offensive_involvement": profile.tendencies.offensive_involvement,
        "play_role_mix": play_role_mix,
        "shoot_vs_pass": profile.tendencies.shoot_vs_pass,
        "shot_zone_mix": shot_zone_mix,
        "pass_risk": profile.tendencies.pass_risk,
        "contact_seek": profile.tendencies.contact_seek,
        "offensive_rebound_commitment": (profile.tendencies.offensive_rebound_commitment),
        "defensive_rebound_commitment": (profile.tendencies.defensive_rebound_commitment),
        "steal_gamble": profile.tendencies.steal_gamble,
        "help_aggression": profile.tendencies.help_aggression,
        "block_chase": profile.tendencies.block_chase,
    }
    return {
        "schema_version": profile.schema_version,
        "player_id": profile.player_id,
        "name": profile.name,
        "size_class": int(profile.size_class),
        "abilities": abilities,
        "tendencies": tendencies,
        "nominal_role_tags": list(profile.nominal_role_tags),
    }


def player_profile_from_dict(value: object) -> PlayerProfile:
    obj = _object(value, "player profile")
    _exact(
        obj,
        {
            "schema_version",
            "player_id",
            "name",
            "size_class",
            "abilities",
            "tendencies",
            "nominal_role_tags",
        },
        "player profile",
    )
    if _integer(obj, "schema_version") != 1:
        _fail("unsupported schema_version")
    name = obj["name"]
    if not isinstance(name, str):
        _fail("name must be a string")
    try:
        size_class = SizeClass(_integer(obj, "size_class"))
    except ValueError as error:
        raise PlayerSerializationError("invalid size_class") from error
    abilities = AbilityRatings(**_rating_kwargs(obj["abilities"], AbilityRatings, "abilities"))
    tendency_obj = _object(obj["tendencies"], "tendencies")
    _exact(
        tendency_obj,
        {
            "offensive_involvement",
            "play_role_mix",
            "shoot_vs_pass",
            "shot_zone_mix",
            "pass_risk",
            "contact_seek",
            "offensive_rebound_commitment",
            "defensive_rebound_commitment",
            "steal_gamble",
            "help_aggression",
            "block_chase",
        },
        "tendencies",
    )
    tendencies = TendencyRatings(
        offensive_involvement=_integer(tendency_obj, "offensive_involvement"),
        play_role_mix=PlayRoleMix(
            **_rating_kwargs(tendency_obj["play_role_mix"], PlayRoleMix, "play_role_mix")
        ),
        shoot_vs_pass=_integer(tendency_obj, "shoot_vs_pass"),
        shot_zone_mix=ShotZoneMix(
            **_rating_kwargs(tendency_obj["shot_zone_mix"], ShotZoneMix, "shot_zone_mix")
        ),
        pass_risk=_integer(tendency_obj, "pass_risk"),
        contact_seek=_integer(tendency_obj, "contact_seek"),
        offensive_rebound_commitment=_integer(tendency_obj, "offensive_rebound_commitment"),
        defensive_rebound_commitment=_integer(tendency_obj, "defensive_rebound_commitment"),
        steal_gamble=_integer(tendency_obj, "steal_gamble"),
        help_aggression=_integer(tendency_obj, "help_aggression"),
        block_chase=_integer(tendency_obj, "block_chase"),
    )
    tags = obj["nominal_role_tags"]
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        _fail("nominal_role_tags must be a string list")
    try:
        return PlayerProfile(
            player_id=_integer(obj, "player_id"),
            name=name,
            size_class=size_class,
            abilities=abilities,
            tendencies=tendencies,
            nominal_role_tags=tuple(tags),
        )
    except ValueError as error:
        raise PlayerSerializationError(str(error)) from error


def player_profile_to_json(profile: PlayerProfile) -> str:
    return json.dumps(
        player_profile_to_dict(profile),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def player_profile_from_json(payload: str) -> PlayerProfile:
    try:
        value: object = json.loads(payload)
    except json.JSONDecodeError as error:
        raise PlayerSerializationError("invalid JSON") from error
    return player_profile_from_dict(value)


def player_lineup_from_dict(value: object) -> tuple[PlayerProfile, ...]:
    obj = _object(value, "player lineup")
    _exact(obj, {"schema_version", "lineup_id", "players"}, "player lineup")
    if _integer(obj, "schema_version") != 1:
        _fail("unsupported lineup schema_version")
    lineup_id = obj["lineup_id"]
    if not isinstance(lineup_id, str) or not lineup_id.strip():
        _fail("lineup_id must be a non-empty string")
    players = obj["players"]
    if not isinstance(players, list) or len(players) != 5:
        _fail("players must contain exactly five profiles")
    lineup = tuple(player_profile_from_dict(player) for player in players)
    if len({player.player_id for player in lineup}) != 5:
        _fail("lineup player ids must be unique")
    return lineup


def player_lineup_from_json(payload: str) -> tuple[PlayerProfile, ...]:
    try:
        value: object = json.loads(payload)
    except json.JSONDecodeError as error:
        raise PlayerSerializationError("invalid JSON") from error
    return player_lineup_from_dict(value)
