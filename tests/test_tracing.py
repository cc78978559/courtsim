from pathlib import Path

import pytest

from courtsim.tracing import DecisionTrace, TraceError, TraceOption, write_traces


def _valid_trace() -> DecisionTrace:
    return DecisionTrace(
        sequence=1,
        possession=0,
        action=1,
        phase="offense",
        actor="home-1",
        selected="pass",
        rng_stream="possession/0/action/1/offense",
        options=(
            TraceOption("pass", 3.0, 0.75, {"tendency": 1.5}),
            TraceOption("shoot", 1.0, 0.25, {"pressure": 0.5}),
        ),
    )


def test_valid_trace_can_be_written(tmp_path: Path) -> None:
    destination = tmp_path / "trace.jsonl"
    write_traces(destination, (_valid_trace(),))
    assert '"selected":"pass"' in destination.read_text(encoding="utf-8")


def test_trace_rejects_invalid_probability_sum() -> None:
    trace = _valid_trace()
    invalid = DecisionTrace(
        sequence=trace.sequence,
        possession=trace.possession,
        action=trace.action,
        phase=trace.phase,
        actor=trace.actor,
        selected=trace.selected,
        rng_stream=trace.rng_stream,
        options=(TraceOption("pass", 1.0, 0.8), TraceOption("shoot", 1.0, 0.8)),
    )
    with pytest.raises(TraceError, match="sum to 1"):
        invalid.validate()


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ((), "at least one"),
        ((TraceOption("pass", 1.0, 0.5), TraceOption("pass", 1.0, 0.5)), "unique"),
        ((TraceOption("pass", -1.0, 1.0),), "non-negative"),
        ((TraceOption("pass", 1.0, float("nan")),), "finite"),
    ],
)
def test_trace_rejects_invalid_options(options: tuple[TraceOption, ...], message: str) -> None:
    trace = DecisionTrace(1, 0, 1, "offense", "home-1", "pass", "rng", options)
    with pytest.raises(TraceError, match=message):
        trace.validate()


def test_trace_rejects_unknown_selection() -> None:
    trace = DecisionTrace(
        1,
        0,
        1,
        "offense",
        "home-1",
        "drive",
        "rng",
        (TraceOption("pass", 1.0, 1.0),),
    )
    with pytest.raises(TraceError, match="not present"):
        trace.validate()
