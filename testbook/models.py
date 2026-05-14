"""
SQLAlchemy ORM models for testbook — representing tests, suites, and testsets.

The data model mirrors the YAML test definition structure:
  - A file contains one `Suite` (suite name) and one `TestSet`
  - A `TestSet` contains many `Test`s
  - A `Test` contains many `Step`s
  - A `Step` contains many `Result`s
  - A `Test` may have dependencies on other `Test`s

Each is cached in a SQLite database, keyed by (repo_name, branch, file_path)
so that syncing updates any changed definitions without losing local records.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, relationship

if TYPE_CHECKING:
    from typing_extensions import Annotated

# Create the declarative base for all models.
Base = declarative_base()


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------

class Suite(Base):
    """Represents a test suite — a top-level grouping of testsets.

    Attributes
    ----------
    id : int
        Primary key.
    stable_id : str
        The suite stable ID (e.g., "Authentication", "Checkout Flow").
    name : str
        The suite name (e.g., "Authentication", "Checkout Flow").
    repo_name : str
        GitHub repo in "owner/repo" format.
    branch : str
        Branch name in the repo (e.g., "main", "develop").
    file_path : str
        The repo-relative path to the YAML file that defined this suite.
    """

    __tablename__ = "suite"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True)
    stable_id = Column(String(255), nullable=False, default="", index=True)
    name = Column(String(255), nullable=False)
    repo_name = Column(String(255), nullable=False)
    branch = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)

    testsets = relationship("TestSet", back_populates="suite", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Suite {self.name!r} from {self.repo_name}:{self.branch}/{self.file_path}>"


class BranchSyncState(Base):
    """Tracks the most recent successful sync time for a repo/branch pair."""

    __tablename__ = "branch_sync_state"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True)
    repo_name = Column(String(255), nullable=False, index=True)
    branch = Column(String(255), nullable=False, index=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<BranchSyncState {self.repo_name}:{self.branch} @ {self.last_synced_at}>"


class TestSet(Base):
    """Represents a testset — an ordered collection of tests within a suite.

    Attributes
    ----------
    id : int
        Primary key.
    stable_id : str
        The testset stable ID (e.g., "Login", "Account Recovery").
    name : str
        The testset name (e.g., "Login", "Account Recovery").
    suite_id : int
        Foreign key to the parent `Suite`.
    order_index : int
        Order within the suite (for consistent ordering across syncs).
    """

    __tablename__ = "testset"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True)
    stable_id = Column(String(255), nullable=False, default="", index=True)
    name = Column(String(255), nullable=False)
    suite_id = Column(Integer, ForeignKey("suite.id"), nullable=False)
    order_index = Column(Integer, default=0)

    suite = relationship("Suite", back_populates="testsets")
    tests = relationship("Test", back_populates="testset", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<TestSet {self.name!r} in {self.suite.name!r}>"


class Test(Base):
    """Represents a single test — a named sequence of steps.

    Attributes
    ----------
    id : int
        Primary key.
    title : str
        The test title (e.g., "Valid credentials").
    testset_id : int
        Foreign key to the parent `TestSet`.
    context : dict
        User-visible context (arbitrary key-value pairs).
    order_index : int
        Order within the testset.
    """

    __tablename__ = "test"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True)
    stable_id = Column(String(255), nullable=False, default="", index=True)
    title = Column(String(255), nullable=False)
    testset_id = Column(Integer, ForeignKey("testset.id"), nullable=False)
    file_path = Column(String(512), nullable=False, default="")
    context = Column(JSON, default={})
    order_index = Column(Integer, default=0)

    testset = relationship("TestSet", back_populates="tests")
    steps = relationship("Step", back_populates="test", cascade="all, delete-orphan")
    setup_items = relationship("SetupItem", back_populates="test", cascade="all, delete-orphan")
    dependencies = relationship(
        "TestDependency",
        back_populates="dependent_test",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Test {self.title!r} in {self.testset.name!r}>"


class SetupItem(Base):
    """Represents a single setup instruction for a test.

    Attributes
    ----------
    id : int
        Primary key.
    test_id : int
        Foreign key to the parent `Test`.
    text : str
        The setup instruction text.
    order_index : int
        Order of this setup item within the test.
    """

    __tablename__ = "setup_item"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True)
    test_id = Column(Integer, ForeignKey("test.id"), nullable=False)
    text = Column(Text, nullable=False)
    order_index = Column(Integer, default=0)

    test = relationship("Test", back_populates="setup_items")

    def __repr__(self) -> str:
        return f"<SetupItem {self.order_index} of {self.test.title!r}>"


class Step(Base):
    """Represents a single step within a test.

    Attributes
    ----------
    id : int
        Primary key.
    test_id : int
        Foreign key to the parent `Test`.
    text : str
        The step instruction text.
    path : str | None
        Optional application path relative to the app base URL.
    resource : str | None
        Optional path to a test resource.
    order_index : int
        Order of this step within the test.
    """

    __tablename__ = "step"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True)
    test_id = Column(Integer, ForeignKey("test.id"), nullable=False)
    text = Column(Text, nullable=False)
    path = Column(String(512), nullable=True)
    resource = Column(String(512), nullable=True)
    order_index = Column(Integer, default=0)

    test = relationship("Test", back_populates="steps")
    results = relationship("Result", back_populates="step", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Step {self.order_index} of {self.test.title!r}>"


class Result(Base):
    """Represents a single result/assertion for a step.

    Attributes
    ----------
    id : int
        Primary key.
    step_id : int
        Foreign key to the parent `Step`.
    text : str
        The result/assertion text.
    order_index : int
        Order of this result within the step.
    """

    __tablename__ = "result"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True)
    step_id = Column(Integer, ForeignKey("step.id"), nullable=False)
    text = Column(Text, nullable=False)
    order_index = Column(Integer, default=0)

    step = relationship("Step", back_populates="results")

    def __repr__(self) -> str:
        return f"<Result {self.order_index} of step {self.step.order_index}>"


class TestDependency(Base):
    """Represents a dependency between tests.

    When Test A depends on Test B, there is a row with
    dependent_test_id → A, and the dependent_suite/testset/test specify B.

    Attributes
    ----------
    id : int
        Primary key.
    dependent_test_id : int
        Foreign key to the Test that depends on another.
    dep_suite_name : str
        Name of the suite that contains the dependency.
    dep_testset_name : str
        Name of the testset that contains the dependency.
    dep_test_title : str | None
        Name of the test that is depended on, or None if depending on entire testset.
    """

    __tablename__ = "test_dependency"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True)
    dependent_test_id = Column(Integer, ForeignKey("test.id"), nullable=False)
    dep_suite_name = Column(String(255), nullable=False)
    dep_testset_name = Column(String(255), nullable=False)
    dep_test_title = Column(String(255), nullable=True)

    dependent_test = relationship("Test", back_populates="dependencies")

    def __repr__(self) -> str:
        dep_str = f"{self.dep_suite_name}/{self.dep_testset_name}"
        if self.dep_test_title:
            dep_str += f"/{self.dep_test_title}"
        return f"<TestDependency {self.dependent_test.title!r} → {dep_str}>"


# ---------------------------------------------------------------------------
# Test Plan models
# ---------------------------------------------------------------------------


class TestPlan(Base):
	"""Represents a test plan — a named list of tests to run for a feature.

	A test plan belongs to a specific repo and branch, and contains an ordered
	list of tests selected from any suite/testset available on that branch.

	Attributes
	----------
	id : int
		Primary key.
	title : str
		The name of the test plan (e.g., "Login Feature Tests").
	repo_name : str
		GitHub repo in "owner/repo" format.
	branch : str
		Branch name in the repo (e.g., "main", "develop").
	created_at : DateTime
		When the plan was created.
	updated_at : DateTime
		When the plan was last modified.
	"""

	__tablename__ = "test_plan"
	__allow_unmapped__ = True

	id = Column(Integer, primary_key=True)
	title = Column(String(255), nullable=False)
	repo_name = Column(String(255), nullable=False, index=True)
	branch = Column(String(255), nullable=False, index=True)
	created_at = Column(DateTime(timezone=True), nullable=False)
	updated_at = Column(DateTime(timezone=True), nullable=False)

	plan_items = relationship(
		"TestPlanItem", back_populates="test_plan", cascade="all, delete-orphan"
	)

	def __repr__(self) -> str:
		return f"<TestPlan {self.title!r} on {self.repo_name}:{self.branch}>"


class TestPlanItem(Base):
	"""Represents a test included in a test plan.

	Attributes
	----------
	id : int
		Primary key.
	test_plan_id : int
		Foreign key to the parent `TestPlan`.
	test_id : int
		Foreign key to the `Test` being added to the plan.
	order_index : int
		Order of this test within the plan (for consistent ordering).
	"""

	__tablename__ = "test_plan_item"
	__allow_unmapped__ = True

	id = Column(Integer, primary_key=True)
	test_plan_id = Column(Integer, ForeignKey("test_plan.id"), nullable=False, index=True)
	test_id = Column(Integer, ForeignKey("test.id"), nullable=False, index=True)
	order_index = Column(Integer, default=0)

	test_plan = relationship("TestPlan", back_populates="plan_items")
	test = relationship("Test")

	def __repr__(self) -> str:
		return f"<TestPlanItem {self.test.title!r} in plan {self.test_plan.title!r}>"


# ---------------------------------------------------------------------------
# Test Execution models
# ---------------------------------------------------------------------------


class TestExecution(Base):
    """Represents one execution run of a test plan by a specific tester.

    The execution contains by-value snapshots of tests/steps/results so the run
    remains immutable even if source tests later change.
    """

    __tablename__ = "test_execution"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True)
    test_plan_id = Column(Integer, ForeignKey("test_plan.id"), nullable=False, index=True)
    repo_name = Column(String(255), nullable=False, index=True)
    branch = Column(String(255), nullable=False, index=True)
    tester_name = Column(String(255), nullable=False)
    iteration = Column(Integer, nullable=False, default=1)
    is_finished = Column(Boolean, nullable=False, default=False)
    comment = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    test_plan = relationship("TestPlan")
    execution_tests = relationship(
        "ExecutionTest", back_populates="execution", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<TestExecution plan={self.test_plan_id} tester={self.tester_name!r} "
            f"iter={self.iteration} finished={self.is_finished}>"
        )


class ExecutionTest(Base):
    """By-value snapshot of a test to run within an execution."""

    __tablename__ = "execution_test"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True)
    execution_id = Column(Integer, ForeignKey("test_execution.id"), nullable=False, index=True)

    # References to source test metadata for traceability (not for runtime linkage).
    source_test_id = Column(Integer, nullable=True, index=True)
    source_test_stable_id = Column(String(255), nullable=False, default="")
    source_suite_name = Column(String(255), nullable=False, default="")
    source_testset_name = Column(String(255), nullable=False, default="")

    # Snapshot fields copied by value.
    title = Column(String(255), nullable=False)
    context = Column(JSON, nullable=False, default=dict)
    setup = Column(JSON, nullable=False, default=list)
    order_index = Column(Integer, nullable=False, default=0)

    # Runtime execution state.
    status = Column(String(20), nullable=False, default="pending")  # pending|pass|fail
    comment = Column(Text, nullable=False, default="")

    execution = relationship("TestExecution", back_populates="execution_tests")
    steps = relationship("ExecutionStep", back_populates="execution_test", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ExecutionTest {self.title!r} status={self.status}>"


class ExecutionStep(Base):
    """By-value snapshot of a step within an execution test."""

    __tablename__ = "execution_step"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True)
    execution_test_id = Column(Integer, ForeignKey("execution_test.id"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    path = Column(String(512), nullable=True)
    resource = Column(String(512), nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    comment = Column(Text, nullable=False, default="")

    execution_test = relationship("ExecutionTest", back_populates="steps")
    results = relationship("ExecutionResult", back_populates="execution_step", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ExecutionStep {self.order_index} of execution_test={self.execution_test_id}>"


class ExecutionResult(Base):
    """By-value snapshot of a result/assertion and its execution outcome."""

    __tablename__ = "execution_result"
    __allow_unmapped__ = True

    id = Column(Integer, primary_key=True)
    execution_step_id = Column(Integer, ForeignKey("execution_step.id"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    order_index = Column(Integer, nullable=False, default=0)

    # Runtime execution state.
    status = Column(String(20), nullable=False, default="pending")  # pending|pass|fail
    comment = Column(Text, nullable=False, default="")

    execution_step = relationship("ExecutionStep", back_populates="results")

    def __repr__(self) -> str:
        return f"<ExecutionResult {self.order_index} status={self.status}>"


