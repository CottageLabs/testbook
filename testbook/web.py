from flask import Flask, render_template, request, redirect, url_for
from sqlalchemy.orm import joinedload

from testbook.config import ConfigurationError, get_source_repo_config
from testbook.database import get_session, init_db, sync_from_source_repo
from testbook.github_connector import SourceRepo
from testbook.models import Suite, TestSet


def _make_source_repo(branch: str | None = None) -> SourceRepo:
    """Build a SourceRepo from the current config, optionally overriding the branch."""
    cfg = get_source_repo_config()
    return SourceRepo(
        token=cfg["github_token"],
        repo_name=cfg["repo_name"],
        tests_path=cfg["tests_path"],
        branch=branch or cfg["default_branch"],
    )


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
                    joinedload(Suite.testsets).joinedload(TestSet.tests)
                )
                .filter_by(
                    repo_name=cfg["repo_name"],
                    branch=selected_branch,
                )
                .all()
            )
            session.close()

            branches = _make_source_repo(selected_branch).list_branches()

            if cached_suites:
                # Display cached data
                return render_template(
                    "index.html",
                    repo_name=cfg["repo_name"],
                    branches=branches,
                    selected_branch=selected_branch,
                    suites=cached_suites,
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
                show_sync_button=False,
                need_sync=False,
            )

    return app


app = create_app()


def main() -> None:
    app.run(debug=True, use_reloader=False)


if __name__ == "__main__":
    main()
