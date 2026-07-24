import pytest

from courtsim.invariants import InvariantSuite, InvariantViolation


def test_invariant_suite_collects_all_violations() -> None:
    suite = InvariantSuite[int](
        checks=(
            lambda value: ("must be positive",) if value <= 0 else (),
            lambda value: ("must be even",) if value % 2 else (),
        )
    )
    assert suite.inspect(-1) == ("must be positive", "must be even")
    with pytest.raises(InvariantViolation) as captured:
        suite.validate(-1)
    assert captured.value.violations == ("must be positive", "must be even")


def test_valid_state_passes() -> None:
    suite = InvariantSuite[int](checks=(lambda value: ("invalid",) if value < 0 else (),))
    suite.validate(2)
