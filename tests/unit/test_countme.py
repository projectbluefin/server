"""countme: the image's declared identity and the reporter it ships.

os-image-info.bst writes /usr/share/ublue-os/image-info.json, which the shared
reporter from projectbluefin/common reads. os-countme.bst installs that reporter
from a pinned commit of common.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ELEMENTS = REPO_ROOT / "elements" / "bluefin-server"
COMMON_URL = "https://github.com/projectbluefin/common.git"


def _element(name: str) -> dict:
    return yaml.safe_load((ELEMENTS / name).read_text(encoding="utf-8"))


def test_countme_ships_main_reporter_units():
    commands = " ".join(_element("os-countme.bst")["config"]["install-commands"])
    for path in (
        "usr/libexec/projectbluefin-countme",
        "usr/lib/systemd/system/projectbluefin-countme.service",
        "usr/lib/systemd/system/projectbluefin-countme.timer",
        "usr/lib/systemd/system-preset/03-projectbluefin-countme.preset",
    ):
        assert f"system_files/shared/{path}" in commands
    assert not re.search(r"(?<!project)bluefin-countme", commands)


@pytest.fixture(scope="module")
def common_main(tmp_path_factory) -> Path:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    repo = tmp_path_factory.mktemp("common")
    subprocess.run([git, "init", "-q", str(repo)], check=True)
    fetch = subprocess.run(
        [git, "-C", str(repo), "fetch", "-q", "--filter=tree:0", COMMON_URL, "main"],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        timeout=120,
        check=False,
    )
    if fetch.returncode != 0:
        if os.environ.get("CI") == "true":
            pytest.fail(f"cannot fetch projectbluefin/common main: {fetch.stderr}")
        pytest.skip("projectbluefin/common is unreachable")
    return repo


def _countme_commit() -> str:
    source = _element("os-countme.bst")["sources"][0]
    assert source["url"] == "github:projectbluefin/common.git"
    assert source["track"] == "main"
    match = re.fullmatch(r".*-g([0-9a-f]{40})", source["ref"])
    assert match, f"ref {source['ref']!r} is not a tracked git_repo ref"
    return match.group(1)


def test_countme_ref_is_on_common_main(common_main):
    # projectbluefin/server#95: a ref that is only on a PR branch disappears with
    # the branch. The pin must be reachable from common main.
    sha = _countme_commit()
    ancestor = subprocess.run(
        ["git", "-C", str(common_main), "merge-base", "--is-ancestor", sha, "FETCH_HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ancestor.returncode == 0, f"{sha} is not on projectbluefin/common main"


def test_countme_reporter_at_ref_reads_image_info(common_main):
    sha = _countme_commit()
    commands = " ".join(_element("os-countme.bst")["config"]["install-commands"])
    for path in re.findall(r"(system_files/\S+?)[\"\s]", commands + " "):
        listed = subprocess.run(
            ["git", "-C", str(common_main), "ls-tree", "--name-only", sha, "--", path],
            capture_output=True,
            text=True,
            check=True,
        )
        assert listed.stdout.strip() == path, f"{path} is missing at {sha}"
    script = subprocess.run(
        ["git", "-C", str(common_main), "show", f"{sha}:system_files/shared/usr/libexec/projectbluefin-countme"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "/usr/share/ublue-os/image-info.json" in script
