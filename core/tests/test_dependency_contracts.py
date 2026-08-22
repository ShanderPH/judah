"""Regression tests for runtime dependency compatibility boundaries."""

from pathlib import Path

from packaging.requirements import Requirement

BASE_REQUIREMENTS = Path(__file__).resolve().parents[2] / "requirements" / "base.txt"
CONSTRAINTS = Path(__file__).resolve().parents[2] / "requirements" / "constraints.txt"


def _runtime_requirement(package_name: str) -> Requirement:
    for raw_line in BASE_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        requirement = Requirement(line)
        if requirement.name.lower() == package_name.lower():
            return requirement
    raise AssertionError(f"Runtime requirement {package_name!r} was not found.")


def _constraint(package_name: str) -> Requirement:
    for raw_line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            requirement = Requirement(line)
            if requirement.name.lower() == package_name.lower():
                return requirement
    raise AssertionError(f"Constraint {package_name!r} was not found.")


def test_agno_runtime_is_pinned_to_validated_version() -> None:
    assert _runtime_requirement("agno").specifier.contains("2.8.5")
    agno = _constraint("agno")

    assert agno.specifier.contains("2.8.5")
    assert not agno.specifier.contains("2.9.0")
