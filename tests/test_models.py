"""
Tests for testbook.models and testbook.database.

Uses an in-memory SQLite database so tests run fast and in isolation.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from testbook.database import reset_db, sync_from_source_repo
from testbook.models import Base, BranchSyncState, Result, SetupItem, Step, Suite, Test, TestDependency, TestSet


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

        sync_state = session.query(BranchSyncState).filter_by(repo_name="org/repo", branch="main").first()
        self.assertIsNotNone(sync_state)
        self.assertIsNotNone(sync_state.last_synced_at)

        # ...existing code...

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

