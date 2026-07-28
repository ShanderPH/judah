"""Regression tests for runtime dependency compatibility boundaries."""

from pathlib import Path

from packaging.requirements import Requirement

BASE_REQUIREMENTS = Path(__file__).resolve().parents[2] / "requirements" / "base.txt"


def _runtime_requirement(package_name: str) -> Requirement:
    for raw_line in BASE_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        requirement = Requirement(line)
        if requirement.name.lower() == package_name.lower():
            return requirement
    raise AssertionError(f"Runtime requirement {package_name!r} was not found.")


def test_mcp_runtime_stays_on_agno_compatible_major_version() -> None:
    mcp = _runtime_requirement("mcp")

    assert mcp.specifier.contains("1.27.0")
    assert mcp.specifier.contains("1.28.1")
    assert not mcp.specifier.contains("2.0.0")
