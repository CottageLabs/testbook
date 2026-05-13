from flask import Flask, render_template, request, redirect, url_for
from sqlalchemy.orm import joinedload
from urllib.parse import quote

from testbook.config import ConfigurationError, get_source_repo_config
from testbook.database import get_session, init_db, sync_from_source_repo
from testbook.github_connector import SourceRepo
from testbook.models import Result, SetupItem, Step, Suite, Test, TestDependency, TestSet


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


def _build_suite_payload(cached_suites: list[Suite]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for suite_idx, suite in enumerate(cached_suites):
        suite_id = _id_value(getattr(suite, "id", ""), f"suite-{suite_idx + 1}")
        suite_name = _text_value(getattr(suite, "name", ""), f"Suite {suite_idx + 1}")
        raw_testsets = _list_value(getattr(suite, "testsets", []))
        sorted_testsets = sorted(
            raw_testsets,
            key=lambda ts: _order_value(getattr(ts, "order_index", None), 0),
        )

        serialized_testsets: list[dict[str, object]] = []
        for testset_idx, testset in enumerate(sorted_testsets):
            testset_id = _id_value(getattr(testset, "id", ""), f"{suite_id}-set-{testset_idx + 1}")
            testset_name = _text_value(getattr(testset, "name", ""), f"TestSet {testset_idx + 1}")
            raw_tests = _list_value(getattr(testset, "tests", []))
            sorted_tests = sorted(
                raw_tests,
                key=lambda test: _order_value(getattr(test, "order_index", None), 0),
            )

            serialized_tests: list[dict[str, object]] = []
            for test_idx, test in enumerate(sorted_tests):
                test_id = _id_value(getattr(test, "id", ""), f"{testset_id}-test-{test_idx + 1}")
                test_title = _text_value(getattr(test, "title", ""), f"Test {test_idx + 1}")
                file_path = _text_value(getattr(test, "file_path", ""), "")
                github_edit_url = ""
                if file_path and getattr(suite, "repo_name", "") and getattr(suite, "branch", ""):
                    github_edit_url = (
                        f"https://github.com/{suite.repo_name}/edit/"
                        f"{quote(str(suite.branch), safe='')}/"
                        f"{quote(file_path, safe='/')}"
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
                            "resource": _text_value(getattr(step, "resource", ""), ""),
                            "results": results,
                        }
                    )

                serialized_tests.append(
                    {
                        "id": test_id,
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
                    "name": testset_name,
                    "tests": serialized_tests,
                }
            )

        payload.append(
            {
                "id": suite_id,
                "name": suite_name,
                "testsets": serialized_testsets,
            }
        )

    return payload


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
            session.close()

            branches = _make_source_repo(selected_branch).list_branches()
            suite_payload = _build_suite_payload(cached_suites)

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
                )

        except ConfigurationError as exc:
            return render_template(
                "index.html",
                error=str(exc),
                repo_name=None,
                branches=[],
                selected_branch=None,
                suites=[],
                suite_payload=[],
                show_sync_button=False,
                need_sync=False,
            )
        except Exception as exc:
            return render_template(
                "index.html",
                error=f"GitHub error: {exc}",
                repo_name=None,
                branches=[],
                selected_branch=None,
                suites=[],
                suite_payload=[],
                show_sync_button=False,
                need_sync=False,
            )

    @app.post("/sync")
    def sync() -> str:
        try:
            cfg = get_source_repo_config()
            selected_branch = request.form.get("branch", cfg["default_branch"])

            repo = _make_source_repo(selected_branch)
            session = get_session()
            count = sync_from_source_repo(repo, session)
            session.close()

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
            )

    return app


app = create_app()


def main() -> None:
    app.run(debug=True, use_reloader=False)


if __name__ == "__main__":
    main()
