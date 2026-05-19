"""
Low-level GitHub connectors for testbook.

Two roles, two classes:

  SourceRepo  – read-only access to the *code* repository that contains test
                definition YAML files.

  PlansRepo   – read/write access to the *plans* repository where test plans
                and execution records will be stored.

Both authenticate with a GitHub Personal Access Token (PAT) and communicate
exclusively through the GitHub REST API (no local git clone required).
"""
from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Generator

import yaml
from github import Github, GithubException
from github.Repository import Repository


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------

class _GitHubConnector:
    """Holds an authenticated GitHub client and a cached repository handle."""

    def __init__(self, token: str, repo_name: str, branch: str = "main") -> None:
        """
        Parameters
        ----------
        token:
            A GitHub Personal Access Token with the scopes required by the
            subclass (``repo`` is sufficient for both public and private repos).
        repo_name:
            Full ``owner/repo`` identifier, e.g. ``"myorg/myproject"``.
        branch:
            The branch (or tag / commit SHA) to read from / write to.
            Defaults to ``"main"``.
        """
        self._gh: Github = Github(token)
        self._repo: Repository = self._gh.get_repo(repo_name)
        self.branch: str = branch

    @property
    def repo_name(self) -> str:
        return self._repo.full_name

    def _decode_content(self, content_file: Any) -> str:
        """Decode a Base-64 encoded ContentFile returned by PyGithub."""
        return base64.b64decode(content_file.content).decode("utf-8")

    def _collect_yaml_paths(self, path: str, result: list[str]) -> None:
        """Recursively collect .yml/.yaml file paths under *path*."""
        try:
            items = self._repo.get_contents(path, ref=self.branch)
        except GithubException as exc:
            if exc.status == 404:
                return
            raise
        if not isinstance(items, list):
            items = [items]
        for item in items:
            if item.type == "dir":
                self._collect_yaml_paths(item.path, result)
            elif item.name.endswith((".yml", ".yaml")):
                result.append(item.path)


# ---------------------------------------------------------------------------
# Source repo  (tests live here, read-only)
# ---------------------------------------------------------------------------

class SourceRepo(_GitHubConnector):
    """Read-only connector for the code repository that contains test YAML files.

    Example
    -------
    >>> source = SourceRepo(token="ghp_…", repo_name="myorg/myproject",
    ...                     tests_path="functional_tests", branch="develop")
    >>> for path, data in source.load_all_tests():
    ...     print(path, data["suite"])
    """

    def __init__(
        self,
        token: str,
        repo_name: str,
        tests_path: str = "testbook",
        branch: str = "main",
    ) -> None:
        """
        Parameters
        ----------
        tests_path:
            Path inside the repository that contains the test definition YAML
            files.  Sub-directories are walked recursively.  Defaults to
            ``"testbook"``.
        """
        super().__init__(token, repo_name, branch)
        self.tests_path: str = tests_path.rstrip("/")

    def list_test_files(self) -> list[str]:
        """Return a sorted list of repo-relative paths of all YAML test files."""
        paths: list[str] = []
        self._collect_yaml_paths(self.tests_path, paths)
        return sorted(paths)

    def load_test_file(self, path: str) -> dict[str, Any]:
        """Fetch and parse a single YAML test file.

        Parameters
        ----------
        path:
            Repo-relative path, e.g. ``"testbook/authentication/login.yml"``.

        Returns
        -------
        dict
            Parsed YAML content.
        """
        content_file = self._repo.get_contents(path, ref=self.branch)
        return yaml.safe_load(self._decode_content(content_file))

    def load_all_tests(self) -> Generator[tuple[str, dict[str, Any]], None, None]:
        """Yield ``(path, parsed_yaml)`` for every test file under ``tests_path``."""
        for path in self.list_test_files():
            yield path, self.load_test_file(path)

    def list_branches(self) -> list[str]:
        """Return a sorted list of all branch names in the source repository."""
        return sorted(branch.name for branch in self._repo.get_branches())

    def github_file_url(self, path: str) -> str:
        """Return the GitHub web URL for *path* on the current branch.

        Example: ``https://github.com/myorg/myproject/blob/main/testbook/login.yml``
        """
        return f"https://github.com/{self._repo.full_name}/blob/{self.branch}/{path}"

    def latest_tests_commit_timestamp(self) -> datetime | None:
        """Return the latest commit timestamp that touched files under tests_path.

        Returns None when no commits are found for the path.
        """
        commits = self._repo.get_commits(sha=self.branch, path=self.tests_path)
        for commit in commits:
            commit_obj = getattr(commit, "commit", None)
            committer = getattr(commit_obj, "committer", None)
            author = getattr(commit_obj, "author", None)
            commit_dt = getattr(committer, "date", None) or getattr(author, "date", None)
            if isinstance(commit_dt, datetime):
                return commit_dt
        return None


