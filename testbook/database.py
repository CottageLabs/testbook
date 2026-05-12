"""
Database setup and synchronization logic for testbook.

Provides:
  - `init_db()` — create the SQLite database and initialize the schema
  - `get_session()` — get a new session for queries/writes
  - `sync_from_source_repo()` — pull test definitions from GitHub and persist to DB
"""
from __future__ import annotations

import os
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from testbook.github_connector import SourceRepo
from testbook.models import (
    Base,
    Result,
    SetupItem,
    Step,
    Suite,
    Test,
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

    Reads all test YAML files from the source repository, parses them,
    and upserts into the database. Existing records for the same
    (repo_name, branch, file_path) are deleted first to ensure a clean sync.

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
        Number of test files successfully synced.
    """
    close_session = False
    if session is None:
        session = get_session()
        close_session = True

    try:
        count = 0
        for file_path, test_yaml in source_repo.load_all_tests():
            _sync_test_file(
                session,
                repo_name=source_repo.repo_name,
                branch=source_repo.branch,
                file_path=file_path,
                test_yaml=test_yaml,
            )
            count += 1
        session.commit()
        return count
    finally:
        if close_session:
            session.close()


def _sync_test_file(
    session: Session,
    repo_name: str,
    branch: str,
    file_path: str,
    test_yaml: dict[str, Any],
) -> None:
    """Parse and persist a single test YAML file to the database.

    If a Suite with the same (repo_name, branch, file_path) already exists,
    it and all its child records are deleted first (soft upsert).
    """
    # Delete any pre-existing records for this file.
    existing = session.query(Suite).filter_by(
        repo_name=repo_name,
        branch=branch,
        file_path=file_path,
    ).all()
    for suite in existing:
        session.delete(suite)

    suite_name = test_yaml.get("suite", "")
    testset_name = test_yaml.get("testset", "")

    # Create or fetch suite.
    suite = Suite(
        name=suite_name,
        repo_name=repo_name,
        branch=branch,
        file_path=file_path,
    )
    session.add(suite)
    session.flush()  # Ensure suite.id is populated

    # Create or fetch testset.
    testset = TestSet(
        name=testset_name,
        suite_id=suite.id,
        order_index=0,
    )
    session.add(testset)
    session.flush()

    # Parse tests and steps from the YAML.
    tests_yaml = test_yaml.get("tests", [])
    for test_idx, test_yaml_obj in enumerate(tests_yaml):
        test = Test(
            title=test_yaml_obj.get("title", ""),
            testset_id=testset.id,
            context=test_yaml_obj.get("context", {}),
            order_index=test_idx,
        )
        session.add(test)
        session.flush()

        # Parse setup items.
        for setup_idx, setup_text in enumerate(test_yaml_obj.get("setup", [])):
            setup = SetupItem(
                test_id=test.id,
                text=setup_text,
                order_index=setup_idx,
            )
            session.add(setup)

        # Parse dependencies.
        for dep in test_yaml_obj.get("depends", []):
            dep_obj = TestDependency(
                dependent_test_id=test.id,
                dep_suite_name=dep.get("suite", ""),
                dep_testset_name=dep.get("testset", ""),
                dep_test_title=dep.get("test"),
            )
            session.add(dep_obj)

        # Parse steps and results.
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

            # Parse results.
            for result_idx, result_text in enumerate(step_yaml_obj.get("results", [])):
                result = Result(
                    step_id=step.id,
                    text=result_text,
                    order_index=result_idx,
                )
                session.add(result)

