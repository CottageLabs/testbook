"""
Tests for testbook.models and testbook.database.

Uses an in-memory SQLite database so tests run fast and in isolation.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from testbook.database import _upgrade_schema, reset_db, sync_from_source_repo
from testbook.models import (
    Base,
    BranchSyncState,
    ExecutionResult,
    ExecutionStep,
    ExecutionTest,
    Result,
    SetupItem,
    Step,
    Suite,
    Test,
    TestDependency,
    TestExecution,
    TestPlan,
    TestSet,
)


class TestModelsSchema(unittest.TestCase):
    """Verify that the ORM models create the expected schema."""

    def setUp(self):
        """Set up an in-memory SQLite database for testing."""
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.session = self.SessionLocal()

    def tearDown(self):
        self.session.close()

    def test_can_create_suite(self):
        suite = Suite(
            name="Authentication",
            repo_name="org/repo",
            branch="main",
            file_path="testbook/auth.yml",
        )
        self.session.add(suite)
        self.session.commit()

        fetched = self.session.query(Suite).first()
        self.assertEqual(fetched.name, "Authentication")
        self.assertEqual(fetched.repo_name, "org/repo")

    def test_suite_cascade_delete_testsets(self):
        suite = Suite(
            name="Auth",
            repo_name="org/repo",
            branch="main",
            file_path="test.yml",
        )
        self.session.add(suite)
        self.session.flush()

        testset = TestSet(name="Login", suite_id=suite.id)
        self.session.add(testset)
        self.session.commit()

        self.session.delete(suite)
        self.session.commit()

        self.assertEqual(self.session.query(TestSet).count(), 0)

    def test_testset_has_many_tests(self):
        suite = Suite(name="Auth", repo_name="org/repo", branch="main", file_path="test.yml")
        self.session.add(suite)
        self.session.flush()

        testset = TestSet(name="Login", suite_id=suite.id)
        self.session.add(testset)
        self.session.flush()

        test1 = Test(title="Valid Login", testset_id=testset.id, order_index=0)
        test2 = Test(title="Invalid Login", testset_id=testset.id, order_index=1)
        self.session.add_all([test1, test2])
        self.session.commit()

        fetched_testset = self.session.query(TestSet).first()
        self.assertEqual(len(fetched_testset.tests), 2)
        self.assertEqual(fetched_testset.tests[0].title, "Valid Login")

    def test_test_has_steps_with_results(self):
        suite = Suite(name="Auth", repo_name="org/repo", branch="main", file_path="test.yml")
        testset = TestSet(name="Login", suite_id=None)
        testset.suite = suite
        self.session.add(suite)
        self.session.flush()
        testset.suite_id = suite.id
        self.session.add(testset)
        self.session.flush()

        test = Test(title="Login", testset_id=testset.id)
        self.session.add(test)
        self.session.flush()

        step = Step(test_id=test.id, text="Enter credentials", order_index=0)
        self.session.add(step)
        self.session.flush()

        result = Result(step_id=step.id, text="Page shows success", order_index=0)
        self.session.add(result)
        self.session.commit()

        fetched_test = self.session.query(Test).first()
        self.assertEqual(len(fetched_test.steps), 1)
        self.assertEqual(len(fetched_test.steps[0].results), 1)

    def test_test_can_have_setup_items(self):
        suite = Suite(name="Auth", repo_name="org/repo", branch="main", file_path="test.yml")
        testset = TestSet(name="Login", suite_id=None)
        testset.suite = suite
        self.session.add(suite)
        self.session.flush()
        testset.suite_id = suite.id
        self.session.add(testset)
        self.session.flush()

        test = Test(title="Login", testset_id=testset.id)
        self.session.add(test)
        self.session.flush()

        setup1 = SetupItem(test_id=test.id, text="Create user", order_index=0)
        setup2 = SetupItem(test_id=test.id, text="Log out", order_index=1)
        self.session.add_all([setup1, setup2])
        self.session.commit()

        fetched_test = self.session.query(Test).first()
        self.assertEqual(len(fetched_test.setup_items), 2)

    def test_test_can_have_dependencies(self):
        suite = Suite(name="Auth", repo_name="org/repo", branch="main", file_path="test.yml")
        testset = TestSet(name="Login", suite_id=None)
        testset.suite = suite
        self.session.add(suite)
        self.session.flush()
        testset.suite_id = suite.id
        self.session.add(testset)
        self.session.flush()

        test = Test(title="Password reset", testset_id=testset.id)
        self.session.add(test)
        self.session.flush()

        dep = TestDependency(
            dependent_test_id=test.id,
            dep_suite_name="Auth",
            dep_testset_name="Login",
            dep_test_title="Valid login",
        )
        self.session.add(dep)
        self.session.commit()

        fetched_test = self.session.query(Test).first()
        self.assertEqual(len(fetched_test.dependencies), 1)
        self.assertEqual(fetched_test.dependencies[0].dep_test_title, "Valid login")

    def test_step_can_have_path_and_resource(self):
        suite = Suite(name="Auth", repo_name="org/repo", branch="main", file_path="test.yml")
        testset = TestSet(name="Login", suite_id=None)
        testset.suite = suite
        self.session.add(suite)
        self.session.flush()
        testset.suite_id = suite.id
        self.session.add(testset)
        self.session.flush()

        test = Test(title="Login", testset_id=testset.id)
        self.session.add(test)
        self.session.flush()

        step = Step(
            test_id=test.id,
            text="Upload file",
            path="/account/upload",
            resource="/fixtures/test_file.txt",
            order_index=0,
        )
        self.session.add(step)
        self.session.commit()

        fetched_step = self.session.query(Step).first()
        self.assertEqual(fetched_step.path, "/account/upload")
        self.assertEqual(fetched_step.resource, "/fixtures/test_file.txt")

    def test_test_context_is_json_stored(self):
        suite = Suite(name="Auth", repo_name="org/repo", branch="main", file_path="test.yml")
        testset = TestSet(name="Login", suite_id=None)
        testset.suite = suite
        self.session.add(suite)
        self.session.flush()
        testset.suite_id = suite.id
        self.session.add(testset)
        self.session.flush()

        context = {"role": "admin", "user_type": "premium"}
        test = Test(title="Admin login", testset_id=testset.id, context=context)
        self.session.add(test)
        self.session.commit()

        fetched_test = self.session.query(Test).first()
        self.assertEqual(fetched_test.context, context)


class TestSyncFromSourceRepo(unittest.TestCase):
    """Test the sync_from_source_repo function."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def test_sync_creates_suite_testset_test_steps_results(self):
        # Mock SourceRepo
        mock_repo = MagicMock()
        mock_repo.repo_name = "org/repo"
        mock_repo.branch = "main"

        test_yaml = {
            "suite": "Authentication",
            "testset": "Login",
            "tests": [
                {
                    "title": "Valid credentials",
                    "context": {"role": "user"},
                    "setup": ["Create user account"],
                    "steps": [
                        {
                            "step": "Navigate to login",
                            "path": "/login",
                            "results": ["Page loads"],
                        },
                        {
                            "step": "Enter credentials",
                            "results": ["Login successful"],
                        },
                    ],
                }
            ],
        }
        mock_repo.load_all_tests.return_value = [("testbook/auth.yml", test_yaml)]

        session = self.SessionLocal()
        count = sync_from_source_repo(mock_repo, session)

        # Now returns count of suites, not files
        self.assertEqual(count, 1)

        synced_test = session.query(Test).first()
        self.assertIsNotNone(synced_test)
        self.assertEqual(synced_test.file_path, "testbook/auth.yml")
        self.assertEqual(synced_test.stable_id, "valid-credentials")

        sync_state = session.query(BranchSyncState).filter_by(repo_name="org/repo", branch="main").first()
        self.assertIsNotNone(sync_state)
        self.assertIsNotNone(sync_state.last_synced_at)

        # ...existing code...

        session.close()