# ---------------------------------------------------------------------------
# Plans repo  (plans + executions live here, read/write)
# ---------------------------------------------------------------------------

class PlansRepo(_GitHubConnector):
    """Read/write connector for the repository that stores test plans and
    execution records.

    File layout inside the plans repo is left intentionally open — the caller
    chooses where to put each YAML file.  A typical convention might be::

        plans/<plan-id>.yml
        executions/<plan-id>/<execution-id>.yml

    Example
    -------
    >>> plans = PlansRepo(token="ghp_…", repo_name="myorg/test-plans")
    >>> plans.write("plans/sprint-42.yml",
    ...             {"plan": "Sprint 42", "tests": [...]},
    ...             commit_message="Add Sprint 42 test plan")
    >>> data = plans.read("plans/sprint-42.yml")
    """

    def list_files(self, path: str = "") -> list[str]:
        """Return a sorted list of YAML file paths under *path* (default: root).

        Parameters
        ----------
        path:
            Sub-directory to search, e.g. ``"plans"`` or ``"executions/sprint-42"``.
            Leave empty to search from the repository root.
        """
        paths: list[str] = []
        self._collect_yaml_paths(path or "", paths)
        return sorted(paths)

    def read(self, path: str) -> dict[str, Any]:
        """Fetch and parse a YAML file from the plans repo.

        Parameters
        ----------
        path:
            Repo-relative path, e.g. ``"plans/sprint-42.yml"``.

        Raises
        ------
        GithubException
            Re-raised for any API error (including 404 if the file does not
            exist yet).
        """
        content_file = self._repo.get_contents(path, ref=self.branch)
        return yaml.safe_load(self._decode_content(content_file))

    def write(
        self,
        path: str,
        data: dict[str, Any],
        commit_message: str,
    ) -> None:
        """Serialise *data* as YAML and create or update the file at *path*.

        If the file already exists it is updated (the current SHA is fetched
        automatically as required by the GitHub Contents API).  If it does not
        exist it is created.

        Parameters
        ----------
        path:
            Repo-relative destination path, e.g. ``"plans/sprint-42.yml"``.
        data:
            Python dict that will be serialised to YAML.
        commit_message:
            Commit message used for the create/update operation.
        """
        raw_bytes = yaml.dump(data, allow_unicode=True, sort_keys=False).encode("utf-8")

        try:
            existing = self._repo.get_contents(path, ref=self.branch)
            self._repo.update_file(
                path=path,
                message=commit_message,
                content=raw_bytes,
                sha=existing.sha,
                branch=self.branch,
            )
        except GithubException as exc:
            if exc.status == 404:
                self._repo.create_file(
                    path=path,
                    message=commit_message,
                    content=raw_bytes,
                    branch=self.branch,
                )
            else:
                raise

    def delete(self, path: str, commit_message: str) -> None:
        """Delete the file at *path* from the plans repo.

        Parameters
        ----------
        path:
            Repo-relative path of the file to delete.
        commit_message:
            Commit message used for the delete operation.
        """
        existing = self._repo.get_contents(path, ref=self.branch)
        self._repo.delete_file(
            path=path,
            message=commit_message,
            sha=existing.sha,
            branch=self.branch,
        )


# ---------------------------------------------------------------------------
# Issues repo  (feedback comments go here, write-only)
# ---------------------------------------------------------------------------

class IssuesRepo(_GitHubConnector):
    """Write-only connector for posting feedback comments to issues/PRs.

    Example
    -------
    >>> issues = IssuesRepo(token="ghp_…", repo_name="myorg/myproject")
    >>> comment_url = issues.post_comment(42, "This is a test failure report…")
    >>> print(comment_url)
    https://github.com/myorg/myproject/issues/42#issuecomment-1234567890
    """

    def post_comment(self, issue_number: int, body: str) -> str:
        """Post a comment on an issue or pull request.

        Parameters
        ----------
        issue_number:
            GitHub issue or pull request number (e.g., 42).
        body:
            Comment text (markdown-formatted).

        Returns
        -------
        str
            URL to the created comment.

        Raises
        ------
        GithubException
            Re-raised for any API error.
        """
        issue = self._repo.get_issue(issue_number)
        comment = issue.create_comment(body)
        return comment.html_url
