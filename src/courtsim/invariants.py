"""Composable state invariant checks for debug and test runs."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

StateT = TypeVar("StateT")
InvariantCheck = Callable[[StateT], Iterable[str]]


class InvariantViolation(RuntimeError):
    def __init__(self, violations: tuple[str, ...]) -> None:
        self.violations = violations
        super().__init__("; ".join(violations))


@dataclass(frozen=True, slots=True)
class InvariantSuite(Generic[StateT]):
    checks: tuple[InvariantCheck[StateT], ...]

    def inspect(self, state: StateT) -> tuple[str, ...]:
        return tuple(message for check in self.checks for message in check(state))

    def validate(self, state: StateT) -> None:
        violations = self.inspect(state)
        if violations:
            raise InvariantViolation(violations)
