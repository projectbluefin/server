""".github/scripts/propose-pr.sh: the trackers' "create or update the PR" step.

Runs the script in a real git checkout whose origin is a local bare
repository, with `gh` stubbed. The contract: propose nothing when the paths
match HEAD; leave an open pull request alone when its branch already holds the
same content (no daily force-push, no restarted CI); push and edit it when the
content differs; open one otherwise; with --skip-closed-title, never reopen a
title that was turned down; and stop, without pushing, when `gh` fails.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "propose-pr.sh"
BRANCH = "auto/track-test"
TITLE = "chore(deps): update thing 1.0 -> 1.1"

GH = """#!/bin/sh
echo "$*" >> "$LOG/gh"
[ -z "$GH_FAIL" ] || { echo "gh: HTTP 502" >&2; exit 1; }
case "$*" in
  "pr list"*"--state open"*) [ -z "$OPEN_PR" ] || echo "$OPEN_PR" ;;
  "pr list"*"--state closed"*) [ -z "$CLOSED_TITLES" ] || printf '%s\\n' "$CLOSED_TITLES" ;;
  "pr create"*) echo "https://github.com/o/r/pull/99" ;;
  "pr view"*) echo "https://github.com/o/r/pull/$OPEN_PR" ;;
esac
"""


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(remote))
    work = tmp_path / "work"
    git(tmp_path, "clone", "--quiet", str(remote), str(work))
    (work / "pin.txt").write_text("1.0\n")
    (work / "other.txt").write_text("x\n")
    git(work, "add", ".")
    git(work, "commit", "--quiet", "-m", "base")
    git(work, "push", "--quiet", "origin", "HEAD:main")
    return work


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH)
    (bin_dir / "gh").chmod(0o755)
    log = tmp_path / "log"
    log.mkdir()
    (tmp_path / "body.md").write_text("body\n")
    return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "LOG": str(log), "OPEN_PR": "",
            "CLOSED_TITLES": "", "GH_FAIL": "", "BODY": str(tmp_path / "body.md")}


def propose(repo: Path, env: dict[str, str], *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), "--branch", BRANCH, "--title", TITLE, "--body-file", env["BODY"], *extra,
         "--", "pin.txt"],
        cwd=repo, env=env, capture_output=True, text=True,
    )


def remote_branch(repo: Path) -> str:
    return git(repo, "ls-remote", "origin", f"refs/heads/{BRANCH}")


def gh_calls(env: dict[str, str]) -> list[str]:
    log = Path(env["LOG"]) / "gh"
    return log.read_text().splitlines() if log.exists() else []


def push_branch_with(repo: Path, content: str) -> str:
    git(repo, "checkout", "--quiet", "-b", "earlier")
    (repo / "pin.txt").write_text(content)
    git(repo, "commit", "--quiet", "-am", "earlier proposal")
    git(repo, "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}")
    git(repo, "checkout", "--quiet", "main")
    git(repo, "branch", "--quiet", "-D", "earlier")
    git(repo, "update-ref", "-d", f"refs/remotes/origin/{BRANCH}")
    return remote_branch(repo).split()[0]


def test_nothing_to_propose_touches_nothing(repo: Path, env: dict[str, str]) -> None:
    result = propose(repo, env)
    assert result.returncode == 0, result.stderr
    assert "Nothing to propose" in result.stdout
    assert remote_branch(repo) == ""
    assert gh_calls(env) == []


def test_opens_a_pull_request_on_a_new_branch(repo: Path, env: dict[str, str]) -> None:
    (repo / "pin.txt").write_text("1.1\n")
    (repo / "other.txt").write_text("unrelated local change\n")
    result = propose(repo, env)
    assert result.returncode == 0, result.stderr
    assert "Created PR: https://github.com/o/r/pull/99" in result.stdout
    head = remote_branch(repo).split()[0]
    assert git(repo, "show", f"{head}:pin.txt") == "1.1"
    assert git(repo, "show", f"{head}:other.txt") == "x", "only the named paths are committed"
    assert git(repo, "log", "-1", "--format=%s%n%an%n%b", head).splitlines() == [TITLE, "github-actions[bot]"]
    assert any(c.startswith(f"pr create --base main --head {BRANCH} --title {TITLE}") for c in gh_calls(env))


def test_open_pull_request_with_identical_content_is_left_alone(repo: Path, env: dict[str, str]) -> None:
    before = push_branch_with(repo, "1.1\n")
    env["OPEN_PR"] = "7"
    (repo / "pin.txt").write_text("1.1\n")
    result = propose(repo, env)
    assert result.returncode == 0, result.stderr
    assert "#7 already proposes this content" in result.stdout
    assert remote_branch(repo).split()[0] == before, "no new commit, no force-push"
    assert not any(c.startswith(("pr edit", "pr create")) for c in gh_calls(env))


def test_open_pull_request_with_other_content_is_updated(repo: Path, env: dict[str, str]) -> None:
    before = push_branch_with(repo, "1.1\n")
    env["OPEN_PR"] = "7"
    (repo / "pin.txt").write_text("1.2\n")
    result = propose(repo, env)
    assert result.returncode == 0, result.stderr
    after = remote_branch(repo).split()[0]
    assert after != before
    assert git(repo, "show", f"{after}:pin.txt") == "1.2"
    assert f"pr edit 7 --title {TITLE} --body-file {env['BODY']}" in gh_calls(env)
    assert "Updated PR: https://github.com/o/r/pull/7" in result.stdout


def test_stale_branch_without_a_pull_request_is_replaced(repo: Path, env: dict[str, str]) -> None:
    push_branch_with(repo, "1.1\n")
    (repo / "pin.txt").write_text("1.1\n")
    result = propose(repo, env)
    assert result.returncode == 0, result.stderr
    assert "Created PR" in result.stdout
    head = remote_branch(repo).split()[0]
    assert git(repo, "log", "-1", "--format=%s", head) == TITLE


@pytest.mark.parametrize("skip_closed", [True, False])
def test_closed_title_is_only_respected_on_request(repo: Path, env: dict[str, str], skip_closed: bool) -> None:
    env["CLOSED_TITLES"] = f"something else\n{TITLE}"
    (repo / "pin.txt").write_text("1.1\n")
    result = propose(repo, env, *(["--skip-closed-title"] if skip_closed else []))
    assert result.returncode == 0, result.stderr
    if skip_closed:
        assert "not reopening it" in result.stdout
        assert remote_branch(repo) == ""
    else:
        assert "Created PR" in result.stdout
        assert remote_branch(repo) != ""


def test_a_failed_query_stops_before_pushing(repo: Path, env: dict[str, str]) -> None:
    env["GH_FAIL"] = "1"
    (repo / "pin.txt").write_text("1.1\n")
    result = propose(repo, env)
    assert result.returncode != 0
    assert remote_branch(repo) == ""


def test_an_unreachable_remote_stops_before_querying(repo: Path, env: dict[str, str]) -> None:
    git(repo, "remote", "set-url", "origin", str(repo.parent / "missing.git"))
    (repo / "pin.txt").write_text("1.1\n")
    result = propose(repo, env)
    assert result.returncode != 0
    assert "cannot list" in result.stderr
    assert gh_calls(env) == []


@pytest.mark.parametrize("args", [[], ["--branch", BRANCH], ["--branch", BRANCH, "--title", TITLE]])
def test_requires_branch_title_and_body(repo: Path, env: dict[str, str], args: list[str]) -> None:
    result = subprocess.run(["bash", str(SCRIPT), *args, "--", "pin.txt"], cwd=repo, env=env,
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert gh_calls(env) == []


def test_both_trackers_propose_through_the_script() -> None:
    for name, extra in (("track-junctions.yml", ""), ("track-binaries.yml", "--skip-closed-title")):
        text = (ROOT / ".github" / "workflows" / name).read_text()
        assert "bash .github/scripts/propose-pr.sh" in text, name
        assert extra in text
        for inline in ("gh pr create", "gh pr edit", "git push", "git commit -"):
            assert inline not in text, f"{name} still inlines {inline}"
