import json
from dataclasses import replace

import pytest

from courtsim.analysis.quick_sim_batch import (
    QuickSimBatchError,
    QuickSimBatchResult,
    QuickSimBatchSpec,
    append_precomputed_quick_sim_summaries,
    quick_sim_batch_from_json,
    quick_sim_batch_to_json,
    run_quick_sim_batch,
)
from courtsim.analysis.quick_sim_comparison import (
    QuickSimComparisonError,
    QuickSimSeasonSummary,
    build_quick_sim_reference,
    compare_quick_sim_summaries,
)


def _executor(season_id: str, seed: int) -> QuickSimSeasonSummary:
    offset = seed % 3
    return QuickSimSeasonSummary(
        season_id,
        30,
        1_230,
        0.11 + offset * 0.01,
        98.0 + offset,
        111.0 + offset,
        4.0 + offset * 0.25,
        0.25 + offset * 0.05,
        1 + offset,
    )


def test_batch_resumes_to_the_same_hash_as_one_shot_execution() -> None:
    spec = QuickSimBatchSpec("nba-2k-study", 20260726, 5)
    partial = run_quick_sim_batch(spec, _executor, maximum_new_seasons=2)
    assert not partial.complete
    assert len(partial.cells) == 2
    restored = quick_sim_batch_from_json(quick_sim_batch_to_json(partial))
    assert restored == partial

    resumed = run_quick_sim_batch(spec, _executor, previous=restored)
    one_shot = run_quick_sim_batch(spec, _executor)
    assert resumed == one_shot
    assert resumed.complete
    assert len({cell.seed for cell in resumed.cells}) == 5


def test_precomputed_wave_has_the_same_canonical_batch_hash() -> None:
    spec = QuickSimBatchSpec("parallel-wave", 20260801, 4)
    expected = run_quick_sim_batch(spec, _executor)
    first = append_precomputed_quick_sim_summaries(
        spec, tuple(cell.summary for cell in expected.cells[:2])
    )
    result = append_precomputed_quick_sim_summaries(
        spec,
        tuple(cell.summary for cell in expected.cells[2:]),
        previous=first,
    )
    assert result == expected


def test_batch_rejects_tampered_checkpoint_and_mismatched_executor() -> None:
    spec = QuickSimBatchSpec("nba-2k-study", 7, 2)
    result = run_quick_sim_batch(spec, _executor, maximum_new_seasons=1)
    raw = json.loads(quick_sim_batch_to_json(result))
    raw["cells"][0]["summary"]["offensive_rating"] += 1
    with pytest.raises(ValueError, match="hash"):
        quick_sim_batch_from_json(json.dumps(raw))
    raw = json.loads(quick_sim_batch_to_json(result))
    raw["complete"] = 0
    with pytest.raises(QuickSimBatchError, match="boolean"):
        quick_sim_batch_from_json(json.dumps(raw))
    raw = json.loads(quick_sim_batch_to_json(result))
    raw["spec"]["seasons"] = "2"
    with pytest.raises(QuickSimBatchError, match="integer"):
        quick_sim_batch_from_json(json.dumps(raw))

    def wrong_team_count(season_id: str, seed: int) -> QuickSimSeasonSummary:
        summary = _executor(season_id, seed)
        return QuickSimSeasonSummary(
            summary.season_id,
            4,
            summary.games,
            summary.win_rate_stddev,
            summary.pace_possessions_per_team,
            summary.offensive_rating,
            summary.point_differential_stddev,
            summary.playoff_upset_rate,
            summary.champion_seed,
        )

    with pytest.raises(QuickSimBatchError, match="mismatched"):
        run_quick_sim_batch(spec, wrong_team_count)


def test_observed_seasons_build_a_versioned_scoring_reference() -> None:
    batch = run_quick_sim_batch(QuickSimBatchSpec("observed-2k", 99, 3), _executor)
    summaries = tuple(cell.summary for cell in batch.cells)
    reference = build_quick_sim_reference(
        summaries,
        reference_id="2k-2026-observed",
        source_label="controlled console exports",
        game_version="NBA 2K exact-build",
        roster_date="2026-07-26",
    )
    assert reference.source_status == "observed"
    assert reference.observed_seasons == 3
    assert compare_quick_sim_summaries(summaries, reference).passed


