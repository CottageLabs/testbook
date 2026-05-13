"""
Database setup and synchronization logic for testbook.

Provides:
  - `init_db()` — create the SQLite database and initialize the schema
  - `get_session()` — get a new session for queries/writes
  - `sync_from_source_repo()` — pull test definitions from GitHub and persist to DB
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from testbook.github_connector import SourceRepo
from testbook.models import (
    Base,
    Result,
    SetupItem,
    Step,
    Suite,
    Test,
    BranchSyncState,
    TestDependency,
    TestSet,
)

# Module-level engine and session factory (lazy-initialized).
_engine: Any = None
_SessionLocal: Any = None


def _get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        db_url = os.environ.get("TESTBOOK_DB_URL", "sqlite:///testbook.db")
        _engine = create_engine(db_url, echo=False)
    return _engine


def _get_session_factory():
    """Get or create the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        engine = _get_engine()
        _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return _SessionLocal


def init_db() -> None:
    """Create the database schema and tables."""
    engine = _get_engine()
    Base.metadata.create_all(engine)
    _upgrade_schema(engine)


def _upgrade_schema(engine: Any) -> None:
    """Apply lightweight schema upgrades for existing local databases."""
    inspector = inspect(engine)
    if "test" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("test")}
    if "file_path" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE test ADD COLUMN file_path VARCHAR(512) NOT NULL DEFAULT ''"))


def get_session() -> Session:
    """Return a new SQLAlchemy session."""
    SessionLocal = _get_session_factory()
    return SessionLocal()


def reset_db() -> None:
    """Drop all tables and recreate them. Intended for testing only."""
    engine = _get_engine()
    Base.metadata.drop_all(engine)
    init_db()


# ---------------------------------------------------------------------------
# Synchronization
# ---------------------------------------------------------------------------

def sync_from_source_repo(
    source_repo: SourceRepo,
    session: Session | None = None,
) -> int:
    """Synchronize test definitions from GitHub into the local database.

    Reads all test YAML files from the source repository, groups them by suite
    and testset (matching core.py logic), and persists to the database.
    
    Files with the same `suite` value are combined into a single Suite object.

    Parameters
    ----------
    source_repo:
        A configured SourceRepo instance (token, repo_name, branch pre-set).
    session:
        An optional SQLAlchemy session. If not provided, a new one is created
        and committed before returning.

    Returns
    -------
    int
        Number of test suites successfully synced.
    """
    close_session = False
    if session is None:
        session = get_session()
        close_session = True

    try:
        # Step 1: Collect and structure all files by suite → testset
        # This matches the logic in core.py read_structure()
        suite_map = {}  # suite_name → testset_name → [(file_path, test_yaml)]
        
        for file_path, test_yaml in source_repo.load_all_tests():
            suite_name = test_yaml.get("suite", "")
            testset_name = test_yaml.get("testset", "")
            
            if suite_name not in suite_map:
                suite_map[suite_name] = {}
            if testset_name not in suite_map[suite_name]:
                suite_map[suite_name][testset_name] = []
            
            suite_map[suite_name][testset_name].append((file_path, test_yaml))
        
        # Step 2: Delete any pre-existing records for this repo/branch
        existing = session.query(Suite).filter_by(
            repo_name=source_repo.repo_name,
            branch=source_repo.branch,
        ).all()
        for suite in existing:
            session.delete(suite)
        session.flush()
        
        # Step 3: Create Suite objects, one per unique suite name
        count = 0
        for suite_name in sorted(suite_map.keys()):
            suite = Suite(
                name=suite_name,
                repo_name=source_repo.repo_name,
                branch=source_repo.branch,
                file_path="",  # Multiple files; not tracked at suite level
            )
            session.add(suite)
            session.flush()
            
            # Create TestSets and Tests for this Suite
            testset_map = suite_map[suite_name]
            for testset_idx, testset_name in enumerate(sorted(testset_map.keys())):
                testset = TestSet(
                    name=testset_name,
                    suite_id=suite.id,
                    order_index=testset_idx,
                )
                session.add(testset)
                session.flush()
                
                # Collect all tests from all files for this testset
                files_for_testset = testset_map[testset_name]
                all_tests = []
                for file_path, test_yaml_obj in files_for_testset:
                    all_tests.extend(
                        (file_path, individual_test)
                        for individual_test in test_yaml_obj.get("tests", [])
                    )

                # Create Test objects, maintaining order across files
                for test_idx, (test_file_path, test_yaml_obj) in enumerate(all_tests):
                    test = Test(
                        title=test_yaml_obj.get("title", ""),
                        testset_id=testset.id,
                        file_path=test_file_path,
                        context=test_yaml_obj.get("context", {}),
                        order_index=test_idx,
                    )
                    session.add(test)
                    session.flush()
                    
                    # Parse setup items
                    for setup_idx, setup_text in enumerate(test_yaml_obj.get("setup", [])):
                        setup = SetupItem(
                            test_id=test.id,
                            text=setup_text,
                            order_index=setup_idx,
                        )
                        session.add(setup)
                    
                    # Parse dependencies
                    for dep in test_yaml_obj.get("depends", []):
                        dep_obj = TestDependency(
                            dependent_test_id=test.id,
                            dep_suite_name=dep.get("suite", ""),
                            dep_testset_name=dep.get("testset", ""),
                            dep_test_title=dep.get("test"),
                        )
                        session.add(dep_obj)
                    
                    # Parse steps and results
                    for step_idx, step_yaml_obj in enumerate(test_yaml_obj.get("steps", [])):
                        step = Step(
                            test_id=test.id,
                            text=step_yaml_obj.get("step", ""),
                            path=step_yaml_obj.get("path"),
                            resource=step_yaml_obj.get("resource"),
                            order_index=step_idx,
                        )
                        session.add(step)
                        session.flush()
                        
                        # Parse results
                        results_list = step_yaml_obj.get("results", [])
                        for result_idx, result_item in enumerate(results_list):
                            # Defensive: handle both string results and dict results
                            if isinstance(result_item, str):
                                result_text = result_item
                            elif isinstance(result_item, dict):
                                result_text = result_item.get("text") or str(result_item)
                            else:
                                result_text = str(result_item)
                            
                            result = Result(
                                step_id=step.id,
                                text=result_text,
                                order_index=result_idx,
                            )
                            session.add(result)
            
            count += 1
        
        sync_state = (
            session.query(BranchSyncState)
            .filter_by(repo_name=source_repo.repo_name, branch=source_repo.branch)
            .first()
        )
        if sync_state is None:
            sync_state = BranchSyncState(
                repo_name=source_repo.repo_name,
                branch=source_repo.branch,
                last_synced_at=datetime.now(timezone.utc),
            )
            session.add(sync_state)
        else:
            sync_state.last_synced_at = datetime.now(timezone.utc)

        session.commit()
        return count
    finally:
        if close_session:
            session.close()

