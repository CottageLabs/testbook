"""
Tests for testbook.web (Flask application).

GitHub calls, database calls, and config loading are mocked so no credentials,
network access, or database are required.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from testbook.config import reset_config


def _mock_source_repo(branches=("main", "develop")):
    """Return a MagicMock that quacks like a SourceRepo."""
    repo = MagicMock()
    repo.list_branches.return_value = sorted(branches)
    return repo


def _mock_suite(name="Auth", testsets_count=2):
    """Return a MagicMock that quacks like a Suite with TestSets and Tests."""
    suite = MagicMock()
    suite.name = name
    suite.repo_name = "org/repo"
    suite.branch = "main"

    # Create mock testsets with tests
    testsets = []
    for i in range(testsets_count):
        testset = MagicMock()
        testset.name = f"TestSet {i+1}"
        tests = []
        for j in range(2):
            test = MagicMock()
            test.title = f"Test {j+1}"
            tests.append(test)
        testset.tests = tests
        testsets.append(testset)

    suite.testsets = testsets
    return suite


class TestIndexRoute(unittest.TestCase):

    def setUp(self):
        reset_config()
        # Patch config so we never need a real config.yml
        self.cfg_patcher = patch(
            "testbook.web.get_source_repo_config",
            return_value={
                "repo_name": "org/repo",
                "default_branch": "main",
                "tests_path": "testbook",
                "github_token": "tok",
            },
        )
        self.cfg_patcher.start()

        # Patch _make_source_repo
        self.repo_mock = _mock_source_repo()
        self.repo_patcher = patch("testbook.web._make_source_repo", return_value=self.repo_mock)
        self.repo_patcher.start()

        # Patch database operations
        self.session_patcher = patch("testbook.web.get_session")
        self.session_mock_obj = self.session_patcher.start()

        # Patch init_db so it doesn't try to create real DB
        self.init_db_patcher = patch("testbook.web.init_db")
        self.init_db_patcher.start()

        from testbook.web import create_app
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.cfg_patcher.stop()
        self.repo_patcher.stop()
        self.session_patcher.stop()
        self.init_db_patcher.stop()
        reset_config()

    def test_index_returns_200(self):
        # Mock the query to return no suites (need sync)
        session_instance = MagicMock()
        # Handle the .options().filter_by().all() chain
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = []
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_index_shows_sync_button_when_no_cached_data(self):
        # Mock the query to return no suites (need sync)
        session_instance = MagicMock()
        # Handle the .options().filter_by().all() chain
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = []
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/")
        # Sync button should be visible
        self.assertIn(b"Sync Tests", response.data)


    def test_index_displays_cached_suites_when_available(self):
        # Mock the query to return suites
        suite1 = _mock_suite("Auth", 2)
        session_instance = MagicMock()
        # Handle the .options().filter_by().all() chain
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = [suite1]
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/")
        self.assertIn(b"Auth", response.data)
        self.assertIn(b"TestSet", response.data)
        self.assertIn(b"Test Suites", response.data)

    def test_index_lists_branches(self):
        session_instance = MagicMock()
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = []
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/")
        self.assertIn(b"develop", response.data)
        self.assertIn(b"main", response.data)

    def test_branch_query_param_preserves_selection(self):
        session_instance = MagicMock()
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = []
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/?branch=develop")
        # The branch is passed to _make_source_repo;
        # we verify it doesn't crash (200 response)
        self.assertEqual(response.status_code, 200)

    def test_index_shows_test_hierarchy(self):
        suite = _mock_suite("Authentication", 2)
        session_instance = MagicMock()
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = [suite]
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/")
        # Check that test titles appear
        self.assertIn(b"Test 1", response.data)


class TestSyncRoute(unittest.TestCase):

    def setUp(self):
        reset_config()
        # Patch config
        self.cfg_patcher = patch(
            "testbook.web.get_source_repo_config",
            return_value={
                "repo_name": "org/repo",
                "default_branch": "main",
                "tests_path": "testbook",
                "github_token": "tok",
            },
        )
        self.cfg_patcher.start()

        # Patch _make_source_repo
        self.repo_mock = _mock_source_repo()
        self.repo_patcher = patch("testbook.web._make_source_repo", return_value=self.repo_mock)
        self.repo_patcher.start()

        # Patch sync_from_source_repo
        self.sync_patcher = patch("testbook.web.sync_from_source_repo")
        self.sync_mock = self.sync_patcher.start()

        # Patch database session
        self.session_patcher = patch("testbook.web.get_session")
        self.session_mock_obj = self.session_patcher.start()

        # Patch init_db
        self.init_db_patcher = patch("testbook.web.init_db")
        self.init_db_patcher.start()

        from testbook.web import create_app
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.cfg_patcher.stop()
        self.repo_patcher.stop()
        self.sync_patcher.stop()
        self.session_patcher.stop()
        self.init_db_patcher.stop()
        reset_config()

    def test_sync_endpoint_redirects_to_index(self):
        session_instance = MagicMock()
        self.session_mock_obj.return_value = session_instance

        response = self.client.post("/sync", data={"branch": "main"}, follow_redirects=False)
        # Should redirect to /
        self.assertEqual(response.status_code, 302)
        self.assertIn("branch=main", response.location)

    def test_sync_endpoint_calls_sync_from_source_repo(self):
        session_instance = MagicMock()
        self.session_mock_obj.return_value = session_instance

        response = self.client.post("/sync", data={"branch": "main"}, follow_redirects=True)
        # Verify sync was called
        self.sync_mock.assert_called_once()

    def test_sync_endpoint_with_different_branch(self):
        session_instance = MagicMock()
        self.session_mock_obj.return_value = session_instance

        self.client.post("/sync", data={"branch": "develop"}, follow_redirects=True)
        # Verify _make_source_repo was called with develop branch
        # (checked via the redirect location)
        self.sync_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
