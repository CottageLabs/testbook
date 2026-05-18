from flask import Flask, render_template, request, redirect, url_for, jsonify
from datetime import datetime, timezone
from sqlalchemy.orm import joinedload
from urllib.parse import quote, urlparse

from testbook.config import ConfigurationError, get_source_repo_config
from testbook.database import get_session, init_db, sync_from_source_repo
from testbook.github_connector import SourceRepo
from testbook.models import (
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
    TestPlanItem,
    TestSet,
)


def _make_source_repo(branch: str | None = None) -> SourceRepo:
    """Build a SourceRepo from the current config, optionally overriding the branch."""
    cfg = get_source_repo_config()
    return SourceRepo(
        token=cfg["github_token"],
        repo_name=cfg["repo_name"],
        tests_path=cfg["tests_path"],
        branch=branch or cfg["default_branch"],
    )


def _order_value(value: object, default: int) -> int:
    return value if isinstance(value, int) else default


def _list_value(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _text_value(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _id_value(value: object, default: str) -> str:
    if isinstance(value, (int, str)):
        return str(value)
    return default


def _int_value(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_feedback_url(value: object) -> str:
    raw = _text_value(value, "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return ""
    if not parsed.netloc:
        return ""
    return raw


def _normalize_execution_test_status(value: object) -> str:
    status = _text_value(value, "pending").strip().lower()
    return status if status in ("pending", "pass", "fail", "skipped") else "pending"


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None or not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_timestamp(dt: datetime | None) -> str | None:
    normalized = _to_utc(dt)
    return normalized.isoformat() if normalized else None


def _display_timestamp(dt: datetime | None) -> str:
    normalized = _to_utc(dt)
    if normalized is None:
        return "Never"
    return normalized.strftime("%Y-%m-%d %H:%M UTC")


def _github_file_url(repo_name: str, branch: str, repo_relative_path: str, mode: str) -> str:
    if not repo_name or not branch or not repo_relative_path:
        return ""
    if repo_relative_path.startswith(("http://", "https://")):
        return repo_relative_path
    normalized_path = repo_relative_path.lstrip("/")
    if not normalized_path:
        return ""
    return (
        f"https://github.com/{repo_name}/{mode}/"
        f"{quote(str(branch), safe='')}/"
        f"{quote(normalized_path, safe='/')}"
    )


def _build_suite_payload(
    cached_suites: list[Suite],
    resources_path: str = "",
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for suite_idx, suite in enumerate(cached_suites):
        suite_id = _id_value(getattr(suite, "id", ""), f"suite-{suite_idx + 1}")
        suite_stable_id = _text_value(getattr(suite, "stable_id", ""), "")
        suite_name = _text_value(getattr(suite, "name", ""), f"Suite {suite_idx + 1}")
        raw_testsets = _list_value(getattr(suite, "testsets", []))
        sorted_testsets = sorted(
            raw_testsets,
            key=lambda ts: _order_value(getattr(ts, "order_index", None), 0),
        )

        serialized_testsets: list[dict[str, object]] = []
        for testset_idx, testset in enumerate(sorted_testsets):
            testset_id = _id_value(getattr(testset, "id", ""), f"{suite_id}-set-{testset_idx + 1}")
            testset_stable_id = _text_value(getattr(testset, "stable_id", ""), "")
            testset_name = _text_value(getattr(testset, "name", ""), f"TestSet {testset_idx + 1}")
            raw_tests = _list_value(getattr(testset, "tests", []))
            sorted_tests = sorted(
                raw_tests,
                key=lambda test: _order_value(getattr(test, "order_index", None), 0),
            )

            serialized_tests: list[dict[str, object]] = []
            for test_idx, test in enumerate(sorted_tests):
                test_id = _id_value(getattr(test, "id", ""), f"{testset_id}-test-{test_idx + 1}")
                test_stable_id = _text_value(getattr(test, "stable_id", ""), "")
                test_title = _text_value(getattr(test, "title", ""), f"Test {test_idx + 1}")
                file_path = _text_value(getattr(test, "file_path", ""), "")
                github_edit_url = _github_file_url(
                    _text_value(getattr(suite, "repo_name", ""), ""),
                    _text_value(getattr(suite, "branch", ""), ""),
                    file_path,
                    "edit",
                )
                context = getattr(test, "context", {}) if isinstance(getattr(test, "context", {}), dict) else {}

                raw_setup_items = _list_value(getattr(test, "setup_items", []))
                setup_items = [
                    _text_value(getattr(item, "text", ""), "")
                    for item in sorted(
                        raw_setup_items,
                        key=lambda item: _order_value(getattr(item, "order_index", None), 0),
                    )
                    if _text_value(getattr(item, "text", ""), "")
                ]

                raw_steps = _list_value(getattr(test, "steps", []))
                serialized_steps: list[dict[str, object]] = []
                for step_idx, step in enumerate(
                    sorted(
                        raw_steps,
                        key=lambda s: _order_value(getattr(s, "order_index", None), 0),
                    )
                ):
                    raw_results = _list_value(getattr(step, "results", []))
                    resource_path = _text_value(getattr(step, "resource", ""), "")
                    base_resources_path = _text_value(resources_path, "").strip("/")
                    normalized_resource_path = resource_path.strip("/")
                    resource_repo_path = normalized_resource_path
                    if base_resources_path and normalized_resource_path:
                        resource_repo_path = f"{base_resources_path}/{normalized_resource_path}"
                    elif base_resources_path:
                        resource_repo_path = base_resources_path
                    results = [
                        _text_value(getattr(result, "text", ""), "")
                        for result in sorted(
                            raw_results,
                            key=lambda result: _order_value(getattr(result, "order_index", None), 0),
                        )
                        if _text_value(getattr(result, "text", ""), "")
                    ]
                    serialized_steps.append(
                        {
                            "id": _id_value(getattr(step, "id", ""), f"{test_id}-step-{step_idx + 1}"),
                            "text": _text_value(getattr(step, "text", ""), ""),
                            "path": _text_value(getattr(step, "path", ""), ""),
                            "resource": resource_path,
                            "resource_url": _github_file_url(
                                _text_value(getattr(suite, "repo_name", ""), ""),
                                _text_value(getattr(suite, "branch", ""), ""),
                                resource_repo_path,
                                "blob",
                            ),
                            "results": results,
                        }
                    )

                serialized_tests.append(
                    {
                        "id": test_id,
                        "stable_id": test_stable_id,
                        "title": test_title,
                        "file_path": file_path,
                        "github_edit_url": github_edit_url,
                        "context": context,
                        "setup": setup_items,
                        "steps": serialized_steps,
                    }
                )

            serialized_testsets.append(
                {
                    "id": testset_id,
                    "stable_id": testset_stable_id,
                    "name": testset_name,
                    "tests": serialized_tests,
                }
            )

        payload.append(
            {
                "id": suite_id,
                "stable_id": suite_stable_id,
                "name": suite_name,
                "testsets": serialized_testsets,
            }
        )

    return payload


def _filter_suite_payload_by_test_ids(
    suite_payload: list[dict[str, object]],
    test_ids: set[str],
) -> list[dict[str, object]]:
    """Return a suite payload restricted to tests whose IDs are in test_ids."""
    if not test_ids:
        return []

    filtered_suites: list[dict[str, object]] = []
    for suite in suite_payload:
        raw_testsets = _list_value(suite.get("testsets", [])) if isinstance(suite, dict) else []
        filtered_testsets: list[dict[str, object]] = []

        for testset in raw_testsets:
            if not isinstance(testset, dict):
                continue
            raw_tests = _list_value(testset.get("tests", []))
            filtered_tests = [
                test
                for test in raw_tests
                if isinstance(test, dict) and str(test.get("id", "")) in test_ids
            ]
            if filtered_tests:
                filtered_testset = dict(testset)
                filtered_testset["tests"] = filtered_tests
                filtered_testsets.append(filtered_testset)

        if filtered_testsets and isinstance(suite, dict):
            filtered_suite = dict(suite)
            filtered_suite["testsets"] = filtered_testsets
            filtered_suites.append(filtered_suite)

    return filtered_suites


def _serialize_plans(plans: list[TestPlan]) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    for plan in plans:
        raw_items = _list_value(getattr(plan, "plan_items", []))
        serialized.append(
            {
                "id": _id_value(getattr(plan, "id", ""), ""),
                "title": _text_value(getattr(plan, "title", ""), "Untitled plan"),
                "test_count": len(raw_items),
            }
        )
    return serialized


def _serialize_executions(executions: list[TestExecution]) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    for execution in executions:
        raw_tests = _list_value(getattr(execution, "execution_tests", []))
        serialized.append(
            {
                "id": _id_value(getattr(execution, "id", ""), ""),
                "title": _text_value(getattr(execution, "title", ""), "Untitled execution"),
                "tester_name": _text_value(getattr(execution, "tester_name", ""), ""),
                "iteration": _int_value(getattr(execution, "iteration", 1), 1),
                "test_count": len(raw_tests),
                "is_finished": bool(getattr(execution, "is_finished", False)),
                "feedback_url": _text_value(getattr(execution, "feedback_url", ""), ""),
            }
        )
    return serialized


def _build_execution_suite_payload(
    execution: TestExecution,
    resources_path: str = "",
) -> list[dict[str, object]]:
    """Build workbench suite payload from by-value execution snapshot rows."""
    suite_map: dict[str, dict[str, object]] = {}
    suite_order: list[str] = []

    sorted_execution_tests = sorted(
        _list_value(getattr(execution, "execution_tests", [])),
        key=lambda item: _order_value(getattr(item, "order_index", None), 0),
    )

    for execution_test in sorted_execution_tests:
        suite_name = _text_value(getattr(execution_test, "source_suite_name", ""), "Uncategorised Suite")
        testset_name = _text_value(getattr(execution_test, "source_testset_name", ""), "Uncategorised TestSet")
        suite_key = suite_name
        testset_key = f"{suite_name}::{testset_name}"

        if suite_key not in suite_map:
            suite_map[suite_key] = {
                "id": f"exec-suite-{len(suite_order) + 1}",
                "stable_id": "",
                "name": suite_name,
                "testsets": {},
                "testset_order": [],
            }
            suite_order.append(suite_key)

        suite_entry = suite_map[suite_key]
        testsets = suite_entry["testsets"]
        if isinstance(testsets, dict) and testset_key not in testsets:
            order = suite_entry["testset_order"]
            if isinstance(order, list):
                order.append(testset_key)
                testset_idx = len(order)
            else:
                testset_idx = 1
            testsets[testset_key] = {
                "id": f"exec-set-{suite_entry['id']}-{testset_idx}",
                "stable_id": "",
                "name": testset_name,
                "tests": [],
            }

        execution_steps = sorted(
            _list_value(getattr(execution_test, "steps", [])),
            key=lambda item: _order_value(getattr(item, "order_index", None), 0),
        )
        serialized_steps: list[dict[str, object]] = []
        for execution_step in execution_steps:
            step_results = sorted(
                _list_value(getattr(execution_step, "results", [])),
                key=lambda item: _order_value(getattr(item, "order_index", None), 0),
            )
            resource_path = _text_value(getattr(execution_step, "resource", ""), "")
            base_resources_path = _text_value(resources_path, "").strip("/")
            normalized_resource_path = resource_path.strip("/")
            resource_repo_path = normalized_resource_path
            if base_resources_path and normalized_resource_path:
                resource_repo_path = f"{base_resources_path}/{normalized_resource_path}"
            elif base_resources_path:
                resource_repo_path = base_resources_path
            serialized_steps.append(
                {
                    "id": _id_value(getattr(execution_step, "id", ""), ""),
                    "text": _text_value(getattr(execution_step, "text", ""), ""),
                    "path": _text_value(getattr(execution_step, "path", ""), ""),
                    "resource": resource_path,
                    "resource_url": _github_file_url(
                        _text_value(getattr(execution, "repo_name", ""), ""),
                        _text_value(getattr(execution, "branch", ""), ""),
                        resource_repo_path,
                        "blob",
                    ),
                    "comment": _text_value(getattr(execution_step, "comment", ""), ""),
                    "results": [
                        {
                            "id": _id_value(getattr(result, "id", ""), ""),
                            "text": _text_value(getattr(result, "text", ""), ""),
                            "status": _text_value(getattr(result, "status", "pending"), "pending"),
                            "comment": _text_value(getattr(result, "comment", ""), ""),
                        }
                        for result in step_results
                    ],
                }
            )

        execution_test_dict = {
            "id": _id_value(getattr(execution_test, "id", ""), ""),
            "stable_id": _text_value(getattr(execution_test, "source_test_stable_id", ""), ""),
            "title": _text_value(getattr(execution_test, "title", ""), ""),
            "file_path": "",
            "github_edit_url": "",
            "context": getattr(execution_test, "context", {}) if isinstance(getattr(execution_test, "context", {}), dict) else {},
            "setup": _list_value(getattr(execution_test, "setup", [])),
            "status": _normalize_execution_test_status(getattr(execution_test, "status", "pending")),
            "comment": _text_value(getattr(execution_test, "comment", ""), ""),
            "steps": serialized_steps,
        }
        if isinstance(testsets, dict) and testset_key in testsets:
            tests = testsets[testset_key].get("tests", [])
            if isinstance(tests, list):
                tests.append(execution_test_dict)

    payload: list[dict[str, object]] = []
    for suite_key in suite_order:
        suite_entry = suite_map[suite_key]
        ordered_testsets: list[dict[str, object]] = []
        testsets = suite_entry.get("testsets", {})
        for testset_key in suite_entry.get("testset_order", []):
            if isinstance(testsets, dict) and testset_key in testsets:
                ordered_testsets.append(testsets[testset_key])
        payload.append(
            {
                "id": suite_entry["id"],
                "stable_id": suite_entry["stable_id"],
                "name": suite_entry["name"],
                "testsets": ordered_testsets,
            }
        )
    return payload


def _create_execution_from_plan(
    session,
    *,
    plan: TestPlan,
    title: str,
    tester_name: str,
    repo_name: str,
    branch: str,
    feedback_url: str = "",
) -> TestExecution:
    """Create an execution and snapshot all tests in the plan by value."""
    existing_iteration = (
        session.query(TestExecution)
        .filter_by(test_plan_id=plan.id, tester_name=tester_name)
        .order_by(TestExecution.iteration.desc(), TestExecution.id.desc())
        .first()
    )
    next_iteration = (_int_value(getattr(existing_iteration, "iteration", 0), 0) + 1) if existing_iteration else 1

    now = datetime.now(timezone.utc)
    execution = TestExecution(
        test_plan_id=plan.id,
        title=title,
        repo_name=repo_name,
        branch=branch,
        tester_name=tester_name,
        iteration=next_iteration,
        is_finished=False,
        feedback_url=_normalize_feedback_url(feedback_url),
        created_at=now,
        updated_at=now,
    )
    session.add(execution)
    session.flush()

    sorted_items = sorted(
        _list_value(getattr(plan, "plan_items", [])),
        key=lambda item: _order_value(getattr(item, "order_index", None), 0),
    )

    for item_idx, item in enumerate(sorted_items):
        source_test = getattr(item, "test", None)
        if source_test is None:
            continue
        source_testset = getattr(source_test, "testset", None)
        source_suite = getattr(source_testset, "suite", None) if source_testset else None

        execution_test = ExecutionTest(
            execution_id=execution.id,
            source_test_id=_int_value(getattr(source_test, "id", None), None),
            source_test_stable_id=_text_value(getattr(source_test, "stable_id", ""), ""),
            source_suite_name=_text_value(getattr(source_suite, "name", ""), ""),
            source_testset_name=_text_value(getattr(source_testset, "name", ""), ""),
            title=_text_value(getattr(source_test, "title", ""), f"Test {item_idx + 1}"),
            context=getattr(source_test, "context", {}) if isinstance(getattr(source_test, "context", {}), dict) else {},
            setup=[
                _text_value(getattr(setup_item, "text", ""), "")
                for setup_item in sorted(
                    _list_value(getattr(source_test, "setup_items", [])),
                    key=lambda setup_item: _order_value(getattr(setup_item, "order_index", None), 0),
                )
                if _text_value(getattr(setup_item, "text", ""), "")
            ],
            order_index=item_idx,
            status="pending",
            comment="",
        )
        session.add(execution_test)
        session.flush()

        source_steps = sorted(
            _list_value(getattr(source_test, "steps", [])),
            key=lambda step: _order_value(getattr(step, "order_index", None), 0),
        )
        for step_idx, source_step in enumerate(source_steps):
            execution_step = ExecutionStep(
                execution_test_id=execution_test.id,
                text=_text_value(getattr(source_step, "text", ""), ""),
                path=_text_value(getattr(source_step, "path", ""), "") or None,
                resource=_text_value(getattr(source_step, "resource", ""), "") or None,
                order_index=step_idx,
                comment="",
            )
            session.add(execution_step)
            session.flush()

            source_results = sorted(
                _list_value(getattr(source_step, "results", [])),
                key=lambda result: _order_value(getattr(result, "order_index", None), 0),
            )
            for result_idx, source_result in enumerate(source_results):
                execution_result = ExecutionResult(
                    execution_step_id=execution_step.id,
                    text=_text_value(getattr(source_result, "text", ""), ""),
                    order_index=result_idx,
                    status="pending",
                    comment="",
                )
                session.add(execution_result)

    return execution


def _default_render_context() -> dict[str, object]:
    return {
        "error": None,
        "repo_name": None,
        "branches": [],
        "selected_branch": None,
        "suite_payload": [],
        "show_sync_button": False,
        "need_sync": False,
        "default_base_url": "http://localhost:5004/",
        "freshness_check_interval_seconds": 1800,
        "last_synced_at_iso": None,
        "last_synced_display": "Never",
        "active_nav": "suites",
        "branch_form_action": "/",
        "return_view": "suites",
        "available_plans": [],
        "plans": [],
        "selected_plan_id": None,
        "selected_plan_title": "",
        "active_plan_id": "",
        "active_plan_title": "",
        "plan_test_ids": [],
        "available_executions": [],
        "executions": [],
        "selected_execution_id": "",
        "selected_execution_title": "",
        "selected_execution_feedback_url": "",
        "show_execution_statuses": False,
    }


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Initialize database schema on startup (unless testing).
    with app.app_context():
        if not app.config.get("TESTING"):
            init_db()

    @app.get("/")
    def index() -> str:
        try:
            cfg = get_source_repo_config()
            default_branch = cfg["default_branch"]
            selected_branch = request.args.get("branch", default_branch)
            interval_seconds = max(60, _int_value(cfg.get("freshness_check_interval_seconds", 1800), 1800))
            active_plan_id_raw = request.args.get("plan_id", "").strip()

            session = get_session()
            # Eagerly load nested relationships so they're available after session closes
            cached_suites = (
                session.query(Suite)
                .options(
                    joinedload(Suite.testsets)
                    .joinedload(TestSet.tests)
                    .joinedload(Test.steps)
                    .joinedload(Step.results),
                    joinedload(Suite.testsets)
                    .joinedload(TestSet.tests)
                    .joinedload(Test.setup_items),
                    joinedload(Suite.testsets)
                    .joinedload(TestSet.tests)
                    .joinedload(Test.dependencies),
                )
                .filter_by(
                    repo_name=cfg["repo_name"],
                    branch=selected_branch,
                )
                .all()
            )
            sync_state = (
                session.query(BranchSyncState)
                .filter_by(repo_name=cfg["repo_name"], branch=selected_branch)
                .first()
            )

            # Resolve active plan
            active_plan_title = ""
            plan_test_ids: list[str] = []
            if active_plan_id_raw:
                try:
                    plan_id_int = int(active_plan_id_raw)
                    active_plan = session.query(TestPlan).filter_by(id=plan_id_int).first()
                    if active_plan:
                        active_plan_title = _text_value(getattr(active_plan, "title", ""), "")
                        items = (
                            session.query(TestPlanItem)
                            .filter_by(test_plan_id=plan_id_int)
                            .all()
                        )
                        plan_test_ids = [str(item.test_id) for item in items]
                except (ValueError, TypeError):
                    active_plan_id_raw = ""

            last_synced_at = _to_utc(getattr(sync_state, "last_synced_at", None))

            # Load available plans for this branch
            available_plans = (
                session.query(TestPlan)
                .filter_by(repo_name=cfg["repo_name"], branch=selected_branch)
                .order_by(TestPlan.updated_at.desc(), TestPlan.id.asc())
                .all()
            )

            session.close()

            branches = _make_source_repo(selected_branch).list_branches()
            suite_payload = _build_suite_payload(
                cached_suites,
                _text_value(cfg.get("resources_path", ""), ""),
            )

            if cached_suites:
                # Display cached data
                return render_template(
                    "index.html",
                    repo_name=cfg["repo_name"],
                    branches=branches,
                    selected_branch=selected_branch,
                    suites=cached_suites,
                    suite_payload=suite_payload,
                    available_plans=available_plans,
                    error=None,
                    show_sync_button=True,
                    default_base_url=cfg.get("default_base_url", "http://localhost:5004/"),
                    freshness_check_interval_seconds=interval_seconds,
                    last_synced_at_iso=_iso_timestamp(last_synced_at),
                    last_synced_display=_display_timestamp(last_synced_at),
                    active_nav="suites",
                    branch_form_action="/",
                    return_view="suites",
                    active_plan_id=active_plan_id_raw,
                    active_plan_title=active_plan_title,
                    plan_test_ids=plan_test_ids,
                )
            else:
                # No cached data; show sync button
                return render_template(
                    "index.html",
                    repo_name=cfg["repo_name"],
                    branches=branches,
                    selected_branch=selected_branch,
                    suites=[],
                    suite_payload=[],
                    available_plans=available_plans,
                    error=None,
                    show_sync_button=True,
                    need_sync=True,
                    default_base_url=cfg.get("default_base_url", "http://localhost:5004/"),
                    freshness_check_interval_seconds=interval_seconds,
                    last_synced_at_iso=_iso_timestamp(last_synced_at),
                    last_synced_display=_display_timestamp(last_synced_at),
                    active_nav="suites",
                    branch_form_action="/",
                    return_view="suites",
                    active_plan_id=active_plan_id_raw,
                    active_plan_title=active_plan_title,
                    plan_test_ids=plan_test_ids,
                )

        except ConfigurationError as exc:
            context = _default_render_context()
            context.update({"error": str(exc), "active_nav": "suites"})
            return render_template("index.html", **context)
        except Exception as exc:
            context = _default_render_context()
            context.update({"error": f"GitHub error: {exc}", "active_nav": "suites"})
            return render_template("index.html", **context)

    @app.get("/plans")
    def plans_index() -> str:
        try:
            cfg = get_source_repo_config()
            default_branch = cfg["default_branch"]
            selected_branch = request.args.get("branch", default_branch)
            interval_seconds = max(60, _int_value(cfg.get("freshness_check_interval_seconds", 1800), 1800))

            selected_plan_id_raw = request.args.get("plan_id", "")

            session = get_session()
            cached_suites = (
                session.query(Suite)
                .options(
                    joinedload(Suite.testsets)
                    .joinedload(TestSet.tests)
                    .joinedload(Test.steps)
                    .joinedload(Step.results),
                    joinedload(Suite.testsets)
                    .joinedload(TestSet.tests)
                    .joinedload(Test.setup_items),
                    joinedload(Suite.testsets)
                    .joinedload(TestSet.tests)
                    .joinedload(Test.dependencies),
                )
                .filter_by(
                    repo_name=cfg["repo_name"],
                    branch=selected_branch,
                )
                .all()
            )
            sync_state = (
                session.query(BranchSyncState)
                .filter_by(repo_name=cfg["repo_name"], branch=selected_branch)
                .first()
            )
            plans = (
                session.query(TestPlan)
                .options(
                    joinedload(TestPlan.plan_items).joinedload(TestPlanItem.test),
                )
                .filter_by(repo_name=cfg["repo_name"], branch=selected_branch)
                .order_by(TestPlan.updated_at.desc(), TestPlan.id.asc())
                .all()
            )
            session.close()

            selected_plan: TestPlan | None = None
            if selected_plan_id_raw:
                selected_plan = next(
                    (plan for plan in plans if str(getattr(plan, "id", "")) == selected_plan_id_raw),
                    None,
                )

            suite_payload = _build_suite_payload(
                cached_suites,
                _text_value(cfg.get("resources_path", ""), ""),
            )
            plan_test_ids = set()
            if selected_plan is not None:
                sorted_items = sorted(
                    _list_value(getattr(selected_plan, "plan_items", [])),
                    key=lambda item: _order_value(getattr(item, "order_index", None), 0),
                )
                plan_test_ids = {
                    _id_value(getattr(item, "test_id", ""), "")
                    for item in sorted_items
                    if _id_value(getattr(item, "test_id", ""), "")
                }
            filtered_payload = _filter_suite_payload_by_test_ids(suite_payload, plan_test_ids)

            branches = _make_source_repo(selected_branch).list_branches()
            last_synced_at = _to_utc(getattr(sync_state, "last_synced_at", None))

            return render_template(
                "plans.html",
                error=None,
                repo_name=cfg["repo_name"],
                branches=branches,
                selected_branch=selected_branch,
                suite_payload=filtered_payload,
                available_plans=plans,
                plans=_serialize_plans(plans),
                selected_plan_id=_id_value(getattr(selected_plan, "id", ""), "") if selected_plan else "",
                selected_plan_title=_text_value(getattr(selected_plan, "title", ""), ""),
                active_plan_id=_id_value(getattr(selected_plan, "id", ""), "") if selected_plan else "",
                active_plan_title=_text_value(getattr(selected_plan, "title", ""), ""),
                plan_test_ids=list(plan_test_ids),
                show_sync_button=True,
                need_sync=not cached_suites,
                default_base_url=cfg.get("default_base_url", "http://localhost:5004/"),
                freshness_check_interval_seconds=interval_seconds,
                last_synced_at_iso=_iso_timestamp(last_synced_at),
                last_synced_display=_display_timestamp(last_synced_at),
                active_nav="plans",
                branch_form_action="/plans",
                return_view="plans",
            )
        except ConfigurationError as exc:
            context = _default_render_context()
            context.update(
                {
                    "error": str(exc),
                    "active_nav": "plans",
                    "branch_form_action": "/plans",
                    "return_view": "plans",
                    "selected_plan_id": "",
                    "selected_plan_title": "",
                    "active_plan_id": "",
                    "active_plan_title": "",
                }
            )
            return render_template("plans.html", **context)
        except Exception as exc:
            context = _default_render_context()
            context.update(
                {
                    "error": f"GitHub error: {exc}",
                    "active_nav": "plans",
                    "branch_form_action": "/plans",
                    "return_view": "plans",
                    "selected_plan_id": "",
                    "selected_plan_title": "",
                    "active_plan_id": "",
                    "active_plan_title": "",
                }
            )
            return render_template("plans.html", **context)

    @app.post("/plans/add")
    def add_plan() -> str:
        try:
            cfg = get_source_repo_config()
            selected_branch = request.form.get("branch", cfg["default_branch"])
            title = request.form.get("title", "").strip()
            session = get_session()
            if not title:
                existing_count = (
                    session.query(TestPlan)
                    .filter_by(repo_name=cfg["repo_name"], branch=selected_branch)
                    .count()
                )
                title = f"New Plan {existing_count + 1}"
            now = datetime.now(timezone.utc)
            plan = TestPlan(
                title=title,
                repo_name=cfg["repo_name"],
                branch=selected_branch,
                created_at=now,
                updated_at=now,
            )
            session.add(plan)
            session.commit()
            plan_id = str(plan.id)
            session.close()
            return redirect(url_for("plans_index", branch=selected_branch, plan_id=plan_id))
        except Exception:
            return redirect(url_for("plans_index"))

    @app.patch("/api/plan/<int:plan_id>")
    def update_plan(plan_id: int):
        """Rename a plan. Accepts JSON {title: "..."}. Returns updated plan."""
        session = get_session()
        try:
            cfg = get_source_repo_config()
            data = request.get_json(force=True) or {}
            title = str(data.get("title", "")).strip()
            if not title:
                return jsonify({"error": "Title is required"}), 400
            plan = session.query(TestPlan).filter_by(id=plan_id, repo_name=cfg["repo_name"]).first()
            if plan is None:
                return jsonify({"error": "Plan not found"}), 404
            plan.title = title
            plan.updated_at = datetime.now(timezone.utc)
            session.commit()
            return jsonify({"id": plan.id, "title": plan.title})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            session.close()

    @app.get("/executions")
    def executions_index() -> str:
        try:
            cfg = get_source_repo_config()
            default_branch = cfg["default_branch"]
            selected_branch = request.args.get("branch", default_branch)
            interval_seconds = max(60, _int_value(cfg.get("freshness_check_interval_seconds", 1800), 1800))
            selected_plan_id_raw = request.args.get("plan_id", "").strip()
            selected_execution_id_raw = request.args.get("execution_id", "").strip()

            session = get_session()
            sync_state = (
                session.query(BranchSyncState)
                .filter_by(repo_name=cfg["repo_name"], branch=selected_branch)
                .first()
            )

            plans = (
                session.query(TestPlan)
                .options(joinedload(TestPlan.plan_items).joinedload(TestPlanItem.test))
                .filter_by(repo_name=cfg["repo_name"], branch=selected_branch)
                .order_by(TestPlan.updated_at.desc(), TestPlan.id.asc())
                .all()
            )

            selected_plan: TestPlan | None = None
            if selected_plan_id_raw:
                selected_plan = next(
                    (plan for plan in plans if str(getattr(plan, "id", "")) == selected_plan_id_raw),
                    None,
                )

            executions = (
                session.query(TestExecution)
                .options(
                    joinedload(TestExecution.execution_tests)
                    .joinedload(ExecutionTest.steps)
                    .joinedload(ExecutionStep.results)
                )
                .filter_by(repo_name=cfg["repo_name"], branch=selected_branch)
                .order_by(TestExecution.updated_at.desc(), TestExecution.id.desc())
                .all()
            )

            selected_execution: TestExecution | None = None
            if selected_execution_id_raw:
                selected_execution = next(
                    (
                        execution
                        for execution in executions
                        if str(getattr(execution, "id", "")) == selected_execution_id_raw
                    ),
                    None,
                )

            if selected_execution is not None and selected_plan is None:
                selected_plan = next(
                    (
                        plan
                        for plan in plans
                        if str(getattr(plan, "id", ""))
                        == _id_value(getattr(selected_execution, "test_plan_id", ""), "")
                    ),
                    None,
                )

            filtered_payload: list[dict[str, object]] = []
            if selected_execution is not None:
                filtered_payload = _build_execution_suite_payload(
                    selected_execution,
                    _text_value(cfg.get("resources_path", ""), ""),
                )

            branches = _make_source_repo(selected_branch).list_branches()
            last_synced_at = _to_utc(getattr(sync_state, "last_synced_at", None))

            return render_template(
                "executions.html",
                error=None,
                repo_name=cfg["repo_name"],
                branches=branches,
                selected_branch=selected_branch,
                suite_payload=filtered_payload,
                available_plans=plans,
                plans=_serialize_plans(plans),
                available_executions=executions,
                executions=_serialize_executions(executions),
                selected_execution_id=_id_value(getattr(selected_execution, "id", ""), "") if selected_execution else "",
                selected_execution_title=_text_value(getattr(selected_execution, "title", ""), ""),
                selected_execution_feedback_url=_text_value(getattr(selected_execution, "feedback_url", ""), ""),
                selected_plan_id=_id_value(getattr(selected_plan, "id", ""), "") if selected_plan else "",
                selected_plan_title=_text_value(getattr(selected_plan, "title", ""), ""),
                active_plan_id=_id_value(getattr(selected_plan, "id", ""), "") if selected_plan else "",
                active_plan_title=_text_value(getattr(selected_plan, "title", ""), ""),
                plan_test_ids=[],
                show_plan_buttons=False,
                show_execution_statuses=True,
                show_sync_button=True,
                need_sync=False,
                default_base_url=cfg.get("default_base_url", "http://localhost:5004/"),
                freshness_check_interval_seconds=interval_seconds,
                last_synced_at_iso=_iso_timestamp(last_synced_at),
                last_synced_display=_display_timestamp(last_synced_at),
                active_nav="executions",
                branch_form_action="/executions",
                return_view="executions",
            )
        except ConfigurationError as exc:
            context = _default_render_context()
            context.update(
                {
                    "error": str(exc),
                    "active_nav": "executions",
                    "branch_form_action": "/executions",
                    "return_view": "executions",
                }
            )
            return render_template("executions.html", **context)
        except Exception as exc:
            context = _default_render_context()
            context.update(
                {
                    "error": f"GitHub error: {exc}",
                    "active_nav": "executions",
                    "branch_form_action": "/executions",
                    "return_view": "executions",
                }
            )
            return render_template("executions.html", **context)

    @app.post("/executions/add")
    def add_execution() -> str:
        try:
            cfg = get_source_repo_config()
            selected_branch = request.form.get("branch", cfg["default_branch"])
            plan_id_raw = request.form.get("plan_id", "").strip()
            title = request.form.get("title", "").strip()
            feedback_url = _normalize_feedback_url(request.form.get("feedback_url", ""))
            if not plan_id_raw:
                return redirect(url_for("executions_index", branch=selected_branch))
            plan_id_int = int(plan_id_raw)

            session = get_session()
            plan = (
                session.query(TestPlan)
                .options(
                    joinedload(TestPlan.plan_items)
                    .joinedload(TestPlanItem.test)
                    .joinedload(Test.testset)
                    .joinedload(TestSet.suite),
                    joinedload(TestPlan.plan_items)
                    .joinedload(TestPlanItem.test)
                    .joinedload(Test.steps)
                    .joinedload(Step.results),
                    joinedload(TestPlan.plan_items)
                    .joinedload(TestPlanItem.test)
                    .joinedload(Test.setup_items),
                )
                .filter_by(id=plan_id_int, repo_name=cfg["repo_name"], branch=selected_branch)
                .first()
            )
            if plan is None:
                session.close()
                return redirect(url_for("executions_index", branch=selected_branch, plan_id=plan_id_raw))

            if not title:
                count = (
                    session.query(TestExecution)
                    .filter_by(repo_name=cfg["repo_name"], branch=selected_branch)
                    .count()
                )
                title = f"Execution {count + 1}"

            execution = _create_execution_from_plan(
                session,
                plan=plan,
                title=title,
                tester_name="Unassigned",
                repo_name=cfg["repo_name"],
                branch=selected_branch,
                feedback_url=feedback_url,
            )
            execution.updated_at = datetime.now(timezone.utc)
            session.commit()
            execution_id = str(execution.id)
            session.close()
            return redirect(
                url_for(
                    "executions_index",
                    branch=selected_branch,
                    plan_id=plan_id_raw,
                    execution_id=execution_id,
                )
            )
        except Exception:
            return redirect(url_for("executions_index"))

    @app.patch("/api/execution/<int:execution_id>")
    def update_execution(execution_id: int):
        session = get_session()
        try:
            cfg = get_source_repo_config()
            data = request.get_json(force=True) or {}
            title = str(data.get("title", "")).strip()
            feedback_url = _normalize_feedback_url(data.get("feedback_url", "")) if "feedback_url" in data else None
            if not title:
                return jsonify({"error": "Title is required"}), 400

            execution = (
                session.query(TestExecution)
                .filter_by(id=execution_id, repo_name=cfg["repo_name"])
                .first()
            )
            if execution is None:
                return jsonify({"error": "Execution not found"}), 404

            execution.title = title
            if feedback_url is not None:
                execution.feedback_url = feedback_url
            execution.updated_at = datetime.now(timezone.utc)
            session.commit()
            return jsonify({"id": execution.id, "title": execution.title, "feedback_url": execution.feedback_url})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            session.close()

    @app.get("/api/default-base-url")
    def get_default_base_url() -> dict:
        """Return the configured default base URL for the application being tested."""
        try:
            cfg = get_source_repo_config()
            return jsonify({"default_base_url": cfg.get("default_base_url", "http://localhost:5004/")})
        except Exception:
            return jsonify({"default_base_url": "http://localhost:5004/"})

    @app.get("/api/branch-freshness")
    def get_branch_freshness() -> tuple[dict, int] | dict:
        """Return branch freshness info by comparing last sync with latest remote test change."""
        try:
            cfg = get_source_repo_config()
            branch = request.args.get("branch", cfg["default_branch"])

            session = get_session()
            sync_state = (
                session.query(BranchSyncState)
                .filter_by(repo_name=cfg["repo_name"], branch=branch)
                .first()
            )
            session.close()

            last_synced_at = _to_utc(getattr(sync_state, "last_synced_at", None))
            remote_updated_at = _to_utc(_make_source_repo(branch).latest_tests_commit_timestamp())

            if last_synced_at is None:
                is_stale = remote_updated_at is not None
            elif remote_updated_at is None:
                is_stale = False
            else:
                is_stale = remote_updated_at > last_synced_at

            return jsonify(
                {
                    "branch": branch,
                    "is_stale": is_stale,
                    "last_synced_at": _iso_timestamp(last_synced_at),
                    "last_synced_display": _display_timestamp(last_synced_at),
                    "remote_updated_at": _iso_timestamp(remote_updated_at),
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.post("/sync")
    def sync() -> str:
        try:
            cfg = get_source_repo_config()
            selected_branch = request.form.get("branch", cfg["default_branch"])
            return_view = request.form.get("return_view", "suites")

            repo = _make_source_repo(selected_branch)
            session = get_session()
            count = sync_from_source_repo(repo, session)
            session.close()

            if return_view == "plans":
                return redirect(url_for("plans_index", branch=selected_branch))
            if return_view == "executions":
                return redirect(url_for("executions_index", branch=selected_branch))
            return redirect(url_for("index", branch=selected_branch))
        except Exception as exc:
            error_msg = str(exc)
            # Provide helpful context for common errors
            if "Error binding parameter" in error_msg or "unsupported type" in error_msg:
                error_msg = (
                    "Sync failed due to YAML format issue. "
                    "Check that test YAML has the expected structure (see README.md for format). "
                    "Error: " + error_msg[:100]
                )
            else:
                error_msg = f"Sync failed: {error_msg}"

            return render_template(
                "index.html",
                error=error_msg,
                repo_name=None,
                branches=[],
                selected_branch=None,
                suites=[],
                suite_payload=[],
                show_sync_button=False,
                need_sync=False,
                default_base_url="http://localhost:5004/",
                freshness_check_interval_seconds=1800,
                last_synced_at_iso=None,
                last_synced_display="Never",
            )

    @app.route("/api/plan/<int:plan_id>/tests", methods=["GET", "POST"])
    def plan_tests_api(plan_id: int):
        """GET: return list of test IDs in the plan.
        POST {action: "add"|"remove", test_ids: [...]}: modify plan membership.
        Returns updated list of test IDs.
        """
        session = get_session()
        try:
            plan = session.query(TestPlan).filter_by(id=plan_id).first()
            if plan is None:
                return jsonify({"error": "Plan not found"}), 404

            if request.method == "POST":
                data = request.get_json(force=True) or {}
                action = data.get("action", "")
                raw_ids = data.get("test_ids", [])
                try:
                    test_ids_int = [int(t) for t in raw_ids]
                except (ValueError, TypeError):
                    return jsonify({"error": "Invalid test_ids"}), 400

                now = datetime.now(timezone.utc)
                if action == "add":
                    existing = session.query(TestPlanItem).filter_by(test_plan_id=plan_id).all()
                    existing_ids = {item.test_id for item in existing}
                    max_order = max((item.order_index for item in existing), default=-1)
                    for tid in test_ids_int:
                        if tid not in existing_ids:
                            max_order += 1
                            session.add(TestPlanItem(
                                test_plan_id=plan_id,
                                test_id=tid,
                                order_index=max_order,
                            ))
                elif action == "remove":
                    if test_ids_int:
                        session.query(TestPlanItem).filter(
                            TestPlanItem.test_plan_id == plan_id,
                            TestPlanItem.test_id.in_(test_ids_int),
                        ).delete(synchronize_session=False)
                else:
                    return jsonify({"error": "action must be 'add' or 'remove'"}), 400

                plan.updated_at = now
                session.commit()

            # Return current state
            items = session.query(TestPlanItem).filter_by(test_plan_id=plan_id).all()
            return jsonify({
                "plan_id": plan_id,
                "test_ids": [item.test_id for item in items],
            })
        finally:
            session.close()

    # -----------------------------------------------------------------------
    # Execution API endpoints
    # -----------------------------------------------------------------------

    @app.patch("/api/execution-result/<int:result_id>")
    def update_execution_result(result_id: int):
        """Update status and/or comment for an execution result.
        Accepts JSON {status: 'pass'|'fail'|'pending', comment: '...'}
        """
        session = get_session()
        try:
            result = session.query(ExecutionResult).filter_by(id=result_id).first()
            if result is None:
                return jsonify({"error": "Result not found"}), 404

            data = request.get_json(force=True) or {}
            status = str(data.get("status", "")).strip()
            comment = str(data.get("comment", "")).strip()

            if status and status in ("pass", "fail", "pending"):
                result.status = status
            if "comment" in data:
                result.comment = comment

            session.commit()
            return jsonify({
                "id": result.id,
                "status": result.status,
                "comment": result.comment
            })
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            session.close()

    @app.patch("/api/execution-step/<int:step_id>")
    def update_execution_step(step_id: int):
        """Update comment for an execution step.
        Accepts JSON {comment: '...'}
        """
        session = get_session()
        try:
            step = session.query(ExecutionStep).filter_by(id=step_id).first()
            if step is None:
                return jsonify({"error": "Step not found"}), 404

            data = request.get_json(force=True) or {}
            comment = str(data.get("comment", "")).strip()

            step.comment = comment
            session.commit()
            return jsonify({
                "id": step.id,
                "comment": step.comment
            })
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            session.close()

    @app.patch("/api/execution-test/<int:test_id>")
    def update_execution_test(test_id: int):
        """Update status and/or comment for an execution test.
        Accepts JSON {status: 'pass'|'fail'|'pending'|'skipped', comment: '...'}
        """
        session = get_session()
        try:
            test = session.query(ExecutionTest).filter_by(id=test_id).first()
            if test is None:
                return jsonify({"error": "Test not found"}), 404

            data = request.get_json(force=True) or {}
            status = str(data.get("status", "")).strip()
            comment = str(data.get("comment", "")).strip()

            if status and status in ("pass", "fail", "pending", "skipped"):
                test.status = status
            if "comment" in data:
                test.comment = comment

            session.commit()
            return jsonify({
                "id": test.id,
                "status": test.status,
                "comment": test.comment
            })
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        finally:
            session.close()

    return app


app = create_app()


def main() -> None:
    import argparse
    from testbook.config import get_server_config, sync_flaskenv

    parser = argparse.ArgumentParser(description="Run the Testbook web server.")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="TCP port to listen on (overrides config.yml and TESTBOOK_PORT).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=True,
        help="Enable Flask debug mode (default: on).",
    )
    args = parser.parse_args()

    if args.port is not None:
        port = args.port
    else:
        port = get_server_config()["port"]

    # Keep .flaskenv in sync so PyCharm's Flask runner uses the same port.
    sync_flaskenv(port)

    app.run(host="0.0.0.0", port=port, debug=args.debug, use_reloader=False)


if __name__ == "__main__":
    main()