class TestExecutionModels(unittest.TestCase):
    """Verify execution models persist by-value snapshots and runtime status."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.session = self.SessionLocal()

    def tearDown(self):
        self.session.close()

    def _seed_source_test_and_plan(self):
        suite = Suite(name="Auth", repo_name="org/repo", branch="main", file_path="test.yml")
        self.session.add(suite)
        self.session.flush()

        testset = TestSet(name="Login", suite_id=suite.id)
        self.session.add(testset)
        self.session.flush()

        test = Test(
            stable_id="auth-login-001",
            title="Valid login",
            testset_id=testset.id,
            context={"role": "admin"},
            file_path="test.yml",
        )
        self.session.add(test)
        self.session.flush()

        step = Step(test_id=test.id, text="Enter credentials", path="/login", order_index=0)
        self.session.add(step)
        self.session.flush()

        result = Result(step_id=step.id, text="User is logged in", order_index=0)
        self.session.add(result)

        plan = TestPlan(
            title="Smoke",
            repo_name="org/repo",
            branch="main",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.session.add(plan)
        self.session.flush()
        return suite, testset, test, step, result, plan

    def test_execution_can_store_status_and_comments(self):
        _, _, source_test, _, _, plan = self._seed_source_test_and_plan()

        execution = TestExecution(
            test_plan_id=plan.id,
            repo_name="org/repo",
            branch="main",
            tester_name="Richard",
            iteration=2,
            is_finished=True,
            comment="Stopped early by design",
            created_at=datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 2, 10, 15, tzinfo=timezone.utc),
        )
        self.session.add(execution)
        self.session.flush()

        ex_test = ExecutionTest(
            execution_id=execution.id,
            source_test_id=source_test.id,
            source_test_stable_id=source_test.stable_id,
            source_suite_name="Auth",
            source_testset_name="Login",
            title="Valid login",
            context={"role": "admin"},
            setup=["Create account"],
            order_index=0,
            status="fail",
            comment="Test failed due to timeout",
        )
        self.session.add(ex_test)
        self.session.flush()

        ex_step = ExecutionStep(
            execution_test_id=ex_test.id,
            text="Enter credentials",
            path="/login",
            resource=None,
            order_index=0,
            comment="Slow response",
        )
        self.session.add(ex_step)
        self.session.flush()

        ex_result = ExecutionResult(
            execution_step_id=ex_step.id,
            text="User is logged in",
            order_index=0,
            status="fail",
            comment="Login button returned 500",
        )
        self.session.add(ex_result)
        self.session.commit()

        fetched = self.session.query(TestExecution).first()
        self.assertEqual(fetched.tester_name, "Richard")
        self.assertEqual(fetched.iteration, 2)
        self.assertTrue(fetched.is_finished)
        self.assertEqual(fetched.execution_tests[0].status, "fail")
        self.assertEqual(fetched.execution_tests[0].steps[0].comment, "Slow response")
        self.assertEqual(
            fetched.execution_tests[0].steps[0].results[0].comment,
            "Login button returned 500",
        )

    def test_execution_snapshot_is_by_value_not_live_reference(self):
        _, _, source_test, source_step, source_result, plan = self._seed_source_test_and_plan()

        execution = TestExecution(
            test_plan_id=plan.id,
            repo_name="org/repo",
            branch="main",
            tester_name="Alice",
            iteration=1,
            is_finished=False,
            created_at=datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc),
        )
        self.session.add(execution)
        self.session.flush()

        ex_test = ExecutionTest(
            execution_id=execution.id,
            source_test_id=source_test.id,
            source_test_stable_id=source_test.stable_id,
            source_suite_name="Auth",
            source_testset_name="Login",
            title=source_test.title,
            context=dict(source_test.context),
            setup=["Create account"],
            order_index=0,
        )
        self.session.add(ex_test)
        self.session.flush()

        ex_step = ExecutionStep(
            execution_test_id=ex_test.id,
            text=source_step.text,
            path=source_step.path,
            order_index=0,
        )
        self.session.add(ex_step)
        self.session.flush()

        self.session.add(
            ExecutionResult(
                execution_step_id=ex_step.id,
                text=source_result.text,
                order_index=0,
            )
        )
        self.session.commit()

        # Simulate source test update after execution has started.
        source_test.title = "Valid login updated"
        source_step.text = "Enter credentials and MFA"
        source_result.text = "Dashboard is shown"
        self.session.commit()

        frozen_ex_test = self.session.query(ExecutionTest).first()
        frozen_ex_step = self.session.query(ExecutionStep).first()
        frozen_ex_result = self.session.query(ExecutionResult).first()

        self.assertEqual(frozen_ex_test.title, "Valid login")
        self.assertEqual(frozen_ex_step.text, "Enter credentials")
        self.assertEqual(frozen_ex_result.text, "User is logged in")


class TestSchemaUpgrades(unittest.TestCase):
    """Verify backward-compatible schema upgrades for legacy DBs."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_upgrade_adds_missing_test_execution_title_column(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            # Simulate a legacy execution table before the title column existed.
            connection.execute(text(
                """
                CREATE TABLE test_execution (
                    id INTEGER PRIMARY KEY,
                    test_plan_id INTEGER NOT NULL,
                    repo_name VARCHAR(255) NOT NULL,
                    branch VARCHAR(255) NOT NULL,
                    tester_name VARCHAR(255) NOT NULL,
                    iteration INTEGER NOT NULL DEFAULT 1,
                    is_finished BOOLEAN NOT NULL DEFAULT 0,
                    comment TEXT NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            ))
            # Required by the upgrade path guard.
            connection.execute(text("CREATE TABLE test (id INTEGER PRIMARY KEY)"))

        _upgrade_schema(engine)

        with engine.connect() as connection:
            rows = connection.execute(text("PRAGMA table_info(test_execution)")).fetchall()
            column_names = {row[1] for row in rows}

        self.assertIn("title", column_names)

    def test_sync_uses_yaml_test_id_when_present(self):
        mock_repo = MagicMock()
        mock_repo.repo_name = "org/repo"
        mock_repo.branch = "main"
        test_yaml = {
            "suite": "Auth",
            "testset": "Login",
            "tests": [
                {
                    "id": "AUTH-LOGIN-001",
                    "title": "Valid credentials",
                    "steps": [{"step": "Login"}],
                }
            ],
        }
        mock_repo.load_all_tests.return_value = [("testbook/auth.yml", test_yaml)]

        session = self.SessionLocal()
        sync_from_source_repo(mock_repo, session)

        synced_test = session.query(Test).first()
        self.assertEqual(synced_test.stable_id, "AUTH-LOGIN-001")
        session.close()

    def test_sync_stable_id_is_preserved_across_resync(self):
        mock_repo = MagicMock()
        mock_repo.repo_name = "org/repo"
        mock_repo.branch = "main"
        v1 = {
            "suite": "Auth",
            "testset": "Login",
            "tests": [{"title": "Valid credentials", "steps": [{"step": "Login"}]}],
        }
        v2 = {
            "suite": "Auth",
            "testset": "Login",
            "tests": [{"title": "Valid credentials", "steps": [{"step": "Login with MFA"}]}],
        }

        session = self.SessionLocal()
        mock_repo.load_all_tests.return_value = [("testbook/auth.yml", v1)]
        sync_from_source_repo(mock_repo, session)
        first_id = session.query(Test).first().stable_id

        mock_repo.load_all_tests.return_value = [("testbook/auth.yml", v2)]
        sync_from_source_repo(mock_repo, session)
        second_id = session.query(Test).first().stable_id

        self.assertEqual(first_id, second_id)
        self.assertEqual(first_id, "valid-credentials")
        session.close()

    def test_sync_suite_stable_id_derived_from_name(self):
        mock_repo = MagicMock()
        mock_repo.repo_name = "org/repo"
        mock_repo.branch = "main"
        test_yaml = {
            "suite": "Authentication",
            "testset": "Login",
            "tests": [{"title": "Login", "steps": [{"step": "Go"}]}],
        }
        mock_repo.load_all_tests.return_value = [("testbook/auth.yml", test_yaml)]

        session = self.SessionLocal()
        sync_from_source_repo(mock_repo, session)

        suite = session.query(Suite).first()
        self.assertEqual(suite.stable_id, "authentication")
        testset = session.query(TestSet).first()
        self.assertEqual(testset.stable_id, "login")
        session.close()

    def test_sync_uses_yaml_suite_id_and_testset_id_when_present(self):
        mock_repo = MagicMock()
        mock_repo.repo_name = "org/repo"
        mock_repo.branch = "main"
        test_yaml = {
            "suite": "Authentication",
            "suite_id": "AUTH",
            "testset": "Login",
            "testset_id": "AUTH-LOGIN",
            "tests": [{"title": "Login", "steps": [{"step": "Go"}]}],
        }
        mock_repo.load_all_tests.return_value = [("testbook/auth.yml", test_yaml)]

        session = self.SessionLocal()
        sync_from_source_repo(mock_repo, session)

        suite = session.query(Suite).first()
        self.assertEqual(suite.stable_id, "AUTH")
        testset = session.query(TestSet).first()
        self.assertEqual(testset.stable_id, "AUTH-LOGIN")
        session.close()

    def test_sync_suite_and_testset_stable_id_preserved_across_resync(self):
        mock_repo = MagicMock()
        mock_repo.repo_name = "org/repo"
        mock_repo.branch = "main"
        v1 = {
            "suite": "Authentication",
            "testset": "Login",
            "tests": [{"title": "Login", "steps": [{"step": "Go"}]}],
        }
        v2 = {
            "suite": "Authentication",
            "testset": "Login",
            "tests": [{"title": "Login", "steps": [{"step": "Go with MFA"}]}],
        }

        session = self.SessionLocal()
        mock_repo.load_all_tests.return_value = [("testbook/auth.yml", v1)]
        sync_from_source_repo(mock_repo, session)
        suite_sid_1 = session.query(Suite).first().stable_id
        ts_sid_1 = session.query(TestSet).first().stable_id

        mock_repo.load_all_tests.return_value = [("testbook/auth.yml", v2)]
        sync_from_source_repo(mock_repo, session)
        suite_sid_2 = session.query(Suite).first().stable_id
        ts_sid_2 = session.query(TestSet).first().stable_id

        self.assertEqual(suite_sid_1, suite_sid_2)
        self.assertEqual(ts_sid_1, ts_sid_2)
        self.assertEqual(suite_sid_1, "authentication")
        self.assertEqual(ts_sid_1, "login")
        session.close()

    def test_sync_groups_files_by_suite_name(self):
        """Multiple files with the same suite name are combined into one Suite."""
        mock_repo = MagicMock()
        mock_repo.repo_name = "org/repo"
        mock_repo.branch = "main"

        # Two files, same suite name, different testsets
        test_yaml_1 = {
            "suite": "Authentication",
            "testset": "Login",
            "tests": [{"title": "Valid login", "steps": [{"step": "Go to login"}]}],
        }
        test_yaml_2 = {
            "suite": "Authentication",
            "testset": "Logout",
            "tests": [{"title": "Valid logout", "steps": [{"step": "Click logout"}]}],
        }
        mock_repo.load_all_tests.return_value = [
            ("testbook/auth_login.yml", test_yaml_1),
            ("testbook/auth_logout.yml", test_yaml_2),
        ]

        session = self.SessionLocal()
        count = sync_from_source_repo(mock_repo, session)

        # Should create 1 suite (not 2)
        self.assertEqual(count, 1)

        # Verify Suite
        suites = session.query(Suite).all()
        self.assertEqual(len(suites), 1)
        self.assertEqual(suites[0].name, "Authentication")

        # Verify TestSets (both should be under the same suite)
        testsets = session.query(TestSet).all()
        self.assertEqual(len(testsets), 2)
        testset_names = {ts.name for ts in testsets}
        self.assertEqual(testset_names, {"Login", "Logout"})

        # All testsets should belong to the same suite
        for ts in testsets:
            self.assertEqual(ts.suite_id, suites[0].id)

        session.close()

    def test_sync_handles_dependencies(self):
        mock_repo = MagicMock()
        mock_repo.repo_name = "org/repo"
        mock_repo.branch = "main"

        test_yaml = {
            "suite": "Auth",
            "testset": "Recovery",
            "tests": [
                {
                    "title": "Reset password",
                    "depends": [
                        {"suite": "Auth", "testset": "Login", "test": "Valid login"}
                    ],
                    "steps": [{"step": "Reset"}],
                }
            ],
        }
        mock_repo.load_all_tests.return_value = [("testbook/recovery.yml", test_yaml)]

        session = self.SessionLocal()
        sync_from_source_repo(mock_repo, session)

        deps = session.query(TestDependency).all()
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0].dep_suite_name, "Auth")
        self.assertEqual(deps[0].dep_test_title, "Valid login")

        session.close()

    def test_sync_overwrites_existing_file(self):
        """Syncing again with different data overwrites the old data."""
        mock_repo = MagicMock()
        mock_repo.repo_name = "org/repo"
        mock_repo.branch = "main"

        test_yaml_v1 = {
            "suite": "Auth",
            "testset": "Login",
            "tests": [{"title": "Test 1", "steps": [{"step": "Step"}]}],
        }
        mock_repo.load_all_tests.return_value = [("testbook/auth.yml", test_yaml_v1)]

        session = self.SessionLocal()
        sync_from_source_repo(mock_repo, session)

        tests_before = session.query(Test).all()
        self.assertEqual(len(tests_before), 1)
        self.assertEqual(tests_before[0].title, "Test 1")

        # Sync again with different data
        test_yaml_v2 = {
            "suite": "Auth",
            "testset": "Login",
            "tests": [
                {"title": "Test A", "steps": [{"step": "Step"}]},
                {"title": "Test B", "steps": [{"step": "Step"}]},
            ],
        }
        mock_repo.load_all_tests.return_value = [("testbook/auth.yml", test_yaml_v2)]
        sync_from_source_repo(mock_repo, session)

        tests_after = session.query(Test).all()
        self.assertEqual(len(tests_after), 2)
        titles = {t.title for t in tests_after}
        self.assertEqual(titles, {"Test A", "Test B"})

        session.close()

    def test_sync_handles_non_string_results(self):
        """Defensive parsing: handle results that aren't strings."""
        mock_repo = MagicMock()
        mock_repo.repo_name = "org/repo"
        mock_repo.branch = "main"

        test_yaml = {
            "suite": "Auth",
            "testset": "Login",
            "tests": [
                {
                    "title": "Mixed results",
                    "steps": [
                        {
                            "step": "Do something",
                            # Results can be strings, but user might have dicts or other types
                            "results": [
                                "String result",
                                {"text": "Dict result"},  # Defensive handling
                            ],
                        }
                    ],
                }
            ],
        }
        mock_repo.load_all_tests.return_value = [("testbook/test.yml", test_yaml)]

        session = self.SessionLocal()
        # Should not raise an error despite mixed result types
        sync_from_source_repo(mock_repo, session)

        results = session.query(Result).all()
        self.assertEqual(len(results), 2)
        # Both should be stored as strings
        self.assertEqual(results[0].text, "String result")
        self.assertEqual(results[1].text, "Dict result")

        session.close()


if __name__ == "__main__":
    unittest.main()

