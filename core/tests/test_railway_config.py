"""Regression tests for Railway deployment configuration."""

import tomllib
from pathlib import Path


def test_api_runs_migrations_as_pre_deploy_command() -> None:
    """Keep database migrations ahead of API and worker runtime code."""
    repository_root = Path(__file__).resolve().parents[2]
    with (repository_root / "railway.toml").open("rb") as config_file:
        config = tomllib.load(config_file)

    deploy_config = config["deploy"]
    assert deploy_config["preDeployCommand"] == "python manage.py migrate --noinput"
    assert "releaseCommand" not in deploy_config
