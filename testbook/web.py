from flask import Flask, render_template, request

from testbook.config import ConfigurationError, get_source_repo_config
from testbook.github_connector import SourceRepo


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

    @app.get("/")
    def index() -> str:
        try:
            cfg = get_source_repo_config()
            default_branch = cfg["default_branch"]
            selected_branch = request.args.get("branch", default_branch)

            repo = _make_source_repo(selected_branch)
            branches = repo.list_branches()
            test_files = [
                {"path": p, "url": repo.github_file_url(p)}
                for p in repo.list_test_files()
            ]

            return render_template(
                "index.html",
                repo_name=cfg["repo_name"],
                tests_path=cfg["tests_path"],
                branches=branches,
                selected_branch=selected_branch,
                test_files=test_files,
                error=None,
            )
        except ConfigurationError as exc:
            return render_template("index.html", error=str(exc),
                                   repo_name=None, tests_path=None,
                                   branches=[], selected_branch=None,
                                   test_files=[])
        except Exception as exc:
            return render_template("index.html", error=f"GitHub error: {exc}",
                                   repo_name=None, tests_path=None,
                                   branches=[], selected_branch=None,
                                   test_files=[])

    return app


app = create_app()


def main() -> None:
    app.run(debug=True, use_reloader=False)


if __name__ == "__main__":
    main()
