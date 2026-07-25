"""Stable, append-only identifiers for the phase-0 domain contract."""

from enum import IntEnum


class PlayFamily(IntEnum):
    BALL_SCREEN = 0
    ISOLATION = 1
    OFF_BALL_ACTION = 2


class Coverage(IntEnum):
    BASE = 0
    DROP = 1
    SWITCH = 2
    BLITZ = 3


class FinisherRoute(IntEnum):
    INITIATOR_SELF = 0
    SCREENER_ROLL = 1
    SCREENER_POP = 2
    HELP_RELEASE = 3
    DESIGNED_OFF_BALL_TARGET = 4
    INITIATOR_BAILOUT = 5


class CreationMode(IntEnum):
    SELF_CREATED = 0
    SCREEN_PARTNER_FEED = 1
    SPOT_UP_FEED = 2
    OFF_BALL_MOVEMENT_FEED = 3


class ShotZone(IntEnum):
    RIM = 0
    MIDRANGE = 1
    THREE = 2


class ContestLevel(IntEnum):
    NORMAL = 0
    HEAVY = 1


class TerminalChannel(IntEnum):
    SHOT_OPPORTUNITY = 0
    TURNOVER = 1


class ReboundSide(IntEnum):
    OFFENSE = 0
    DEFENSE = 1


class TurnoverKind(IntEnum):
    LOST_BALL_STEAL = 0
    LOST_BALL_UNFORCED = 1
    BAD_PASS_STEAL = 2
    BAD_PASS_UNFORCED = 3
    VIOLATION = 4


class PossessionEndReason(IntEnum):
    MADE_SHOT = 0
    TURNOVER = 1
    DEFENSIVE_REBOUND = 2
    SEGMENT_LIMIT = 3
    FREE_THROW_SEQUENCE = 4
    OFFENSIVE_FOUL = 5
    TECHNICAL_FREE_THROW = 6


class GameEndReason(IntEnum):
    REGULATION = 0
    POSSESSION_TRUNCATED = 1
    OVERTIME = 2
    OVERTIME_LIMIT = 3
    NO_LEGAL_LINEUP = 4


class FoulTeamSide(IntEnum):
    OFFENSE = 0
    DEFENSE = 1


class TechnicalFoulType(IntEnum):
    PLAYER = 0
    BENCH = 1
    DELAY_OF_GAME = 2


class SubstitutionReason(IntEnum):
    ROTATION = 0
    FOUL_OUT = 1


class LateGameOffenseMode(IntEnum):
    STANDARD = 0
    COMEBACK = 1
    PROTECT_LEAD = 2
    TWO_FOR_ONE = 3


class LateGameDefenseMode(IntEnum):
    STANDARD = 0
    INTENTIONAL_FOUL = 1
