"""Source-level evidence gates for thirty-team front-office policies."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from math import isfinite

NBA_MANAGER_EVIDENCE_VERSION = "manager-evidence-v2"
DEFAULT_SEASON_WEIGHTS = (0.10, 0.15, 0.20, 0.25, 0.30)


@dataclass(frozen=True, slots=True)
class NBAFrontOfficeOutcome:
    source_id: str
    master_seed: int
    season_year: int
    focal_team_id: str
    win_rate: float
    postseason_progress: float
    player_asset_value: float
    draft_asset_value: float
    cap_health: float
    roster_continuity: float
    negotiations_opened: int = 0
    negotiations_accepted: int = 0
    negotiation_rounds: int = 0
    stale_rejections: int = 0
    positive_gain_transactions: int = 0
    no_counteroffers: int = 0
    round_exhaustions: int = 0
    illegal_transactions: int = 0
    unplayable_rosters: int = 0
    macro_gate_passed: bool = True
    macro_metrics: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.focal_team_id.strip():
            raise ValueError("NBA manager outcome identity must not be blank")
        if (
            not isinstance(self.master_seed, int)
            or isinstance(self.master_seed, bool)
            or self.master_seed < 0
            or not isinstance(self.season_year, int)
            or isinstance(self.season_year, bool)
            or self.season_year < 1
        ):
            raise ValueError("NBA manager outcome seed and season are invalid")
        metrics = (
            self.win_rate,
            self.postseason_progress,
            self.player_asset_value,
            self.draft_asset_value,
            self.cap_health,
            self.roster_continuity,
        )
        if any(not isfinite(value) or not 0 <= value <= 1 for value in metrics):
            raise ValueError("NBA manager outcome metrics must be finite values from zero to one")
        counts = (
            self.negotiations_opened,
            self.negotiations_accepted,
            self.negotiation_rounds,
            self.stale_rejections,
            self.positive_gain_transactions,
            self.no_counteroffers,
            self.round_exhaustions,
            self.illegal_transactions,
            self.unplayable_rosters,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts
        ):
            raise ValueError("NBA manager outcome audit counts must be non-negative integers")
        if self.negotiations_accepted > self.negotiations_opened:
            raise ValueError("accepted negotiations cannot exceed opened negotiations")
        if not isinstance(self.macro_gate_passed, bool):
            raise ValueError("macro_gate_passed must be boolean")
        metric_names = tuple(name for name, _ in self.macro_metrics)
        if metric_names != tuple(sorted(set(metric_names))) or any(
            not name.strip() or not isfinite(value) for name, value in self.macro_metrics
        ):
            raise ValueError("NBA manager macro metrics must be finite and canonical")

    @property
    def address(self) -> tuple[str, int, int, str]:
        return (self.source_id, self.master_seed, self.season_year, self.focal_team_id)


@dataclass(frozen=True, slots=True)
class PairedNBAFrontOfficeOutcome:
    control: NBAFrontOfficeOutcome
    treatment: NBAFrontOfficeOutcome

    def __post_init__(self) -> None:
        if self.control.address != self.treatment.address:
            raise ValueError("NBA manager outcomes must use an exact paired address")


@dataclass(frozen=True, slots=True)
class NBAFrontOfficeEvaluationWeights:
    win_rate: float = 0.35
    postseason_progress: float = 0.15
    player_asset_value: float = 0.20
    draft_asset_value: float = 0.15
    cap_health: float = 0.10
    roster_continuity: float = 0.05

    def __post_init__(self) -> None:
        values = tuple(asdict(self).values())
        if any(not isfinite(value) or value < 0 for value in values) or not math.isclose(
            sum(values), 1.0, abs_tol=1e-9
        ):
            raise ValueError("NBA manager evidence weights must be non-negative and sum to one")


@dataclass(frozen=True, slots=True)
class NBAFrontOfficeEvidenceThresholds:
    minimum_independent_sources: int = 30
    minimum_seasons_per_source: int = 5
    minimum_mean_utility_delta: float = 0.005
    minimum_utility_ci_lower: float = -0.005
    minimum_win_rate_delta: float = -0.002
    minimum_postseason_delta: float = -0.010
    minimum_terminal_asset_delta: float = -0.010
    minimum_cap_health_delta: float = -0.010
    maximum_loss_rate: float = 0.45
    minimum_worst_source_delta: float = -0.040
    neutral_band: float = 0.001

    def __post_init__(self) -> None:
        if (
            not isinstance(self.minimum_independent_sources, int)
            or isinstance(self.minimum_independent_sources, bool)
            or self.minimum_independent_sources < 1
            or not isinstance(self.minimum_seasons_per_source, int)
            or isinstance(self.minimum_seasons_per_source, bool)
            or self.minimum_seasons_per_source < 1
        ):
            raise ValueError("NBA manager evidence sample thresholds must be positive integers")
        numeric = (
            self.minimum_mean_utility_delta,
            self.minimum_utility_ci_lower,
            self.minimum_win_rate_delta,
            self.minimum_postseason_delta,
            self.minimum_terminal_asset_delta,
            self.minimum_cap_health_delta,
            self.maximum_loss_rate,
            self.minimum_worst_source_delta,
            self.neutral_band,
        )
        if any(not isfinite(value) for value in numeric):
            raise ValueError("NBA manager evidence thresholds must be finite")
        if not 0 <= self.maximum_loss_rate <= 1 or self.neutral_band < 0:
            raise ValueError("NBA manager evidence rate thresholds are invalid")


@dataclass(frozen=True, slots=True)
class NBAFrontOfficeEvidenceMetrics:
    mean_utility_delta: float
    utility_ci_lower_95: float
    mean_win_rate_delta: float
    mean_postseason_delta: float
    mean_player_asset_delta: float
    mean_draft_asset_delta: float
    mean_cap_health_delta: float
    mean_continuity_delta: float
    mean_terminal_asset_delta: float
    loss_rate: float
    worst_source_delta: float
    control_negotiation_efficiency: float
    treatment_negotiation_efficiency: float
    control_mean_negotiation_rounds: float
    treatment_mean_negotiation_rounds: float
    control_positive_gain_transactions: int
    treatment_positive_gain_transactions: int
    control_no_counteroffers: int
    treatment_no_counteroffers: int
    control_round_exhaustions: int
    treatment_round_exhaustions: int
    control_stale_rejections: int
    treatment_stale_rejections: int


@dataclass(frozen=True, slots=True)
class NBAMacroGateComparison:
    arm: str
    metric: str
    observed: float
    minimum: float
    maximum: float
    passed: bool


@dataclass(frozen=True, slots=True)
class NBAFrontOfficeEvidenceResult:
    baseline_policy_id: str
    candidate_policy_id: str
    independent_sources: int
    seasons_per_source: tuple[tuple[str, int], ...]
    focal_teams: tuple[str, ...]
    better_sources: int
    neutral_sources: int
    worse_sources: int
    metrics: NBAFrontOfficeEvidenceMetrics
    macro_comparisons: tuple[NBAMacroGateComparison, ...]
    hard_rejections: tuple[str, ...]
    recommended: bool
    evidence_digest: str
    version: str = NBA_MANAGER_EVIDENCE_VERSION


def evaluate_nba_front_office_policy(
    *,
    baseline_policy_id: str,
    candidate_policy_id: str,
    observations: Sequence[PairedNBAFrontOfficeOutcome],
    weights: NBAFrontOfficeEvaluationWeights | None = None,
    thresholds: NBAFrontOfficeEvidenceThresholds | None = None,
    season_weights: tuple[float, ...] = DEFAULT_SEASON_WEIGHTS,
    macro_ranges: tuple[tuple[str, float, float], ...] = (),
) -> NBAFrontOfficeEvidenceResult:
    """Evaluate focal-team deltas after aggregating each independent source."""
    if not baseline_policy_id.strip() or not candidate_policy_id.strip():
        raise ValueError("NBA manager policy identifiers must not be blank")
    active_weights = weights or NBAFrontOfficeEvaluationWeights()
    active_thresholds = thresholds or NBAFrontOfficeEvidenceThresholds()
    if (
        len(season_weights) != active_thresholds.minimum_seasons_per_source
        or any(not isfinite(value) or value <= 0 for value in season_weights)
        or not math.isclose(sum(season_weights), 1.0, abs_tol=1e-9)
    ):
        raise ValueError("NBA manager season weights must be positive and sum to one")
    macro_names = tuple(name for name, _, _ in macro_ranges)
    if macro_names != tuple(sorted(set(macro_names))) or any(
        not name.strip() or not isfinite(minimum) or not isfinite(maximum) or minimum > maximum
        for name, minimum, maximum in macro_ranges
    ):
        raise ValueError("NBA manager macro ranges must be finite and canonical")
    ordered = tuple(sorted(observations, key=lambda item: item.control.address))
    addresses = tuple(item.control.address for item in ordered)
    if len(addresses) != len(set(addresses)):
        raise ValueError("NBA manager evidence contains duplicate paired addresses")

    by_source: dict[str, list[PairedNBAFrontOfficeOutcome]] = defaultdict(list)
    source_seeds: dict[str, set[int]] = defaultdict(set)
    source_teams: dict[str, set[str]] = defaultdict(set)
    for observation in ordered:
        source = observation.control.source_id
        by_source[source].append(observation)
        source_seeds[source].add(observation.control.master_seed)
        source_teams[source].add(observation.control.focal_team_id)
    if any(len(values) != 1 for values in source_seeds.values()):
        raise ValueError("each NBA manager source must use one master seed")
    seeds = tuple(next(iter(source_seeds[source])) for source in sorted(source_seeds))
    if len(seeds) != len(set(seeds)):
        raise ValueError("NBA manager sources must use distinct master seeds")
    if any(len(values) != 1 for values in source_teams.values()):
        raise ValueError("each NBA manager source must retain one focal team")

    source_utility: list[float] = []
    metric_deltas: dict[str, list[float]] = defaultdict(list)
    terminal_assets: list[float] = []
    safety_failures = 0
    control_opened = control_accepted = control_rounds = 0
    treatment_opened = treatment_accepted = treatment_rounds = 0
    negotiation_audit = {
        "control_positive": 0,
        "treatment_positive": 0,
        "control_no_counter": 0,
        "treatment_no_counter": 0,
        "control_exhausted": 0,
        "treatment_exhausted": 0,
        "control_stale": 0,
        "treatment_stale": 0,
    }
    for source in sorted(by_source):
        seasons = sorted(by_source[source], key=lambda item: item.control.season_year)
        if len(seasons) != len(season_weights):
            continue
        years = tuple(item.control.season_year for item in seasons)
        if years != tuple(range(years[0], years[0] + len(years))):
            raise ValueError("NBA manager source seasons must be contiguous")
        deltas = {
            name: tuple(
                getattr(item.treatment, name) - getattr(item.control, name) for item in seasons
            )
            for name in (
                "win_rate",
                "postseason_progress",
                "player_asset_value",
                "draft_asset_value",
                "cap_health",
                "roster_continuity",
            )
        }
        weighted = {
            name: sum(weight * value for weight, value in zip(season_weights, values, strict=True))
            for name, values in deltas.items()
        }
        utility = sum(getattr(active_weights, name) * value for name, value in weighted.items())
        source_utility.append(utility)
        for name, value in weighted.items():
            metric_deltas[name].append(value)
        terminal_assets.append(
            (deltas["player_asset_value"][-1] + deltas["draft_asset_value"][-1]) / 2
        )
        for item in seasons:
            safety_failures += (
                item.control.illegal_transactions
                + item.control.unplayable_rosters
                + item.treatment.illegal_transactions
                + item.treatment.unplayable_rosters
                + int(not item.control.macro_gate_passed)
                + int(not item.treatment.macro_gate_passed)
            )
            control_opened += item.control.negotiations_opened
            control_accepted += item.control.negotiations_accepted
            control_rounds += item.control.negotiation_rounds
            treatment_opened += item.treatment.negotiations_opened
            treatment_accepted += item.treatment.negotiations_accepted
            treatment_rounds += item.treatment.negotiation_rounds
            negotiation_audit["control_positive"] += item.control.positive_gain_transactions
            negotiation_audit["treatment_positive"] += item.treatment.positive_gain_transactions
            negotiation_audit["control_no_counter"] += item.control.no_counteroffers
            negotiation_audit["treatment_no_counter"] += item.treatment.no_counteroffers
            negotiation_audit["control_exhausted"] += item.control.round_exhaustions
            negotiation_audit["treatment_exhausted"] += item.treatment.round_exhaustions
            negotiation_audit["control_stale"] += item.control.stale_rejections
            negotiation_audit["treatment_stale"] += item.treatment.stale_rejections

    mean_utility = _mean(source_utility)
    worse = sum(value < -active_thresholds.neutral_band for value in source_utility)
    better = sum(value > active_thresholds.neutral_band for value in source_utility)
    neutral = len(source_utility) - better - worse
    metrics = NBAFrontOfficeEvidenceMetrics(
        _rounded(mean_utility),
        _rounded(_ci_lower_95(source_utility)),
        _rounded(_mean(metric_deltas["win_rate"])),
        _rounded(_mean(metric_deltas["postseason_progress"])),
        _rounded(_mean(metric_deltas["player_asset_value"])),
        _rounded(_mean(metric_deltas["draft_asset_value"])),
        _rounded(_mean(metric_deltas["cap_health"])),
        _rounded(_mean(metric_deltas["roster_continuity"])),
        _rounded(_mean(terminal_assets)),
        _rounded(worse / len(source_utility) if source_utility else 1.0),
        _rounded(min(source_utility, default=float("-inf"))),
        _rounded(control_accepted / control_opened if control_opened else 0.0),
        _rounded(treatment_accepted / treatment_opened if treatment_opened else 0.0),
        _rounded(control_rounds / control_opened if control_opened else 0.0),
        _rounded(treatment_rounds / treatment_opened if treatment_opened else 0.0),
        negotiation_audit["control_positive"],
        negotiation_audit["treatment_positive"],
        negotiation_audit["control_no_counter"],
        negotiation_audit["treatment_no_counter"],
        negotiation_audit["control_exhausted"],
        negotiation_audit["treatment_exhausted"],
        negotiation_audit["control_stale"],
        negotiation_audit["treatment_stale"],
    )
    macro_comparisons = _macro_comparisons(ordered, macro_ranges)
    rejected: list[str] = []
    seasons_per_source = tuple((source, len(by_source[source])) for source in sorted(by_source))
    if len(by_source) < active_thresholds.minimum_independent_sources:
        rejected.append("insufficient-independent-sources")
    if any(count < active_thresholds.minimum_seasons_per_source for _, count in seasons_per_source):
        rejected.append("insufficient-seasons-per-source")
    if len(set(next(iter(source_teams[source])) for source in source_teams)) != len(by_source):
        rejected.append("focal-team-coverage-is-not-unique")
    checks = (
        (
            metrics.mean_utility_delta,
            active_thresholds.minimum_mean_utility_delta,
            "insufficient-utility-improvement",
        ),
        (
            metrics.utility_ci_lower_95,
            active_thresholds.minimum_utility_ci_lower,
            "utility-confidence-regression",
        ),
        (
            metrics.mean_win_rate_delta,
            active_thresholds.minimum_win_rate_delta,
            "win-rate-regression",
        ),
        (
            metrics.mean_postseason_delta,
            active_thresholds.minimum_postseason_delta,
            "postseason-regression",
        ),
        (
            metrics.mean_terminal_asset_delta,
            active_thresholds.minimum_terminal_asset_delta,
            "terminal-asset-regression",
        ),
        (
            metrics.mean_cap_health_delta,
            active_thresholds.minimum_cap_health_delta,
            "cap-health-regression",
        ),
        (-metrics.loss_rate, -active_thresholds.maximum_loss_rate, "excessive-source-loss-rate"),
        (
            metrics.worst_source_delta,
            active_thresholds.minimum_worst_source_delta,
            "unsafe-source-regression",
        ),
    )
    rejected.extend(reason for observed, minimum, reason in checks if observed < minimum)
    if safety_failures:
        rejected.append("manager-safety-invariant-failed")
    if any(not item.passed for item in macro_comparisons):
        rejected.append("manager-macro-reality-gate-failed")

    digest_payload = {
        "baseline_policy_id": baseline_policy_id,
        "candidate_policy_id": candidate_policy_id,
        "weights": asdict(active_weights),
        "thresholds": asdict(active_thresholds),
        "season_weights": season_weights,
        "macro_ranges": macro_ranges,
        "observations": [
            {"control": asdict(item.control), "treatment": asdict(item.treatment)}
            for item in ordered
        ],
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return NBAFrontOfficeEvidenceResult(
        baseline_policy_id,
        candidate_policy_id,
        len(by_source),
        seasons_per_source,
        tuple(sorted(next(iter(source_teams[source])) for source in source_teams)),
        better,
        neutral,
        worse,
        metrics,
        macro_comparisons,
        tuple(rejected),
        not rejected,
        digest,
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else float("-inf")


def _macro_comparisons(
    observations: Sequence[PairedNBAFrontOfficeOutcome],
    ranges: tuple[tuple[str, float, float], ...],
) -> tuple[NBAMacroGateComparison, ...]:
    results: list[NBAMacroGateComparison] = []
    for arm in ("control", "treatment"):
        outcomes = tuple(getattr(item, arm) for item in observations)
        by_outcome = [dict(item.macro_metrics) for item in outcomes]
        for metric, minimum, maximum in ranges:
            values = [item[metric] for item in by_outcome if metric in item]
            observed = _mean(values)
            passed = len(values) == len(outcomes) and minimum <= observed <= maximum
            results.append(
                NBAMacroGateComparison(
                    arm,
                    metric,
                    _rounded(observed),
                    minimum,
                    maximum,
                    passed,
                )
            )
    return tuple(results)


def _ci_lower_95(values: Sequence[float]) -> float:
    if len(values) == 1:
        # A one-source development smoke has no estimable sampling variance.
        # Keep the artifact strict-JSON and deliberately fail the frozen gate.
        return values[0] - 1.0
    if not values:
        return -1.0
    mean = _mean(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    critical = 2.045 if len(values) == 30 else 1.96
    return mean - critical * math.sqrt(variance / len(values))


def _rounded(value: float) -> float:
    return round(value, 6) if isfinite(value) else value
