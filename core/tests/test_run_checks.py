"""Tests for the local validation helper."""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import run_checks


def _patch_commands(monkeypatch: Any, commands: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
    monkeypatch.setattr(run_checks, "MANDATORY_COMMANDS", commands)


def _patch_subprocess(monkeypatch: Any, return_codes: Sequence[int]) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    remaining = list(return_codes)

    def fake_run(command: Sequence[str], *, check: bool) -> SimpleNamespace:
        assert check is False
        calls.append(tuple(command))
        return SimpleNamespace(returncode=remaining.pop(0))

    monkeypatch.setattr(run_checks.subprocess, "run", fake_run)
    return calls


def test_django_check_success_allows_overall_success(monkeypatch: Any) -> None:
    _patch_commands(monkeypatch, (("Running django checks...", ("python", "manage.py", "check")),))
    calls = _patch_subprocess(monkeypatch, [0])

    assert run_checks.main() == 0
    assert calls == [("python", "manage.py", "check")]


def test_django_check_failure_returns_non_zero(monkeypatch: Any) -> None:
    _patch_commands(monkeypatch, (("Running django checks...", ("python", "manage.py", "check")),))
    _patch_subprocess(monkeypatch, [3])

    assert run_checks.main() == 3


def test_migration_validation_success_allows_overall_success(monkeypatch: Any) -> None:
    _patch_commands(
        monkeypatch,
        (("Checking for missing migrations...", ("python", "manage.py", "makemigrations", "--check")),),
    )
    calls = _patch_subprocess(monkeypatch, [0])

    assert run_checks.main() == 0
    assert calls == [("python", "manage.py", "makemigrations", "--check")]


def test_migration_validation_failure_returns_non_zero(monkeypatch: Any) -> None:
    _patch_commands(
        monkeypatch,
        (("Checking for missing migrations...", ("python", "manage.py", "makemigrations", "--check")),),
    )
    _patch_subprocess(monkeypatch, [1])

    assert run_checks.main() == 1


def test_first_mandatory_failure_stops_later_commands(monkeypatch: Any) -> None:
    _patch_commands(
        monkeypatch,
        (
            ("Running migrations...", ("python", "manage.py", "migrate")),
            ("Checking for missing migrations...", ("python", "manage.py", "makemigrations", "--check")),
            ("Running django checks...", ("python", "manage.py", "check")),
        ),
    )
    calls = _patch_subprocess(monkeypatch, [2, 0, 0])

    assert run_checks.main() == 2
    assert calls == [("python", "manage.py", "migrate")]


def test_mandatory_commands_preserve_diagnostics(monkeypatch: Any, capsys: Any) -> None:
    _patch_commands(monkeypatch, (("Running django checks...", ("python", "manage.py", "check")),))
    _patch_subprocess(monkeypatch, [0])

    assert run_checks.main() == 0

    captured = capsys.readouterr()
    assert "Running django checks..." in captured.out


def test_run_checks_has_no_optional_commands() -> None:
    assert run_checks.MANDATORY_COMMANDS
