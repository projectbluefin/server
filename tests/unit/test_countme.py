"""countme: the image's declared identity and the reporter it ships.

os-image-info.bst writes /usr/share/ublue-os/image-info.json, which the shared
reporter from projectbluefin/common reads. os-countme.bst installs that reporter
from a pinned commit of common.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ELEMENTS = REPO_ROOT / "elements" / "bluefin-server"
TRANSFERS = REPO_ROOT / "files" / "os" / "sysupdate.d"
COMMON_URL = "https://github.com/projectbluefin/common.git"


def _element(name: str) -> dict:
    return yaml.safe_load((ELEMENTS / name).read_text(encoding="utf-8"))


def _image_info() -> dict:
    commands = "\n".join(_element("os-image-info.bst")["config"]["install-commands"])
    body = re.search(r"<<'JSON'\n(.*?)\n\s*JSON\s*$", commands, re.S | re.M)
    assert body, "os-image-info.bst must write image-info.json from a JSON heredoc"
    return json.loads(body.group(1))


def _transfer_channels() -> set[str]:
    channels = set()
    for transfer in TRANSFERS.glob("*.transfer"):
        for path in re.findall(r"^Path=(https://\S+)$", transfer.read_text(encoding="utf-8"), re.M):
            match = re.fullmatch(r"https://github\.com/[^/]+/[^/]+/releases/(.+)/download/", path)
            assert match, f"{transfer.name}: unexpected source Path={path}"
            channels.add(match.group(1))
    return channels


def test_image_info_declares_name_and_stream_only():
    # No image-flavor: a DDI has no flavors, and a guessed one would be counted
    # as a real population (projectbluefin/server#97).
    assert _image_info() == {"image-name": "server", "image-tag": "latest"}


def test_image_tag_is_the_channel_sysupdate_follows():
    # The tag is the stream, not the version: it must name the one GitHub
    # Releases channel every transfer pulls from, and change with it.
    channels = _transfer_channels()
    assert channels == {"latest"}, f"transfers follow {sorted(channels)}"
    assert _image_info()["image-tag"] in channels


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
