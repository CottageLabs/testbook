"""
Database setup and synchronization logic for testbook.

Provides:
  - `init_db()` — create the SQLite database and initialize the schema
  - `get_session()` — get a new session for queries/writes
  - `sync_from_source_repo()` — pull test definitions from GitHub and persist to DB
"""
from __future__ import annotations

import os
import re
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
    TestPlan,
    TestPlanItem,
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
    existing_tables = inspector.get_table_names()

    def _add_column_if_missing(table_name: str, column_name: str, ddl: str) -> None:
        if table_name not in existing_tables:
            return
        table_columns = {c["name"] for c in inspector.get_columns(table_name)}
        if column_name in table_columns:
            return
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))

    if "test" not in existing_tables:
        return

    test_columns = {c["name"] for c in inspector.get_columns("test")}
    if "file_path" not in test_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE test ADD COLUMN file_path VARCHAR(512) NOT NULL DEFAULT ''"))
    if "stable_id" not in test_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE test ADD COLUMN stable_id VARCHAR(255) NOT NULL DEFAULT ''"))

    if "suite" in existing_tables:
        suite_columns = {c["name"] for c in inspector.get_columns("suite")}
        if "stable_id" not in suite_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE suite ADD COLUMN stable_id VARCHAR(255) NOT NULL DEFAULT ''"))

    if "testset" in existing_tables:
        testset_columns = {c["name"] for c in inspector.get_columns("testset")}
        if "stable_id" not in testset_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE testset ADD COLUMN stable_id VARCHAR(255) NOT NULL DEFAULT ''"))

    # Backward compatibility for execution schema evolution.
    # Existing local DBs may have test_execution without the later-added title column.
    _add_column_if_missing(
        "test_execution",
        "title",
        "title VARCHAR(255) NOT NULL DEFAULT 'Execution'",
    )
    _add_column_if_missing(
        "test_execution",
        "feedback_url",
        "feedback_url VARCHAR(1024) NOT NULL DEFAULT ''",
    )
    _add_column_if_missing(
        "test_execution",
        "feedback_comment_url",
        "feedback_comment_url VARCHAR(1024) NOT NULL DEFAULT ''",
    )


def _slugify_identity(value: object) -> str:
    text_value = str(value or "").strip().lower()
    if not text_value:
        return "test"
    slug = re.sub(r"[^a-z0-9]+", "-", text_value).strip("-")
    return slug or "test"


def _resolve_stable_id(explicit_id: str, name: str, used_ids: set[str], fallback_seed: str) -> str:
    """Return a stable id, using explicit_id verbatim if given, else a slug from name."""
    requested = explicit_id.strip() if explicit_id.strip() else _slugify_identity(name or fallback_seed)
    candidate = requested
    suffix = 2
    while candidate in used_ids:
        candidate = f"{requested}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _resolve_test_stable_id(raw_test: dict[str, Any], used_ids: set[str], fallback_seed: str) -> str:
    explicit_id = str(raw_test.get("id") or "").strip()
    return _resolve_stable_id(explicit_id, raw_test.get("title") or "", used_ids, fallback_seed)


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
        # suite_map: suite_name → { "suite_id": str, "testsets": { testset_name → { "testset_id": str, "files": [(path, yaml)] } } }
        suite_map: dict[str, dict] = {}

        for file_path, test_yaml in source_repo.load_all_tests():
            suite_name = test_yaml.get("suite", "")
            testset_name = test_yaml.get("testset", "")

            if suite_name not in suite_map:
                suite_map[suite_name] = {
                    "suite_id": str(test_yaml.get("suite_id") or "").strip(),
                    "testsets": {},
                }
            elif not suite_map[suite_name]["suite_id"]:
                # Accept first explicit suite_id seen for this suite name
                suite_map[suite_name]["suite_id"] = str(test_yaml.get("suite_id") or "").strip()

            testsets = suite_map[suite_name]["testsets"]
            if testset_name not in testsets:
                testsets[testset_name] = {
                    "testset_id": str(test_yaml.get("testset_id") or "").strip(),
                    "files": [],
                }
            elif not testsets[testset_name]["testset_id"]:
                testsets[testset_name]["testset_id"] = str(test_yaml.get("testset_id") or "").strip()

            testsets[testset_name]["files"].append((file_path, test_yaml))

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
        used_suite_ids: set[str] = set()
        for suite_name in sorted(suite_map.keys()):
            suite_info = suite_map[suite_name]
            suite = Suite(
                stable_id=_resolve_stable_id(suite_info["suite_id"], suite_name, used_suite_ids, f"suite-{len(used_suite_ids) + 1}"),
                name=suite_name,
                repo_name=source_repo.repo_name,
                branch=source_repo.branch,
                file_path="",  # Multiple files; not tracked at suite level
            )
            session.add(suite)
            session.flush()

            # Create TestSets and Tests for this Suite
            testsets_info = suite_info["testsets"]
            used_testset_ids: set[str] = set()
            for testset_idx, testset_name in enumerate(sorted(testsets_info.keys())):
                ts_info = testsets_info[testset_name]
                testset = TestSet(
                    stable_id=_resolve_stable_id(ts_info["testset_id"], testset_name, used_testset_ids, f"testset-{testset_idx + 1}"),
                    name=testset_name,
                    suite_id=suite.id,
                    order_index=testset_idx,
                )
                session.add(testset)
                session.flush()

                # Collect all tests from all files for this testset
                all_tests = []
                for file_path, test_yaml_obj in ts_info["files"]:
                    all_tests.extend(
                        (file_path, individual_test)
                        for individual_test in test_yaml_obj.get("tests", [])
                    )

                # Create Test objects, maintaining order across files
                used_stable_ids: set[str] = set()
                for test_idx, (test_file_path, test_yaml_obj) in enumerate(all_tests):
                    test = Test(
                        stable_id=_resolve_test_stable_id(
                            test_yaml_obj,
                            used_stable_ids,
                            f"{testset_name}-{test_idx + 1}",
                        ),
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

