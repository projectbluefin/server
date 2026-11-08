"""The Homebrew seed: unit, tmpfiles rule, profile snippet and extraction script."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
HOMEBREW = ROOT / "files/homebrew"
SEED = HOMEBREW / "bluefin-homebrew-seed"
STAMP = "/var/lib/bluefin-homebrew/seeded"
ARCHIVE = "/usr/share/homebrew/brew.tar.zst"


def test_seed_unit_is_a_stamped_oneshot() -> None:
    unit = SystemdFile(HOMEBREW / "bluefin-homebrew-seed.service")
    assert unit.value("Service", "Type") == "oneshot"
    assert unit.value("Service", "RemainAfterExit") == "yes"
    assert unit.value("Service", "ExecStart") == "/usr/libexec/bluefin-homebrew-seed"
    assert f"!{STAMP}" in unit.values("Unit", "ConditionPathExists")
    assert ARCHIVE in unit.values("Unit", "ConditionPathExists")
    assert unit.value("Install", "WantedBy") == "multi-user.target"


def test_path_unit_retries_when_accounts_change() -> None:
    path = SystemdFile(HOMEBREW / "bluefin-homebrew-seed.path")
    assert path.value("Path", "PathChanged") == "/etc/passwd"
    assert path.value("Path", "Unit") == "bluefin-homebrew-seed.service"
    assert f"!{STAMP}" in path.values("Unit", "ConditionPathExists")


def test_preset_enables_both_units() -> None:
    lines = (HOMEBREW / "80-bluefin-homebrew.preset").read_text().split("\n")
    assert "enable bluefin-homebrew-seed.service" in lines
    assert "enable bluefin-homebrew-seed.path" in lines


def test_tmpfiles_links_home_linuxbrew_to_var() -> None:
    rules = [line.split() for line in (HOMEBREW / "bluefin-homebrew.tmpfiles").read_text().splitlines()
             if line and not line.startswith("#")]
    assert ["L", "/home/linuxbrew", "-", "-", "-", "-", "/var/home/linuxbrew"] in rules
    assert ["d", "/var/home/linuxbrew", "0755", "root", "root", "-"] in rules
    assert any(rule[:2] == ["L+", "/etc/profile.d/90-bluefin-homebrew.sh"] for rule in rules)


def test_profile_snippet_only_runs_for_seed_owner(tmp_path: Path) -> None:
    snippet = (HOMEBREW / "90-bluefin-homebrew.sh").read_text()
    assert 'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"' in snippet
    assert '[ "$(id -u)" -ne 0 ]' in snippet
    assert '[ -r /var/lib/bluefin-homebrew/seed-owner ]' in snippet
    assert '[ "$(id -u)" = "$(cut -d: -f1 /var/lib/bluefin-homebrew/seed-owner)" ]' in snippet
    assert "[ -x /home/linuxbrew/.linuxbrew/bin/brew ]" in snippet
    assert "CONTAINER_HOST=" in snippet
    assert "DOCKER_HOST=" in snippet
    # Absent prefix / root: sourcing is a silent no-op.
    result = subprocess.run(["sh", "-c", f". {HOMEBREW / '90-bluefin-homebrew.sh'}; echo ok"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0 and result.stdout == "ok\n"


def test_profile_snippet_behavior_matrix(tmp_path: Path) -> None:
    script_text = (HOMEBREW / "90-bluefin-homebrew.sh").read_text()
    state = tmp_path / "var/lib/bluefin-homebrew"
    state.mkdir(parents=True)
    (state / "seed-owner").write_text("1000:1000\n")
    prefix_bin = tmp_path / "home/linuxbrew/.linuxbrew/bin"
    prefix_bin.mkdir(parents=True)
    brew = prefix_bin / "brew"
    brew.write_text("#!/bin/sh\necho 'export BREW_SHELLENV=1'")
    brew.chmod(0o755)

    # Script tested with mocked paths
    test_script = tmp_path / "test-profile.sh"
    test_script.write_text(
        script_text.replace("/var/lib/bluefin-homebrew", str(state))
                   .replace("/home/linuxbrew/.linuxbrew", str(tmp_path / "home/linuxbrew/.linuxbrew"))
    )

    def run_case(uid: str, is_active: bool, extra_env: dict[str, str] | None = None) -> tuple[int, str]:
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        env["MOCK_UID"] = uid
        env["MOCK_DOCKER_ACTIVE"] = "1" if is_active else "0"
        cmd = (
            f'id() {{ echo "$MOCK_UID"; }}; '
            f'systemctl() {{ [ "$MOCK_DOCKER_ACTIVE" = "1" ]; }}; '
            f'. {test_script}; '
            'echo "BREW=${BREW_SHELLENV:-0} CONTAINER=${CONTAINER_HOST:-none} DOCKER=${DOCKER_HOST:-none}"'
        )
        res = subprocess.run(["sh", "-c", cmd], env=env, capture_output=True, text=True, check=False)
        return res.returncode, res.stdout.strip()

    # Case 1: Root login (uid 0) must never invoke brew or export container variables
    code, out = run_case("0", False)
    assert code == 0
    assert out == "BREW=0 CONTAINER=none DOCKER=none"

    # Case 2: Other nonroot user (uid 1001 != 1000) must never invoke brew
    code, out = run_case("1001", False)
    assert code == 0
    assert out == "BREW=0 CONTAINER=none DOCKER=none"

    # Case 3: Seed owner (uid 1000) with default podman backend
    code, out = run_case("1000", False)
    assert code == 0
    assert "BREW=1" in out
    assert "CONTAINER=unix:///run/user/1000/bluefin-podman/api.sock" in out
    assert "DOCKER=unix:///run/user/1000/bluefin-podman/api.sock" in out

    # Case 4: Seed owner (uid 1000) with docker active
    code, out = run_case("1000", True)
    assert code == 0
    assert "BREW=1" in out
    assert "CONTAINER=unix:///run/user/1000/bluefin-podman/api.sock" in out
    assert "DOCKER=unix:///run/user/1000/bluefin-docker/api.sock" in out

    # Case 5: Explicit CONTAINER_HOST / DOCKER_HOST overrides preserved
    code, out = run_case("1000", False, {"CONTAINER_HOST": "tcp://custom:1234", "DOCKER_HOST": "tcp://custom:5678"})
    assert code == 0
    assert "CONTAINER=tcp://custom:1234" in out
    assert "DOCKER=tcp://custom:5678" in out

def test_element_pins_every_artifact() -> None:
    pins = yaml.safe_load((ROOT / "include/homebrew.yml").read_text())["variables"]
    for key in ("homebrew-version", "homebrew-commit", "homebrew-portable-ruby-version",
                "homebrew-portable-ruby-x86-64-sha256", "homebrew-portable-ruby-arm64-sha256"):
        assert pins[key]
    for key in ("homebrew-portable-ruby-x86-64-sha256", "homebrew-portable-ruby-arm64-sha256"):
        assert len(pins[key]) == 64 and int(pins[key], 16) >= 0
    assert len(pins["homebrew-commit"]) == 40
    element = (ROOT / "elements/homebrew/seed.bst").read_text()
    assert "include/homebrew.yml" in element
    assert "kind: tar" in element and "kind: git_repo" in element


# --- the extraction script ---------------------------------------------------

needs_tools = pytest.mark.skipif(
    shutil.which("zstd") is None or shutil.which("tar") is None, reason="zstd and tar are required")


class Box:
    def __init__(self, root: Path, users: str) -> None:
        self.root = root
        self.parent = root / "home/linuxbrew"
        self.stamp = root / "state/seeded"
        self.archive = root / "brew.tar.zst"
        shims = root / "shims"
        shims.mkdir()
        (shims / "getent").write_text(f"#!/bin/sh\nprintf '%s' '{users}'\n")
        (shims / "chown").write_text(f"#!/bin/sh\necho \"$@\" >> {root}/chown.log\n")
        for shim in shims.iterdir():
            shim.chmod(0o755)
        src = root / "src/.linuxbrew/Homebrew/bin"
        src.mkdir(parents=True)
        (src / "brew").write_text("#!/bin/sh\n")
        subprocess.run(["tar", "--zstd", "-cf", str(self.archive), "-C", str(root / "src"), ".linuxbrew"],
                       check=True)

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SEED)],
            env={"PATH": f"{self.root / 'shims'}:{os.environ['PATH']}",
                 "BLUEFIN_HOMEBREW_SEED_ARCHIVE": str(self.archive),
                 "BLUEFIN_HOMEBREW_PARENT": str(self.parent),
                 "BLUEFIN_HOMEBREW_STAMP": str(self.stamp)},
            capture_output=True, text=True, check=False)

    def chowns(self) -> list[str]:
        log = self.root / "chown.log"
        return log.read_text().splitlines() if log.exists() else []


USERS = "root:x:0:0::/root:/bin/bash\nalice:x:1001:1001::/var/home/alice:/bin/bash\nbob:x:1000:1000::/var/home/bob:/bin/bash\n"


@needs_tools
def test_extracts_once_and_chowns_to_the_first_regular_user(tmp_path: Path) -> None:
    box = Box(tmp_path, USERS)
    result = box.run()
    assert result.returncode == 0, result.stderr
    assert (box.parent / ".linuxbrew/Homebrew/bin/brew").is_file()
    assert box.stamp.exists()
    assert (box.stamp.parent / "seed-owner").read_text() == "1000:1000\n"
    assert "-R 1000:1000 " in box.chowns()[0]
    assert box.chowns()[1].startswith("1000:1000 ")
    assert not [p for p in box.parent.iterdir() if p.name.startswith(".seed.")]


@needs_tools
def test_stamp_is_respected(tmp_path: Path) -> None:
    box = Box(tmp_path, USERS)
    box.stamp.parent.mkdir(parents=True)
    box.stamp.touch()
    assert box.run().returncode == 0
    assert not box.parent.exists()


@needs_tools
def test_existing_prefix_is_never_overwritten(tmp_path: Path) -> None:
    box = Box(tmp_path, USERS)
    prefix = box.parent / ".linuxbrew"
    prefix.mkdir(parents=True)
    (prefix / "mine").write_text("keep")
    assert box.run().returncode == 0
    assert (prefix / "mine").read_text() == "keep"
    assert not (prefix / "Homebrew").exists()
    assert box.stamp.exists()
    assert box.chowns() == []


@needs_tools
def test_defers_until_a_regular_user_exists(tmp_path: Path) -> None:
    box = Box(tmp_path, "root:x:0:0::/root:/bin/bash\nnobody:x:65534:65534::/:/sbin/nologin\n")
    result = box.run()
    assert result.returncode == 0, result.stderr
    assert "deferring" in result.stdout
    assert not box.stamp.exists()
    assert not box.parent.exists()


@needs_tools
def test_missing_archive_fails_without_a_stamp(tmp_path: Path) -> None:
    box = Box(tmp_path, USERS)
    box.archive.unlink()
    result = box.run()
    assert result.returncode == 1
    assert "seed archive" in result.stderr
    assert not box.stamp.exists()
