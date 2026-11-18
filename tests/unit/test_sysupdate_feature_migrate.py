"""Contracts for the systemd-sysupdate deprecated-feature migration.

Release transitions such as Homebrew becoming a first-boot seed drop a feature's
transfer definitions from the release manifest, but leave the operator's
``/etc/sysupdate.d/<feature>.feature.d/`` drop-in behind. Because
systemd-sysupdate requires every enabled feature to be provided by a remote
transfer set, that stale drop-in makes it report "No update needed" and the
node silently stops updating (issue #688).

These tests pin the shipped fix:

* the ``bluefin-sysupdate-migrate`` helper exists, is executable, and lives at
  ``/usr/bin/bluefin-sysupdate-migrate`` in the image
* the one-shot unit runs ahead of the update path (before the timer and the
  update unit itself) and is enabled by preset
* the ``systemd-sysupdate.service`` drop-in runs the helper as
  ``ExecStartPre`` so every update -- timer- or hand-triggered -- is covered
* the helper archives an enabled feature the release no longer ships, keeps a
  feature a transfer still provides, is idempotent, and is a no-op when there
  is nothing to do
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "files" / "os" / "sysupdate-migrate" / "bluefin-sysupdate-migrate"
SERVICE = (
    ROOT / "files" / "os" / "systemd" / "system" / "bluefin-sysupdate-migrate.service"
)
DROPIN = (
    ROOT
    / "files"
    / "os"
    / "systemd"
    / "system"
    / "systemd-sysupdate.service.d"
    / "05-bluefin-prune-deprecated-features.conf"
)
PRESET = (
    ROOT
    / "files"
    / "os"
    / "systemd"
    / "system-preset"
    / "80-bluefin-sysupdate-feature-migrate.preset"
)
ELEMENT = ROOT / "elements" / "bluefin-server" / "os-sysupdate-feature-migrate.bst"
STACK = ROOT / "elements" / "bluefin-server" / "os-stack.bst"


def run_helper(etc_dir: Path, lib_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPT)],
        env={
            **os.environ,
            "SYSUPDATE_ETC_DIR": str(etc_dir),
            "SYSUPDATE_LIB_DIR": str(lib_dir),
        },
        capture_output=True,
        text=True,
        check=False,
    )


# ── Packaging contracts -----------------------------------------------------


def test_helper_is_packaged_and_executable() -> None:
    assert SCRIPT.is_file(), "the migration helper is missing"
    assert os.access(SCRIPT, os.X_OK), (
        "the helper must be executable so the systemd unit can run it"
    )
    element = ELEMENT.read_text(encoding="utf-8")
    assert "path: files/os/sysupdate-migrate" in element, (
        "the helper must ship from files/os/sysupdate-migrate"
    )
    assert "target: /usr/bin" in element, (
        "the helper must land at /usr/bin/bluefin-sysupdate-migrate"
    )
    assert (
        "bluefin-server/os-sysupdate-feature-migrate.bst" in STACK.read_text("utf-8")
    ), "the element must be part of the DDI stack"


def test_migration_unit_runs_before_the_update_path() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    assert "[Unit]" in service and "[Service]" in service and "[Install]" in service
    assert "Description=Bluefin: prune deprecated systemd-sysupdate features" in service
    assert "Type=oneshot" in service, "the migration is a one-shot helper"
    assert "ExecStart=/usr/bin/bluefin-sysupdate-migrate" in service
    assert "Before=systemd-sysupdate.timer" in service, (
        "the migration must run ahead of the update timer"
    )
    assert "Before=systemd-sysupdate.service" in service
    assert "WantedBy=multi-user.target" in service, (
        "the unit must be enabled so it runs at boot"
    )


def test_update_unit_prunes_features_before_every_update() -> None:
    dropin = DROPIN.read_text(encoding="utf-8")
    assert "[Service]" in dropin
    assert "ExecStartPre=/usr/bin/bluefin-sysupdate-migrate" in dropin, (
        "the prune must run before systemd-sysupdate itself, so timer- and "
        "hand-triggered updates are both covered"
    )


def test_migration_unit_is_enabled_by_preset() -> None:
    preset = PRESET.read_text(encoding="utf-8")
    assert preset == "enable bluefin-sysupdate-migrate.service\n"


# ── Behavioural contracts ---------------------------------------------------


def _make_tree(tmp_path: Path, provided: list[str], enabled: list[str]) -> tuple[Path, Path]:
    etc = tmp_path / "etc" / "sysupdate.d"
    lib = tmp_path / "usr" / "lib" / "sysupdate.d"
    etc.mkdir(parents=True)
    lib.mkdir(parents=True)
    if provided:
        transfers = "\n".join(f"Features={name}" for name in provided)
        (lib / "10-example.transfer").write_text(
            "[Transfer]\n\n" + transfers + "\n\n[Source]\nType=url-file\n",
            encoding="utf-8",
        )
    for name in enabled:
        (etc / f"{name}.feature.d").mkdir()
    return etc, lib


def test_orphaned_feature_is_archived_and_provided_one_kept(tmp_path: Path) -> None:
    etc, lib = _make_tree(tmp_path, provided=["k0s"], enabled=["k0s", "homebrew"])
    result = run_helper(etc, lib)
    assert result.returncode == 0, result.stderr
    assert (etc / "homebrew.feature.d.disabled").is_dir(), (
        "a feature no transfer provides must be archived"
    )
    assert (etc / "k0s.feature.d").is_dir(), (
        "a feature a transfer still provides must be left in place"
    )
    assert "not shipped in this release" in result.stdout


def test_helper_is_idempotent_on_rerun(tmp_path: Path) -> None:
    etc, lib = _make_tree(tmp_path, provided=[], enabled=["homebrew"])
    first = run_helper(etc, lib)
    assert first.returncode == 0
    assert (etc / "homebrew.feature.d.disabled").is_dir()
    second = run_helper(etc, lib)
    assert second.returncode == 0, second.stderr
    assert (etc / "homebrew.feature.d.disabled").is_dir(), (
        "the archived drop-in must survive a second run untouched"
    )
    assert not (etc / "homebrew.feature.d.disabled.disabled").exists(), (
        "a second run must not archive the drop-in again"
    )
    assert "no deprecated sysupdate features found" in second.stdout


def test_no_orphaned_feature_is_a_noop(tmp_path: Path) -> None:
    etc, lib = _make_tree(tmp_path, provided=["k0s", "homebrew"], enabled=["k0s", "homebrew"])
    result = run_helper(etc, lib)
    assert result.returncode == 0, result.stderr
    assert (etc / "k0s.feature.d").is_dir()
    assert (etc / "homebrew.feature.d").is_dir()
    assert "no deprecated sysupdate features found" in result.stdout


def test_missing_etc_directory_is_a_noop(tmp_path: Path) -> None:
    lib = tmp_path / "usr" / "lib" / "sysupdate.d"
    lib.mkdir(parents=True)
    etc = tmp_path / "does-not-exist"
    result = run_helper(etc, lib)
    assert result.returncode == 0, result.stderr
    assert "nothing to do" in result.stdout


def test_existing_archive_is_not_clobbered(tmp_path: Path) -> None:
    # If an operator re-enabled a feature while the archived drop-in is still
    # present, the helper must not move the new drop-in over the archive.
    etc, lib = _make_tree(tmp_path, provided=[], enabled=["homebrew"])
    (etc / "homebrew.feature.d.disabled").mkdir()
    result = run_helper(etc, lib)
    assert result.returncode == 0, result.stderr
    assert "already archived" in result.stderr
    assert (etc / "homebrew.feature.d.disabled").is_dir()
    assert not (etc / "homebrew.feature.d.disabled" / "homebrew.feature.d").exists()


def test_features_list_accepts_spaces_and_commas(tmp_path: Path) -> None:
    etc, lib = _make_tree(tmp_path, provided=[], enabled=["k0s", "homebrew"])
    # A single transfer listing both features, mixed separators.
    (lib / "10-example.transfer").write_text(
        "[Transfer]\nFeatures=k0s, homebrew\n[Source]\nType=url-file\n",
        encoding="utf-8",
    )
    result = run_helper(etc, lib)
    assert result.returncode == 0, result.stderr
    assert (etc / "k0s.feature.d").is_dir()
    assert (etc / "homebrew.feature.d").is_dir()

