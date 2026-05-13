from flask import Flask, render_template, request, redirect, url_for, jsonify
from datetime import datetime, timezone
from sqlalchemy.orm import joinedload
from urllib.parse import quote

from testbook.config import ConfigurationError, get_source_repo_config
from testbook.database import get_session, init_db, sync_from_source_repo
from testbook.github_connector import SourceRepo
from testbook.models import (
    BranchSyncState,
    Result,
    SetupItem,
    Step,
    Suite,
    Test,
    TestDependency,
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
        "plans": [],
        "selected_plan_id": None,
        "selected_plan_title": "",
        "active_plan_id": "",
        "active_plan_title": "",
        "plan_test_ids": [],
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
            if selected_plan is None and plans:
                selected_plan = plans[0]

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
                plans=_serialize_plans(plans),
                selected_plan_id=_id_value(getattr(selected_plan, "id", ""), "") if selected_plan else "",
                selected_plan_title=_text_value(getattr(selected_plan, "title", ""), ""),
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
                }
            )
            return render_template("plans.html", **context)

    @app.post("/plans/add")
    def add_plan() -> str:
        try:
            cfg = get_source_repo_config()
            selected_branch = request.form.get("branch", cfg["default_branch"])
            session = get_session()
            existing_count = (
                session.query(TestPlan)
                .filter_by(repo_name=cfg["repo_name"], branch=selected_branch)
                .count()
            )
            now = datetime.now(timezone.utc)
            plan = TestPlan(
                title=f"New Plan {existing_count + 1}",
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

    return app


app = create_app()


def main() -> None:
    app.run(debug=True, use_reloader=False)


if __name__ == "__main__":
    main()
