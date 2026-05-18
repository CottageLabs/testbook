"""
Tests for testbook.web (Flask application).

GitHub calls, database calls, and config loading are mocked so no credentials,
network access, or database are required.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from testbook.config import reset_config
from testbook.models import ExecutionStep, ExecutionTest, TestExecution


def _mock_source_repo(branches=("main", "develop")):
    """Return a MagicMock that quacks like a SourceRepo."""
    repo = MagicMock()
    repo.list_branches.return_value = sorted(branches)
    return repo


def _mock_suite(name="Auth", testsets_count=2):
    """Return a MagicMock that quacks like a Suite with TestSets and Tests."""
    suite = MagicMock()
    suite.id = 1
    suite.name = name
    suite.stable_id = name.lower().replace(" ", "-")
    suite.repo_name = "org/repo"
    suite.branch = "main"
    suite.file_path = ""

    # Create mock testsets with tests
    testsets = []
    for i in range(testsets_count):
        testset = MagicMock()
        testset.id = i + 1
        testset.name = f"TestSet {i+1}"
        testset.stable_id = f"testset-{i+1}"
        tests = []
        for j in range(2):
            test = MagicMock()
            test.id = (i * 10) + j + 1
            test.stable_id = f"{name.lower()}-{i+1}-{j+1}"
            test.title = f"Test {j+1}"
            test.file_path = f"testbook/{name.lower()}_{i+1}.yml"
            test.context = {}
            test.setup_items = []
            test.steps = []
            test.dependencies = []
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

    def test_workbench_shell_and_placeholder_text_present(self):
        session_instance = MagicMock()
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = []
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/")
        self.assertIn(b"Select a testset or a test from the left navigation to view details.", response.data)
        self.assertIn(b"Test Plans", response.data)
        self.assertIn(b"Executions", response.data)

    def test_index_shows_sync_button_when_no_cached_data(self):
        # Mock the query to return no suites (need sync)
        session_instance = MagicMock()
        # Simple approach: return empty/None for all queries
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = []
        query_mock.filter_by.return_value.first.return_value = None
        query_mock.filter_by.return_value.order_by.return_value.all.return_value = []
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/")
        # Page should load successfully
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sync Tests", response.data)
        # Should show message for needing sync
        self.assertIn(b"Choose a branch and sync to load its tests", response.data)

    def test_index_renders_plan_selector_below_branch_when_plans_exist(self):
        session_instance = MagicMock()

        suites_query = MagicMock()
        suites_query.options.return_value.filter_by.return_value.all.return_value = []

        sync_query = MagicMock()
        sync_query.filter_by.return_value.first.return_value = None

        plan = SimpleNamespace(id=7, title="Smoke Plan")
        plans_query = MagicMock()
        plans_query.filter_by.return_value.order_by.return_value.all.return_value = [plan]

        session_instance.query.side_effect = [suites_query, sync_query, plans_query]
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="branch-select"', response.data)
        self.assertIn(b'id="plan-header-select"', response.data)
        self.assertIn(b"Smoke Plan", response.data)
        self.assertLess(
            response.data.index(b'id="branch-select"'),
            response.data.index(b'id="plan-header-select"'),
        )


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

    def test_index_renders_last_synced_label(self):
        session_instance = MagicMock()
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = []
        query_mock.filter_by.return_value.first.return_value = None
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/")
        self.assertIn(b"Last synced:", response.data)
        self.assertIn(b"freshness-status-label", response.data)
        self.assertIn(b"toast-container", response.data)

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

    def test_index_serializes_github_edit_url_for_tests(self):
        suite = _mock_suite("Authentication", 1)
        session_instance = MagicMock()
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = [suite]
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/")
        self.assertIn(
            b"https://github.com/org/repo/edit/main/testbook/authentication_1.yml",
            response.data,
        )

    def test_index_serializes_stable_id_for_tests(self):
        suite = _mock_suite("Authentication", 1)
        session_instance = MagicMock()
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = [suite]
        query_mock.filter_by.return_value.first.return_value = None
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/")
        self.assertIn(b'"stable_id": "authentication-1-1"', response.data)
        # Suite and testset stable_ids also present
        self.assertIn(b'"stable_id": "authentication"', response.data)
        self.assertIn(b'"stable_id": "testset-1"', response.data)

    def test_index_serializes_github_blob_url_for_step_resources(self):
        suite = _mock_suite("Authentication", 1)
        suite.testsets[0].tests[0].steps = [
            SimpleNamespace(
                id=1,
                text="Open linked resource",
                path="",
                resource="/fixtures/manuals/login.md",
                order_index=0,
                results=[],
            )
        ]
        session_instance = MagicMock()
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = [suite]
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/")
        self.assertIn(
            b"https://github.com/org/repo/blob/main/fixtures/manuals/login.md",
            response.data,
        )

    def test_index_serializes_github_blob_url_with_configured_resources_path(self):
        suite = _mock_suite("Authentication", 1)
        suite.testsets[0].tests[0].steps = [
            SimpleNamespace(
                id=1,
                text="Open linked resource",
                path="",
                resource="fixtures/manuals/login.md",
                order_index=0,
                results=[],
            )
        ]
        session_instance = MagicMock()
        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.all.return_value = [suite]
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        with patch(
            "testbook.web.get_source_repo_config",
            return_value={
                "repo_name": "org/repo",
                "default_branch": "main",
                "tests_path": "testbook",
                "resources_path": "doajtest",
                "github_token": "tok",
            },
        ):
            response = self.client.get("/")

        self.assertIn(
            b"https://github.com/org/repo/blob/main/doajtest/fixtures/manuals/login.md",
            response.data,
        )

    def test_branch_freshness_endpoint_marks_stale_when_remote_newer(self):
        session_instance = MagicMock()
        query_mock = MagicMock()
        query_mock.filter_by.return_value.first.return_value = SimpleNamespace(
            last_synced_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        )
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance
        self.repo_mock.latest_tests_commit_timestamp.return_value = datetime(
            2026, 1, 2, 12, 0, tzinfo=timezone.utc
        )

        response = self.client.get("/api/branch-freshness?branch=main")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["is_stale"])

    def test_branch_freshness_endpoint_not_stale_when_up_to_date(self):
        session_instance = MagicMock()
        query_mock = MagicMock()
        query_mock.filter_by.return_value.first.return_value = SimpleNamespace(
            last_synced_at=datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
        )
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance
        self.repo_mock.latest_tests_commit_timestamp.return_value = datetime(
            2026, 1, 1, 12, 0, tzinfo=timezone.utc
        )

        response = self.client.get("/api/branch-freshness?branch=main")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertFalse(data["is_stale"])


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

    def test_sync_endpoint_redirects_to_plans_when_return_view_is_plans(self):
        session_instance = MagicMock()
        self.session_mock_obj.return_value = session_instance

        response = self.client.post(
            "/sync",
            data={"branch": "main", "return_view": "plans"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/plans", response.location)
        self.assertIn("branch=main", response.location)

    def test_sync_endpoint_redirects_to_executions_when_return_view_is_executions(self):
        session_instance = MagicMock()
        self.session_mock_obj.return_value = session_instance

        response = self.client.post(
            "/sync",
            data={"branch": "main", "return_view": "executions"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/executions", response.location)
        self.assertIn("branch=main", response.location)


class TestPlansRoute(unittest.TestCase):

    def setUp(self):
        reset_config()
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

        self.repo_mock = _mock_source_repo()
        self.repo_patcher = patch("testbook.web._make_source_repo", return_value=self.repo_mock)
        self.repo_patcher.start()

        self.session_patcher = patch("testbook.web.get_session")
        self.session_mock_obj = self.session_patcher.start()

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

    def test_plans_route_returns_200_and_highlights_nav(self):
        session_instance = MagicMock()
        suites_query = MagicMock()
        suites_query.options.return_value.filter_by.return_value.all.return_value = []

        sync_query = MagicMock()
        sync_query.filter_by.return_value.first.return_value = None

        plans_query = MagicMock()
        plans_query.options.return_value.filter_by.return_value.order_by.return_value.all.return_value = []

        session_instance.query.side_effect = [suites_query, sync_query, plans_query]
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/plans")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Test Plans", response.data)
        # Active nav link for Test Plans should be present (multi-line href format)
        self.assertIn(b'subnav-link active', response.data)
        self.assertIn(b'href="/plans', response.data)
        self.assertIn(b"Add Plan", response.data)

    def test_plans_route_shows_plan_tests_navigation(self):
        suite = _mock_suite("Authentication", 1)
        plan_item = SimpleNamespace(test_id=suite.testsets[0].tests[0].id, order_index=0)
        plan = SimpleNamespace(id=7, title="Smoke Plan", plan_items=[plan_item])

        session_instance = MagicMock()
        suites_query = MagicMock()
        suites_query.options.return_value.filter_by.return_value.all.return_value = [suite]

        sync_query = MagicMock()
        sync_query.filter_by.return_value.first.return_value = None

        plans_query = MagicMock()
        plans_query.options.return_value.filter_by.return_value.order_by.return_value.all.return_value = [plan]

        session_instance.query.side_effect = [suites_query, sync_query, plans_query]
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/plans?plan_id=7")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Smoke Plan", response.data)
        self.assertIn(b'id="plan-nav-title">Smoke Plan', response.data)
        self.assertIn(b"Test 1", response.data)

    def test_add_plan_with_title(self):
        """POST /plans/add with a title uses that title instead of auto-generating one."""
        session_instance = MagicMock()
        created_plan = SimpleNamespace(id=42, title="My New Plan")
        session_instance.add = MagicMock()
        session_instance.commit = MagicMock()
        session_instance.close = MagicMock()
        self.session_mock_obj.return_value = session_instance

        # Capture the plan added so we can read its id
        def capture_add(obj):
            obj.id = 42

        session_instance.add.side_effect = capture_add

        response = self.client.post(
            "/plans/add",
            data={"branch": "main", "title": "My New Plan"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("plan_id=42", response.location)

    def test_update_plan_renames_it(self):
        """PATCH /api/plan/<id> renames the plan and returns updated JSON."""
        plan = MagicMock()
        plan.id = 7
        plan.title = "Smoke Plan"

        session_instance = MagicMock()
        session_instance.query.return_value.filter_by.return_value.first.return_value = plan
        session_instance.commit = MagicMock()
        session_instance.close = MagicMock()
        self.session_mock_obj.return_value = session_instance

        response = self.client.patch(
            "/api/plan/7",
            json={"title": "Renamed Plan"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["title"], "Renamed Plan")

    def test_update_plan_rejects_empty_title(self):
        """PATCH /api/plan/<id> with empty title returns 400."""
        session_instance = MagicMock()
        session_instance.close = MagicMock()
        self.session_mock_obj.return_value = session_instance

        response = self.client.patch(
            "/api/plan/7",
            json={"title": "   "},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class TestExecutionsRoute(unittest.TestCase):

    def setUp(self):
        reset_config()
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

        self.repo_mock = _mock_source_repo()
        self.repo_patcher = patch("testbook.web._make_source_repo", return_value=self.repo_mock)
        self.repo_patcher.start()

        self.session_patcher = patch("testbook.web.get_session")
        self.session_mock_obj = self.session_patcher.start()

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

    def test_executions_route_returns_200_and_highlights_nav(self):
        session_instance = MagicMock()
        sync_query = MagicMock()
        sync_query.filter_by.return_value.first.return_value = None

        plans_query = MagicMock()
        plans_query.options.return_value.filter_by.return_value.order_by.return_value.all.return_value = []

        executions_query = MagicMock()
        executions_query.options.return_value.filter_by.return_value.order_by.return_value.all.return_value = []

        session_instance.query.side_effect = [sync_query, plans_query, executions_query]
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/executions")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Executions", response.data)
        self.assertIn(b"Add Execution", response.data)
        self.assertIn(b"subnav-link active", response.data)
        self.assertIn(b"href=\"/executions", response.data)

    def test_add_execution_creates_snapshot_and_redirects(self):
        plan_test = SimpleNamespace(
            id=101,
            stable_id="auth-login-001",
            title="Valid Login",
            context={"role": "admin"},
            setup_items=[SimpleNamespace(order_index=0, text="Create account")],
            steps=[
                SimpleNamespace(
                    order_index=0,
                    text="Enter credentials",
                    path="/login",
                    resource="",
                    results=[SimpleNamespace(order_index=0, text="User is logged in")],
                )
            ],
            testset=SimpleNamespace(name="Login", suite=SimpleNamespace(name="Auth")),
        )
        plan_item = SimpleNamespace(order_index=0, test=plan_test)
        plan = SimpleNamespace(id=7, plan_items=[plan_item])

        session_instance = MagicMock()
        plan_query = MagicMock()
        plan_query.options.return_value.filter_by.return_value.first.return_value = plan

        existing_exec_query = MagicMock()
        existing_exec_query.filter_by.return_value.order_by.return_value.first.return_value = None

        session_instance.query.side_effect = [plan_query, existing_exec_query]

        captured = {"feedback_url": None}

        def capture_add(obj):
            if isinstance(obj, TestExecution):
                obj.id = 55
                captured["feedback_url"] = obj.feedback_url
            elif isinstance(obj, ExecutionTest):
                obj.id = 77
            elif isinstance(obj, ExecutionStep):
                obj.id = 88

        session_instance.add.side_effect = capture_add
        self.session_mock_obj.return_value = session_instance

        response = self.client.post(
            "/executions/add",
            data={
                "branch": "main",
                "plan_id": "7",
                "title": "Cycle 1",
                "feedback_url": "https://github.com/org/repo/issues/42",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/executions", response.location)
        self.assertIn("plan_id=7", response.location)
        self.assertIn("execution_id=55", response.location)
        self.assertEqual(captured["feedback_url"], "https://github.com/org/repo/issues/42")

    def test_update_execution_renames_it(self):
        execution = MagicMock()
        execution.id = 9
        execution.title = "Cycle 1"
        execution.feedback_url = ""

        session_instance = MagicMock()
        session_instance.query.return_value.filter_by.return_value.first.return_value = execution
        session_instance.commit = MagicMock()
        session_instance.close = MagicMock()
        self.session_mock_obj.return_value = session_instance

        response = self.client.patch(
            "/api/execution/9",
            json={
                "title": "Cycle 1 - Retest",
                "feedback_url": "https://github.com/org/repo/pull/55",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["title"], "Cycle 1 - Retest")
        self.assertEqual(data["feedback_url"], "https://github.com/org/repo/pull/55")

    def test_update_execution_test_allows_skipped_status(self):
        execution_test = MagicMock()
        execution_test.id = 22
        execution_test.status = "pending"
        execution_test.comment = ""

        session_instance = MagicMock()
        session_instance.query.return_value.filter_by.return_value.first.return_value = execution_test
        session_instance.commit = MagicMock()
        session_instance.close = MagicMock()
        self.session_mock_obj.return_value = session_instance

        response = self.client.patch(
            "/api/execution-test/22",
            json={"status": "skipped", "comment": "Not applicable for this release"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "skipped")
        self.assertEqual(data["comment"], "Not applicable for this release")

    def test_executions_route_displays_active_plan_in_sidebar(self):
        session_instance = MagicMock()
        sync_query = MagicMock()
        sync_query.filter_by.return_value.first.return_value = None

        plan = SimpleNamespace(id=7, title="Smoke Plan", plan_items=[])
        plans_query = MagicMock()
        plans_query.options.return_value.filter_by.return_value.order_by.return_value.all.return_value = [plan]

        executions_query = MagicMock()
        executions_query.options.return_value.filter_by.return_value.order_by.return_value.all.return_value = []

        session_instance.query.side_effect = [sync_query, plans_query, executions_query]
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/executions?plan_id=7")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Executing plan:", response.data)
        self.assertIn(b"Smoke Plan", response.data)

    def test_executions_route_displays_feedback_url_link_for_selected_execution(self):
        session_instance = MagicMock()
        sync_query = MagicMock()
        sync_query.filter_by.return_value.first.return_value = None

        plan = SimpleNamespace(id=7, title="Smoke Plan", plan_items=[])
        plans_query = MagicMock()
        plans_query.options.return_value.filter_by.return_value.order_by.return_value.all.return_value = [plan]

        execution = SimpleNamespace(
            id=9,
            title="Cycle 1",
            feedback_url="https://github.com/org/repo/issues/42",
            execution_tests=[],
            test_plan_id=7,
        )
        executions_query = MagicMock()
        executions_query.options.return_value.filter_by.return_value.order_by.return_value.all.return_value = [execution]

        def query_side_effect(model):
            if model.__name__ == "BranchSyncState":
                return sync_query
            if model.__name__ == "TestPlan":
                return plans_query
            if model.__name__ == "TestExecution":
                return executions_query
            return MagicMock()

        session_instance.query.side_effect = query_side_effect
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/reports?plan_id=7&execution_id=9")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Feedback:", response.data)
        self.assertIn(b'href="https://github.com/org/repo/issues/42"', response.data)

    def test_executions_route_serializes_github_blob_url_for_step_resources(self):
        execution = SimpleNamespace(
            repo_name="org/repo",
            branch="main",
            execution_tests=[
                SimpleNamespace(
                    id=301,
                    order_index=0,
                    steps=[
                        SimpleNamespace(
                            id=401,
                            text="Open resource",
                            resource="fixtures/manuals/login.md",
                            order_index=0,
                            comment="",
                            results=[],
                        )
                    ],
                    source_suite_name="Auth",
                    source_testset_name="Login",
                )
            ],
        )
        from testbook.web import _build_execution_suite_payload

        payload = _build_execution_suite_payload(execution, "doajtest")
        self.assertEqual(
            payload[0]["testsets"][0]["tests"][0]["steps"][0]["resource_url"],
            "https://github.com/org/repo/blob/main/doajtest/fixtures/manuals/login.md",
        )

    def test_reports_route_returns_200_and_shows_execution_summary(self):
        session_instance = MagicMock()
        sync_query = MagicMock()
        sync_query.filter_by.return_value.first.return_value = None

        plan = SimpleNamespace(id=7, title="Smoke Plan", plan_items=[])
        plans_query = MagicMock()
        plans_query.options.return_value.filter_by.return_value.order_by.return_value.all.return_value = [plan]

        execution = SimpleNamespace(
            id=9,
            title="Cycle 1",
            feedback_url="https://github.com/org/repo/issues/42",
            execution_tests=[
                SimpleNamespace(
                    id=201,
                    source_test_stable_id="auth-1",
                    source_suite_name="Auth",
                    source_testset_name="Login",
                    title="Passed test",
                    context={},
                    setup=[],
                    order_index=0,
                    status="pass",
                    comment="",
                    steps=[],
                ),
                SimpleNamespace(
                    id=202,
                    source_test_stable_id="auth-2",
                    source_suite_name="Auth",
                    source_testset_name="Login",
                    title="Failed test",
                    context={},
                    setup=[],
                    order_index=1,
                    status="fail",
                    comment="",
                    steps=[],
                ),
                SimpleNamespace(
                    id=203,
                    source_test_stable_id="auth-3",
                    source_suite_name="Auth",
                    source_testset_name="Login",
                    title="Skipped test",
                    context={},
                    setup=[],
                    order_index=2,
                    status="skipped",
                    comment="",
                    steps=[],
                ),
                SimpleNamespace(
                    id=204,
                    source_test_stable_id="auth-4",
                    source_suite_name="Auth",
                    source_testset_name="Login",
                    title="Todo test",
                    context={},
                    setup=[],
                    order_index=3,
                    status="pending",
                    comment="",
                    steps=[],
                ),
            ],
            test_plan_id=7,
            repo_name="org/repo",
            branch="main",
        )
        executions_query = MagicMock()
        executions_query.options.return_value.filter_by.return_value.order_by.return_value.all.return_value = [execution]

        def query_side_effect(model):
            if model.__name__ == "BranchSyncState":
                return sync_query
            if model.__name__ == "TestPlan":
                return plans_query
            if model.__name__ == "TestExecution":
                return executions_query
            return MagicMock()

        session_instance.query.side_effect = query_side_effect
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/reports?branch=main&plan_id=7&execution_id=9")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Reports", response.data)
        self.assertIn(b"Download test failures as markdown", response.data)
        self.assertIn(b"Push test failures to GitHub", response.data)
        self.assertIn(b"Cycle 1 (iter 1)", response.data)
        self.assertIn(b"P1/F1/S1/T1", response.data)
        self.assertIn(b"read-only-mode", response.data)

    def test_executions_route_displays_test_status_badges_in_navigation(self):
        session_instance = MagicMock()
        sync_query = MagicMock()
        sync_query.filter_by.return_value.first.return_value = None

        plan = SimpleNamespace(id=7, title="Smoke Plan", plan_items=[])
        plans_query = MagicMock()
        plans_query.options.return_value.filter_by.return_value.order_by.return_value.all.return_value = [plan]

        execution = SimpleNamespace(
            id=9,
            title="Cycle 1",
            feedback_url="",
            test_plan_id=7,
            execution_tests=[
                SimpleNamespace(
                    id=201,
                    source_test_stable_id="auth-1",
                    source_suite_name="Auth",
                    source_testset_name="Login",
                    title="Passed test",
                    context={},
                    setup=[],
                    order_index=0,
                    status="pass",
                    comment="",
                    steps=[],
                ),
                SimpleNamespace(
                    id=202,
                    source_test_stable_id="auth-2",
                    source_suite_name="Auth",
                    source_testset_name="Login",
                    title="Failed test",
                    context={},
                    setup=[],
                    order_index=1,
                    status="fail",
                    comment="",
                    steps=[],
                ),
                SimpleNamespace(
                    id=203,
                    source_test_stable_id="auth-3",
                    source_suite_name="Auth",
                    source_testset_name="Login",
                    title="Skipped test",
                    context={},
                    setup=[],
                    order_index=2,
                    status="pending",
                    comment="",
                    steps=[],
                ),
                SimpleNamespace(
                    id=204,
                    source_test_stable_id="auth-4",
                    source_suite_name="Auth",
                    source_testset_name="Login",
                    title="Skipped test",
                    context={},
                    setup=[],
                    order_index=3,
                    status="skipped",
                    comment="",
                    steps=[],
                ),
            ],
        )
        executions_query = MagicMock()
        executions_query.options.return_value.filter_by.return_value.order_by.return_value.all.return_value = [execution]

        def query_side_effect(model):
            if model.__name__ == "BranchSyncState":
                return sync_query
            if model.__name__ == "TestPlan":
                return plans_query
            if model.__name__ == "TestExecution":
                return executions_query
            return MagicMock()

        session_instance.query.side_effect = query_side_effect
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/reports?plan_id=7&execution_id=9")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'exec-nav-status exec-nav-status--pass', response.data)
        self.assertIn(b'>pass<', response.data)
        self.assertIn(b'exec-nav-status exec-nav-status--fail', response.data)
        self.assertIn(b'>fail<', response.data)
        self.assertIn(b'exec-nav-status exec-nav-status--todo', response.data)
        self.assertIn(b'>todo<', response.data)
        self.assertIn(b'exec-nav-status exec-nav-status--skipped', response.data)
        self.assertIn(b'>skipped<', response.data)

    def test_reports_download_failures_returns_markdown_attachment_for_failed_tests_only(self):
        session_instance = MagicMock()

        execution = SimpleNamespace(
            id=9,
            title="Cycle 1",
            branch="main",
            test_plan_id=7,
            execution_tests=[
                SimpleNamespace(
                    id=201,
                    source_suite_name="Auth",
                    source_testset_name="Login",
                    title="Failed login validation",
                    order_index=0,
                    status="fail",
                    steps=[
                        SimpleNamespace(
                            order_index=0,
                            text="Submit invalid credentials",
                            comment="Unexpected 500 shown",
                            results=[
                                SimpleNamespace(
                                    order_index=0,
                                    status="fail",
                                    text="Validation error message is shown",
                                    comment="UI shows stack trace",
                                ),
                                SimpleNamespace(
                                    order_index=1,
                                    status="pass",
                                    text="Username input remains visible",
                                    comment="",
                                ),
                            ],
                        )
                    ],
                ),
                SimpleNamespace(
                    id=202,
                    source_suite_name="Auth",
                    source_testset_name="Login",
                    title="Passing login flow",
                    order_index=1,
                    status="pass",
                    steps=[],
                ),
            ],
        )

        query_mock = MagicMock()
        query_mock.options.return_value.filter_by.return_value.first.return_value = execution
        session_instance.query.return_value = query_mock
        self.session_mock_obj.return_value = session_instance

        response = self.client.get("/reports/download-failures?branch=main&plan_id=7&execution_id=9")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/markdown", response.content_type)
        self.assertIn("attachment; filename=\"testbook-failures-execution-9.md\"", response.headers.get("Content-Disposition", ""))
        self.assertIn(b"# Testbook failed test report", response.data)
        self.assertIn(b"- **Full report:** [http://localhost:5005/reports?branch=main&plan_id=7&execution_id=9](http://localhost:5005/reports?branch=main&plan_id=7&execution_id=9)", response.data)
        self.assertIn(b"## Auth / Login", response.data)
        self.assertIn(b"### Failed login validation", response.data)
        self.assertIn(b"[View in Testbook](http://localhost:5005/reports?branch=main&plan_id=7&execution_id=9#test/201)", response.data)
        self.assertIn(b"- [ ] All issues resolved", response.data)
        self.assertIn(b"- [ ] **Step 1**: Submit invalid credentials", response.data)
        self.assertIn(b"    - User comment: *Unexpected 500 shown*", response.data)
        self.assertIn(b"        - [ ] Validation error message is shown (FAIL)", response.data)
        self.assertIn(b"            - [ ] User comment: *UI shows stack trace*", response.data)
        self.assertIn(b"        - Username input remains visible (PASS)", response.data)
        self.assertNotIn(b"Passing login flow", response.data)


if __name__ == "__main__":
    unittest.main()
