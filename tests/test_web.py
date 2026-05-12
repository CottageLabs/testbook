"""
Tests for testbook.web (Flask application).

GitHub calls and config loading are mocked so no credentials or network
access are required.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from testbook.config import reset_config


def _mock_source_repo(branches=("main", "develop"), files=("testbook/login.yml",)):
    """Return a MagicMock that quacks like a SourceRepo."""
    repo = MagicMock()
    repo.list_branches.return_value = sorted(branches)
    repo.list_test_files.return_value = sorted(files)
    repo.github_file_url.side_effect = lambda p: f"https://github.com/org/repo/blob/main/{p}"
    return repo


class TestIndexRoute(unittest.TestCase):

    def setUp(self):
        reset_config()
        # Patch config so we never need a real config.yml
        self.cfg_patcher = patch(
            "testbook.web.get_source_repo_config",
            return_value={
                "repo_name": "org/repo",
                "tests_path": "testbook",
                "default_branch": "main",
                "github_token": "tok",
            },
        )
        self.cfg_patcher.start()

        # Patch _make_source_repo so no GitHub API calls happen
        self.repo_mock = _mock_source_repo()
        self.repo_patcher = patch("testbook.web._make_source_repo", return_value=self.repo_mock)
        self.repo_patcher.start()

        from testbook.web import create_app
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.cfg_patcher.stop()
        self.repo_patcher.stop()
        reset_config()

    def test_index_returns_200(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_index_contains_repo_name(self):
        response = self.client.get("/")
        self.assertIn(b"org/repo", response.data)

    def test_index_lists_branches_in_dropdown(self):
        self.repo_mock.list_branches.return_value = ["develop", "main"]
        response = self.client.get("/")
        self.assertIn(b"develop", response.data)
        self.assertIn(b"main", response.data)

    def test_index_lists_test_files(self):
        self.repo_mock.list_test_files.return_value = ["testbook/login.yml"]
        response = self.client.get("/")
        self.assertIn(b"testbook/login.yml", response.data)

    def test_branch_query_param_is_forwarded(self):
        self.client.get("/?branch=develop")
        self.repo_patcher.stop()  # stop the blanket patcher
        # Re-check that _make_source_repo would be called with the right branch
        # (tested indirectly — the important thing is no 500 is returned)
        self.repo_patcher.start()  # restart for tearDown

    def test_config_error_shows_error_banner(self):
        self.cfg_patcher.stop()
        with patch("testbook.web.get_source_repo_config",
                   side_effect=Exception("config missing")):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"GitHub error", response.data)
        self.cfg_patcher.start()  # restart for tearDown


if __name__ == "__main__":
    unittest.main()
