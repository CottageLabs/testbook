"""
Tests for testbook.github_connector.

All GitHub API calls are mocked with unittest.mock, so no real token or
internet connection is required.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import yaml

from testbook.github_connector import PlansRepo, SourceRepo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_content_file(path: str, data: dict) -> MagicMock:
    """Return a mock ContentFile whose .content is base-64 encoded YAML."""
    raw = yaml.dump(data, allow_unicode=True).encode("utf-8")
    cf = MagicMock()
    cf.path = path
    cf.name = path.split("/")[-1]
    cf.type = "file"
    cf.content = base64.b64encode(raw).decode("utf-8")
    cf.sha = "abc123"
    return cf


def _make_dir_item(path: str) -> MagicMock:
    item = MagicMock()
    item.path = path
    item.name = path.split("/")[-1]
    item.type = "dir"
    return item


def _patch_github(repo_mock: MagicMock):
    """Patch Github, wire it to repo_mock, and return the already-started patcher."""
    patcher = patch("testbook.github_connector.Github")
    mock_cls = patcher.start()
    mock_cls.return_value.get_repo.return_value = repo_mock
    return patcher


# ---------------------------------------------------------------------------
# SourceRepo tests
# ---------------------------------------------------------------------------

class TestSourceRepoListTestFiles(unittest.TestCase):

    def setUp(self):
        self.repo = MagicMock()
        self.patcher = _patch_github(self.repo)

    def tearDown(self):
        self.patcher.stop()

    def test_flat_directory(self):
        """YAML files in a single directory are returned."""
        cf1 = _make_content_file("testbook/login.yml", {})
        cf2 = _make_content_file("testbook/signup.yml", {})
        self.repo.get_contents.return_value = [cf1, cf2]

        src = SourceRepo(token="tok", repo_name="org/repo")
        paths = src.list_test_files()

        self.assertEqual(paths, ["testbook/login.yml", "testbook/signup.yml"])
        self.repo.get_contents.assert_called_once_with("testbook", ref="main")

    def test_nested_directory_is_walked(self):
        """Sub-directories are recursed into."""
        dir_item = _make_dir_item("testbook/auth")
        cf = _make_content_file("testbook/auth/login.yml", {})
        non_yaml = MagicMock()
        non_yaml.type = "file"
        non_yaml.name = "README.md"
        non_yaml.path = "testbook/README.md"

        def get_contents(path, ref):
            if path == "testbook":
                return [dir_item, non_yaml]
            if path == "testbook/auth":
                return [cf]
            return []

        self.repo.get_contents.side_effect = get_contents

        src = SourceRepo(token="tok", repo_name="org/repo")
        paths = src.list_test_files()

        self.assertIn("testbook/auth/login.yml", paths)
        self.assertNotIn("testbook/README.md", paths)

    def test_custom_tests_path(self):
        """The tests_path parameter is forwarded to the API."""
        self.repo.get_contents.return_value = []

        src = SourceRepo(token="tok", repo_name="org/repo", tests_path="functional_tests")
        src.list_test_files()

        self.repo.get_contents.assert_called_once_with("functional_tests", ref="main")

    def test_custom_branch(self):
        """A non-default branch is forwarded correctly."""
        self.repo.get_contents.return_value = []

        src = SourceRepo(token="tok", repo_name="org/repo", branch="develop")
        src.list_test_files()

        self.repo.get_contents.assert_called_once_with("testbook", ref="develop")


class TestSourceRepoLoadTestFile(unittest.TestCase):

    def setUp(self):
        self.repo = MagicMock()
        self.patcher = _patch_github(self.repo)

    def tearDown(self):
        self.patcher.stop()

    def test_returns_parsed_yaml(self):
        payload = {"suite": "Auth", "testset": "Login", "tests": []}
        self.repo.get_contents.return_value = _make_content_file("testbook/login.yml", payload)

        src = SourceRepo(token="tok", repo_name="org/repo")
        result = src.load_test_file("testbook/login.yml")

        self.assertEqual(result, payload)

    def test_load_all_tests_yields_each_file(self):
        payload1 = {"suite": "Auth", "testset": "Login", "tests": []}
        payload2 = {"suite": "Auth", "testset": "Logout", "tests": []}
        cf1 = _make_content_file("testbook/login.yml", payload1)
        cf2 = _make_content_file("testbook/logout.yml", payload2)

        def get_contents(path, ref):
            if path == "testbook":
                return [cf1, cf2]
            if path == "testbook/login.yml":
                return cf1
            if path == "testbook/logout.yml":
                return cf2

        self.repo.get_contents.side_effect = get_contents

        src = SourceRepo(token="tok", repo_name="org/repo")
        results = list(src.load_all_tests())

        self.assertEqual(len(results), 2)
        paths = [r[0] for r in results]
        self.assertIn("testbook/login.yml", paths)
        self.assertIn("testbook/logout.yml", paths)


class TestSourceRepoListBranches(unittest.TestCase):

    def setUp(self):
        self.repo = MagicMock()
        self.patcher = _patch_github(self.repo)

    def tearDown(self):
        self.patcher.stop()

    def test_returns_sorted_branch_names(self):
        b1, b2, b3 = MagicMock(), MagicMock(), MagicMock()
        b1.name = "main"
        b2.name = "develop"
        b3.name = "feature/login"
        self.repo.get_branches.return_value = [b1, b2, b3]

        src = SourceRepo(token="tok", repo_name="org/repo")
        branches = src.list_branches()

        self.assertEqual(branches, ["develop", "feature/login", "main"])

    def test_empty_repository_returns_empty_list(self):
        self.repo.get_branches.return_value = []

        src = SourceRepo(token="tok", repo_name="org/repo")
        self.assertEqual(src.list_branches(), [])


class TestSourceRepoGithubFileUrl(unittest.TestCase):

    def setUp(self):
        self.repo = MagicMock()
        self.repo.full_name = "myorg/myproject"
        self.patcher = _patch_github(self.repo)

    def tearDown(self):
        self.patcher.stop()

    def test_url_contains_repo_branch_and_path(self):
        src = SourceRepo(token="tok", repo_name="myorg/myproject", branch="develop")
        url = src.github_file_url("testbook/auth/login.yml")
        self.assertEqual(url, "https://github.com/myorg/myproject/blob/develop/testbook/auth/login.yml")


class TestSourceRepoLatestTestsCommitTimestamp(unittest.TestCase):

    def setUp(self):
        self.repo = MagicMock()
        self.patcher = _patch_github(self.repo)

    def tearDown(self):
        self.patcher.stop()

    def test_returns_first_commit_date(self):
        commit_date = datetime(2026, 5, 1, 10, 30, tzinfo=timezone.utc)
        commit = MagicMock()
        commit.commit.committer.date = commit_date
        self.repo.get_commits.return_value = [commit]

        src = SourceRepo(token="tok", repo_name="org/repo", tests_path="testbook", branch="main")
        result = src.latest_tests_commit_timestamp()

        self.assertEqual(result, commit_date)
        self.repo.get_commits.assert_called_once_with(sha="main", path="testbook")

    def test_returns_none_when_no_commits(self):
        self.repo.get_commits.return_value = []

        src = SourceRepo(token="tok", repo_name="org/repo", tests_path="testbook", branch="main")
        self.assertIsNone(src.latest_tests_commit_timestamp())


# ---------------------------------------------------------------------------
# PlansRepo tests
# ---------------------------------------------------------------------------

class TestPlansRepoRead(unittest.TestCase):

    def setUp(self):
        self.repo = MagicMock()
        self.patcher = _patch_github(self.repo)

    def tearDown(self):
        self.patcher.stop()

    def test_read_returns_parsed_yaml(self):
        payload = {"plan": "Sprint 42", "tests": ["login", "logout"]}
        self.repo.get_contents.return_value = _make_content_file("plans/sprint-42.yml", payload)

        plans = PlansRepo(token="tok", repo_name="org/plans")
        result = plans.read("plans/sprint-42.yml")

        self.assertEqual(result, payload)
        self.repo.get_contents.assert_called_once_with("plans/sprint-42.yml", ref="main")


class TestPlansRepoWrite(unittest.TestCase):

    def setUp(self):
        self.repo = MagicMock()
        self.patcher = _patch_github(self.repo)

    def tearDown(self):
        self.patcher.stop()

    def test_write_creates_new_file_when_not_found(self):
        from github import GithubException
        self.repo.get_contents.side_effect = GithubException(404, data={}, headers={})

        plans = PlansRepo(token="tok", repo_name="org/plans")
        data = {"plan": "Sprint 1", "tests": []}
        plans.write("plans/sprint-1.yml", data, commit_message="Add Sprint 1 plan")

        self.repo.create_file.assert_called_once()
        call_kwargs = self.repo.create_file.call_args
        self.assertEqual(call_kwargs.kwargs["path"], "plans/sprint-1.yml")
        self.assertEqual(call_kwargs.kwargs["message"], "Add Sprint 1 plan")
        self.assertEqual(call_kwargs.kwargs["branch"], "main")
        # Content should be valid YAML that round-trips back to data
        written_bytes = call_kwargs.kwargs["content"]
        self.assertEqual(yaml.safe_load(written_bytes), data)

    def test_write_updates_existing_file(self):
        existing = _make_content_file("plans/sprint-1.yml", {"plan": "Sprint 1", "tests": []})
        self.repo.get_contents.return_value = existing

        plans = PlansRepo(token="tok", repo_name="org/plans")
        new_data = {"plan": "Sprint 1", "tests": ["login"]}
        plans.write("plans/sprint-1.yml", new_data, commit_message="Update Sprint 1")

        self.repo.update_file.assert_called_once()
        call_kwargs = self.repo.update_file.call_args
        self.assertEqual(call_kwargs.kwargs["path"], "plans/sprint-1.yml")
        self.assertEqual(call_kwargs.kwargs["sha"], "abc123")
        self.assertEqual(call_kwargs.kwargs["message"], "Update Sprint 1")
        written_bytes = call_kwargs.kwargs["content"]
        self.assertEqual(yaml.safe_load(written_bytes), new_data)

    def test_write_reraises_non_404_errors(self):
        from github import GithubException
        self.repo.get_contents.side_effect = GithubException(500, data={}, headers={})

        plans = PlansRepo(token="tok", repo_name="org/plans")
        with self.assertRaises(GithubException):
            plans.write("plans/x.yml", {}, commit_message="should fail")


class TestPlansRepoDelete(unittest.TestCase):

    def setUp(self):
        self.repo = MagicMock()
        self.patcher = _patch_github(self.repo)

    def tearDown(self):
        self.patcher.stop()

    def test_delete_fetches_sha_and_calls_delete_file(self):
        existing = _make_content_file("plans/old.yml", {})
        self.repo.get_contents.return_value = existing

        plans = PlansRepo(token="tok", repo_name="org/plans")
        plans.delete("plans/old.yml", commit_message="Remove old plan")

        self.repo.delete_file.assert_called_once_with(
            path="plans/old.yml",
            message="Remove old plan",
            sha="abc123",
            branch="main",
        )


class TestPlansRepoListFiles(unittest.TestCase):

    def setUp(self):
        self.repo = MagicMock()
        self.patcher = _patch_github(self.repo)

    def tearDown(self):
        self.patcher.stop()

    def test_list_files_returns_yaml_paths(self):
        cf1 = _make_content_file("plans/sprint-1.yml", {})
        cf2 = _make_content_file("plans/sprint-2.yml", {})
        self.repo.get_contents.return_value = [cf1, cf2]

        plans = PlansRepo(token="tok", repo_name="org/plans")
        paths = plans.list_files("plans")

        self.assertEqual(paths, ["plans/sprint-1.yml", "plans/sprint-2.yml"])


if __name__ == "__main__":
    unittest.main()
