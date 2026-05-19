"""Tests for testbook.config."""
from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from testbook.config import (
    ConfigurationError,
    get_plans_repo_config,
    get_source_repo_config,
    load_config,
    reset_config,
)


class TestLoadConfig(unittest.TestCase):

    def setUp(self):
        reset_config()

    def tearDown(self):
        reset_config()

    def test_returns_empty_dict_when_no_file_found(self):
        with patch("testbook.config._find_config_file", return_value=None):
            cfg = load_config()
        self.assertEqual(cfg, {})

    def test_loads_yaml_from_testbook_config_env_var(self):
        content = textwrap.dedent("""\
            source_repo:
              repo_name: "org/repo"
              github_token: "tok"
        """)
        with _temp_config(content) as path:
            os.environ["TESTBOOK_CONFIG"] = path
            try:
                cfg = load_config()
            finally:
                del os.environ["TESTBOOK_CONFIG"]
        self.assertEqual(cfg["source_repo"]["repo_name"], "org/repo")


class TestGetSourceRepoConfig(unittest.TestCase):

    def setUp(self):
        reset_config()

    def tearDown(self):
        reset_config()
        for var in ("TESTBOOK_SOURCE_TOKEN", "TESTBOOK_ISSUES_TOKEN", "TESTBOOK_CONFIG"):
            os.environ.pop(var, None)

    def test_raises_when_repo_name_is_placeholder(self):
        content = textwrap.dedent("""\
            source_repo:
              repo_name: "PLACEHOLDER_OWNER/PLACEHOLDER_REPO"
              github_token: "tok"
        """)
        with _isolated_config(content):
            with self.assertRaises(ConfigurationError):
                get_source_repo_config()

    def test_raises_when_token_is_placeholder(self):
        content = textwrap.dedent("""\
            source_repo:
              repo_name: "org/repo"
              github_token: "PLACEHOLDER_GITHUB_TOKEN"
        """)
        with _isolated_config(content):
            with self.assertRaises(ConfigurationError):
                get_source_repo_config()

    def test_env_var_token_overrides_config_file(self):
        content = textwrap.dedent("""\
            source_repo:
              repo_name: "org/repo"
              github_token: ""
        """)
        with _isolated_config(content):
            os.environ["TESTBOOK_SOURCE_TOKEN"] = "env_token"
            try:
                cfg = get_source_repo_config()
            finally:
                del os.environ["TESTBOOK_SOURCE_TOKEN"]
        self.assertEqual(cfg["github_token"], "env_token")

    def test_returns_defaults_for_optional_fields(self):
        content = textwrap.dedent("""\
            source_repo:
              repo_name: "org/repo"
              github_token: "tok"
        """)
        with _isolated_config(content):
            cfg = get_source_repo_config()
        self.assertEqual(cfg["tests_path"], "testbook")
        self.assertEqual(cfg["resources_path"], "")
        self.assertEqual(cfg["default_branch"], "main")
        self.assertEqual(cfg["freshness_check_interval_seconds"], 1800)
        self.assertEqual(cfg["issues_repo"]["repo_name"], "org/repo")
        self.assertEqual(cfg["issues_repo"]["default_branch"], "main")
        self.assertEqual(cfg["issues_repo"]["github_token"], "tok")

    def test_returns_configured_optional_fields(self):
        content = textwrap.dedent("""\
            source_repo:
              repo_name: "org/repo"
              github_token: "tok"
              tests_path: "functional_tests"
              resources_path: "doajtest"
              default_branch: "develop"
              freshness_check_interval_seconds: 900
        """)
        with _isolated_config(content):
            cfg = get_source_repo_config()
        self.assertEqual(cfg["tests_path"], "functional_tests")
        self.assertEqual(cfg["resources_path"], "doajtest")
        self.assertEqual(cfg["default_branch"], "develop")
        self.assertEqual(cfg["freshness_check_interval_seconds"], 900)

    def test_returns_configured_issues_repo_fields(self):
        content = textwrap.dedent("""\
            source_repo:
              repo_name: "org/repo"
              github_token: "source_tok"
            issues_repo:
              repo_name: "org/issues"
              default_branch: "stable"
              github_token: "issues_tok"
        """)
        with _isolated_config(content):
            cfg = get_source_repo_config()

        self.assertEqual(cfg["issues_repo"]["repo_name"], "org/issues")
        self.assertEqual(cfg["issues_repo"]["default_branch"], "stable")
        self.assertEqual(cfg["issues_repo"]["github_token"], "issues_tok")

    def test_issues_repo_token_can_be_overridden_by_env_var(self):
        content = textwrap.dedent("""\
            source_repo:
              repo_name: "org/repo"
              github_token: "source_tok"
            issues_repo:
              repo_name: "org/issues"
              github_token: "issues_tok"
        """)
        with _isolated_config(content):
            os.environ["TESTBOOK_ISSUES_TOKEN"] = "issues_env_tok"
            cfg = get_source_repo_config()

        self.assertEqual(cfg["issues_repo"]["github_token"], "issues_env_tok")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _temp_config(content: str):
    """Write content to a temp file and yield its path."""
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
        fh.write(content)
        path = fh.name
    try:
        yield path
    finally:
        os.unlink(path)


@contextmanager
def _isolated_config(content: str):
    """Write content to a temp config file, point TESTBOOK_CONFIG at it,
    reset the config cache, and restore everything on exit."""
    with _temp_config(content) as path:
        old = os.environ.get("TESTBOOK_CONFIG")
        os.environ["TESTBOOK_CONFIG"] = path
        reset_config()
        try:
            yield path
        finally:
            if old is None:
                os.environ.pop("TESTBOOK_CONFIG", None)
            else:
                os.environ["TESTBOOK_CONFIG"] = old
            reset_config()


if __name__ == "__main__":
    unittest.main()
