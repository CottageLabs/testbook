"""
Configuration loader for testbook.

Resolution order for the config file:
  1. Path given by the ``TESTBOOK_CONFIG`` environment variable.
  2. ``config.yml`` in the current working directory.
  3. ``~/.testbook/config.yml``

Tokens can also be supplied (or overridden) via environment variables:
  - ``TESTBOOK_SOURCE_TOKEN``  — GitHub token for the source (code) repo.
  - ``TESTBOOK_PLANS_TOKEN``   — GitHub token for the plans repo.
  - ``TESTBOOK_ISSUES_TOKEN``  — GitHub token for the issues/feedback repo.

These env vars take priority over whatever is written in the config file,
which makes it safe to leave the ``github_token`` fields blank in
``config.yml`` for production deployments.

Server settings can also be overridden via environment variable:
  - ``TESTBOOK_PORT`` — TCP port the web server listens on (default 5005).
"""
from __future__ import annotations

import os
from typing import Any

import yaml

# Ordered list of candidate config file paths.
# Evaluated as a function so env-var changes made after import are picked up.
def _candidate_paths() -> list[str]:
    return [
        os.environ.get("TESTBOOK_CONFIG", ""),
        "config.yml",
        os.path.expanduser("~/.testbook/config.yml"),
    ]


def _find_config_file() -> str | None:
    for path in _candidate_paths():
        if path and os.path.isfile(path):
            return path
    return None


def load_config() -> dict[str, Any]:
    """Load and return the raw config dict.

    Returns an empty dict if no config file is found, so callers can proceed
    and surface a friendlier error when they actually try to use missing values.
    """
    path = _find_config_file()
    if path is None:
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# Module-level singleton; cleared by tests that need a fresh load.
_config: dict[str, Any] | None = None


def get_config() -> dict[str, Any]:
    """Return the (cached) application configuration."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Clear the cached config.  Intended for use in tests only."""
    global _config
    _config = None


# ---------------------------------------------------------------------------
# Typed helpers used by the rest of the application
# ---------------------------------------------------------------------------

class ConfigurationError(Exception):
    """Raised when a required configuration value is missing or invalid."""


def _token(section: dict[str, Any], env_var: str) -> str:
    """Return the GitHub token, preferring the env var over the config file."""
    return os.environ.get(env_var, "") or section.get("github_token", "")


def get_source_repo_config() -> dict[str, Any]:
    """Return resolved config for the source (code) repository.

    Raises ``ConfigurationError`` if required keys are absent.
    """
    cfg = get_config()
    section = cfg.get("source_repo", {})

    repo_name = section.get("repo_name", "")
    if not repo_name or "PLACEHOLDER" in repo_name:
        raise ConfigurationError(
            "source_repo.repo_name is not configured.  "
            "Edit config.yml and set a real GitHub owner/repo value."
        )

    token = _token(section, "TESTBOOK_SOURCE_TOKEN")
    if not token or "PLACEHOLDER" in token:
        raise ConfigurationError(
            "No GitHub token found for the source repository.  "
            "Set source_repo.github_token in config.yml or the "
            "TESTBOOK_SOURCE_TOKEN environment variable."
        )

    issues_section = cfg.get("issues_repo", {})
    issues_repo_name = issues_section.get("repo_name", repo_name)
    issues_default_branch = issues_section.get("default_branch", section.get("default_branch", "main"))
    _raw_issues_token = os.environ.get("TESTBOOK_ISSUES_TOKEN", "") or issues_section.get("github_token", "")
    issues_token = _raw_issues_token if (_raw_issues_token and "PLACEHOLDER" not in _raw_issues_token) else token

    return {
        "repo_name": repo_name,
        "tests_path": section.get("tests_path", "testbook"),
        "resources_path": section.get("resources_path", ""),
        "default_branch": section.get("default_branch", "main"),
        "default_base_url": section.get("default_base_url", "http://localhost:5004/"),
        "freshness_check_interval_seconds": section.get("freshness_check_interval_seconds", 1800),
        "github_token": token,
        "issues_repo": {
            "repo_name": issues_repo_name,
            "default_branch": issues_default_branch,
            "github_token": issues_token,
        },
    }


def get_server_config() -> dict[str, Any]:
    """Return resolved server configuration.

    Port resolution order:
      1. ``TESTBOOK_PORT`` environment variable.
      2. ``server.port`` in config.yml.
      3. Default: 5005.
    """
    cfg = get_config()
    section = cfg.get("server", {})
    env_port = os.environ.get("TESTBOOK_PORT", "")
    try:
        port = int(env_port) if env_port else int(section.get("port", 5005))
    except (ValueError, TypeError):
        raise ConfigurationError(
            f"Invalid port value '{env_port or section.get('port')}'. "
            "Must be an integer."
        )
    return {"port": port}


def get_testbook_base_url() -> str:
    """Return the testbook application base URL.

    Resolution order:
      1. ``TESTBOOK_BASE_URL`` environment variable.
      2. ``server.testbook_base_url`` in config.yml.
      3. Default: http://localhost:5005/
    """
    cfg = get_config()
    env_url = os.environ.get("TESTBOOK_BASE_URL", "")
    if env_url:
        url = env_url.rstrip("/") + "/"
        return url

    section = cfg.get("server", {})
    config_url = section.get("testbook_base_url", "")
    if config_url:
        url = config_url.rstrip("/") + "/"
        return url

    return "http://localhost:5005/"


def sync_flaskenv(port: int, flaskenv_path: str = ".flaskenv") -> None:
    """Write/update FLASK_RUN_PORT in .flaskenv so `flask run` (and PyCharm's
    Flask runner) always uses the same port as config.yml.

    Preserves all other lines in the file unchanged.
    """
    target_line = f"FLASK_RUN_PORT={port}\n"
    key = "FLASK_RUN_PORT"

    if os.path.isfile(flaskenv_path):
        with open(flaskenv_path, encoding="utf-8") as fh:
            lines = fh.readlines()
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(key + "=") or line.startswith(key + " ="):
                if lines[i] != target_line:
                    lines[i] = target_line
                    updated = True
                break
        else:
            lines.append(target_line)
            updated = True
        if updated:
            with open(flaskenv_path, "w", encoding="utf-8") as fh:
                fh.writelines(lines)
    else:
        with open(flaskenv_path, "w", encoding="utf-8") as fh:
            fh.write(f"FLASK_APP=testbook.web:app\nFLASK_RUN_HOST=0.0.0.0\n{target_line}")


def get_plans_repo_config() -> dict[str, Any]:
    """Return resolved config for the plans repository.

    Raises ``ConfigurationError`` if required keys are absent.
    """
    cfg = get_config()
    section = cfg.get("plans_repo", {})

    repo_name = section.get("repo_name", "")
    if not repo_name or "PLACEHOLDER" in repo_name:
        raise ConfigurationError(
            "plans_repo.repo_name is not configured.  "
            "Edit config.yml and set a real GitHub owner/repo value."
        )

    token = _token(section, "TESTBOOK_PLANS_TOKEN")
    if not token or "PLACEHOLDER" in token:
        raise ConfigurationError(
            "No GitHub token found for the plans repository.  "
            "Set plans_repo.github_token in config.yml or the "
            "TESTBOOK_PLANS_TOKEN environment variable."
        )

    return {
        "repo_name": repo_name,
        "default_branch": section.get("default_branch", "main"),
        "github_token": token,
    }