def test_batch_contract_rejects_invalid_specs_cells_and_results() -> None:
    with pytest.raises(ValueError, match="blank"):
        QuickSimBatchSpec(" ", 1, 1)
    for kwargs in (
        {"master_seed": True},
        {"seasons": 0},
        {"team_count": 1},
    ):
        with pytest.raises(ValueError, match="dimensions"):
            QuickSimBatchSpec(
                batch_id="batch",
                master_seed=kwargs.get("master_seed", 1),
                seasons=kwargs.get("seasons", 1),
                team_count=kwargs.get("team_count", 30),
            )
    with pytest.raises(ValueError, match="unsupported"):
        QuickSimBatchSpec("batch", 1, 1, version="future")

    result = run_quick_sim_batch(QuickSimBatchSpec("batch", 1, 1), _executor)
    cell = result.cells[0]
    with pytest.raises(ValueError, match="identity"):
        replace(cell, season_index=-1)
    with pytest.raises(ValueError, match="summary identity"):
        replace(cell, season_id="other")
    with pytest.raises(ValueError, match="summary hash"):
        replace(cell, summary_sha256="0" * 64)
    with pytest.raises(ValueError, match="contiguous"):
        replace(result, cells=(replace(cell, season_index=1),))
    with pytest.raises(ValueError, match="too many"):
        QuickSimBatchResult(
            result.spec,
            (cell, replace(cell, season_index=1)),
            False,
            result.batch_sha256,
        )
    other_team = run_quick_sim_batch(
        QuickSimBatchSpec("small", 1, 1, team_count=4),
        lambda season_id, seed: replace(_executor(season_id, seed), team_count=4),
    )
    with pytest.raises(ValueError, match="team count"):
        QuickSimBatchResult(result.spec, other_team.cells, True, result.batch_sha256)
    with pytest.raises(ValueError, match="completion"):
        replace(result, complete=False)
    with pytest.raises(ValueError, match="batch hash"):
        replace(result, batch_sha256="0" * 64)


def test_batch_run_and_json_boundaries_are_strict() -> None:
    spec = QuickSimBatchSpec("batch", 1, 1)
    result = run_quick_sim_batch(spec, _executor)
    for limit in (0, True):
        with pytest.raises(QuickSimBatchError, match="positive"):
            run_quick_sim_batch(spec, _executor, maximum_new_seasons=limit)
    with pytest.raises(QuickSimBatchError, match="spec differs"):
        run_quick_sim_batch(
            QuickSimBatchSpec("other", 1, 1),
            _executor,
            previous=result,
        )

    payload = json.loads(quick_sim_batch_to_json(result))
    invalid_payloads = [
        "{",
        json.dumps({"unknown": True}),
        json.dumps({**payload, "spec": []}),
        json.dumps({**payload, "cells": {}}),
        json.dumps({**payload, "cells": [None]}),
        json.dumps({**payload, "cells": [{**payload["cells"][0], "summary": []}]}),
    ]
    for invalid in invalid_payloads:
        with pytest.raises(QuickSimBatchError):
            quick_sim_batch_from_json(invalid)

    bad_summary = json.loads(quick_sim_batch_to_json(result))
    del bad_summary["cells"][0]["summary"]["games"]
    with pytest.raises(QuickSimBatchError, match="summary keys"):
        quick_sim_batch_from_json(json.dumps(bad_summary))
    bad_string = json.loads(quick_sim_batch_to_json(result))
    bad_string["spec"]["batch_id"] = 4
    with pytest.raises(QuickSimBatchError, match="string"):
        quick_sim_batch_from_json(json.dumps(bad_string))
    bad_number = json.loads(quick_sim_batch_to_json(result))
    bad_number["cells"][0]["summary"]["offensive_rating"] = "111"
    with pytest.raises(QuickSimBatchError, match="numeric"):
        quick_sim_batch_from_json(json.dumps(bad_number))


def test_observed_reference_builder_rejects_incomparable_seasons() -> None:
    with pytest.raises(QuickSimComparisonError, match="observed seasons"):
        build_quick_sim_reference(
            (),
            reference_id="empty",
            source_label="source",
            game_version="build",
            roster_date="2026-07-26",
        )
    first = _executor("one", 1)
    cases = (
        (first, replace(first, season_id="two", team_count=4)),
        (first, first),
        (replace(first, playoff_upset_rate=None, champion_seed=None),),
    )
    messages = ("one team count", "unique", "postseason")
    for summaries, message in zip(cases, messages, strict=True):
        with pytest.raises(QuickSimComparisonError, match=message):
            build_quick_sim_reference(
                summaries,
                reference_id="invalid",
                source_label="source",
                game_version="build",
                roster_date="2026-07-26",
            )
