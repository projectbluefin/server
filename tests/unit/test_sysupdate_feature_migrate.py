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
  update unit itself) and is enabled by a /usr wants symlink
* the ``systemd-sysupdate.service`` drop-in runs the helper as
  ``ExecStartPre`` so every update -- timer- or hand-triggered -- is covered
* the helper archives an enabled feature the release no longer ships, keeps a
  feature a transfer still provides, is idempotent, and is a no-op when there
  is nothing to do
"""

import os
import subprocess
from pathlib import Path

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
USR = ROOT / "elements" / "oci" / "bluefin-server-usr.bst"
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
    assert "ExecStartPre=-/usr/bin/bluefin-sysupdate-migrate" in dropin, (
        "the prune must run before systemd-sysupdate itself, so timer- and "
        "hand-triggered updates are both covered"
    )


def test_migration_unit_is_enabled_in_usr() -> None:
    # Presets only apply on first boot; updated nodes need the /usr link.
    usr = USR.read_text(encoding="utf-8")
    assert "multi-user.target.wants/bluefin-sysupdate-migrate.service" in usr


# ── Behavioural contracts ---------------------------------------------------


def _make_tree(
    tmp_path: Path, remote: list[str], local: dict[str, str], enabled: list[str]
) -> tuple[Path, Path]:
    """Local transfers (feature -> file pattern) against a file:// remote."""
    etc = tmp_path / "etc" / "sysupdate.d"
    lib = tmp_path / "usr" / "lib" / "sysupdate.d"
    rel = tmp_path / "release"
    for d in (etc, lib, rel):
        d.mkdir(parents=True)
    (rel / "SHA256SUMS").write_text(
        "".join(f"{'0' * 64} *{name}\n" for name in remote), encoding="utf-8"
    )
    for i, (feature, pattern) in enumerate(local.items()):
        (lib / f"{10 + i}-{feature}.transfer").write_text(
            f"[Transfer]\nFeatures={feature}\n\n[Source]\nType=url-file\n"
            f"Path=file://{rel}/\nMatchPattern={pattern}\n",
            encoding="utf-8",
        )
    for name in enabled:
        (etc / f"{name}.feature.d").mkdir()
    return etc, lib


def test_feature_dropped_from_remote_is_archived_though_local_transfer_exists(
    tmp_path: Path,
) -> None:
    # The stalled node still ships the homebrew transfer locally; only the
    # remote release dropped it.
    etc, lib = _make_tree(
        tmp_path,
        remote=["k0s_1.2.raw.zst", "bluefin_1.2.raw"],
        local={"k0s": "k0s_@v.raw.zst", "homebrew": "homebrew_@v.raw.zst"},
        enabled=["k0s", "homebrew"],
    )
    result = run_helper(etc, lib)
    assert result.returncode == 0, result.stderr
    assert (etc / "homebrew.feature.d.disabled").is_dir()
    assert (etc / "k0s.feature.d").is_dir()
    assert "not in the release manifest" in result.stdout


def test_feature_without_local_transfer_is_archived(tmp_path: Path) -> None:
    etc, lib = _make_tree(tmp_path, remote=[], local={}, enabled=["homebrew"])
    assert run_helper(etc, lib).returncode == 0
    assert (etc / "homebrew.feature.d.disabled").is_dir()


def test_unreachable_manifest_leaves_features_alone(tmp_path: Path) -> None:
    etc, lib = _make_tree(
        tmp_path, remote=[], local={"homebrew": "homebrew_@v.raw.zst"}, enabled=["homebrew"]
    )
    for f in (tmp_path / "release").iterdir():
        f.unlink()
    result = run_helper(etc, lib)
    assert result.returncode == 0, result.stderr
    assert (etc / "homebrew.feature.d").is_dir(), "offline must never archive"


def test_non_manifest_manifest_leaves_features_alone(tmp_path: Path) -> None:
    # A 200 response that is not a SHA256SUMS (a captive portal or proxy error
    # page) must never archive a working feature: it is treated as
    # unreachable. `curl -f` only fails on HTTP >= 400, so a valid-looking
    # status with an HTML body would otherwise set found=no for every transfer.
    etc, lib = _make_tree(
        tmp_path, remote=[], local={"homebrew": "homebrew_@v.raw.zst"}, enabled=["homebrew"]
    )
    (tmp_path / "release" / "SHA256SUMS").write_text(
        "<html><title>Captive Login</title></html>\n", encoding="utf-8"
    )
    result = run_helper(etc, lib)
    assert result.returncode == 0, result.stderr
    assert (etc / "homebrew.feature.d").is_dir(), "a non-manifest 200 must never archive"


def test_helper_is_idempotent_on_rerun(tmp_path: Path) -> None:
    etc, lib = _make_tree(tmp_path, remote=[], local={}, enabled=["homebrew"])
    assert run_helper(etc, lib).returncode == 0
    second = run_helper(etc, lib)
    assert second.returncode == 0, second.stderr
    assert (etc / "homebrew.feature.d.disabled").is_dir()
    assert not (etc / "homebrew.feature.d.disabled.disabled").exists()
    assert "no deprecated sysupdate features found" in second.stdout


def test_no_orphaned_feature_is_a_noop(tmp_path: Path) -> None:
    etc, lib = _make_tree(
        tmp_path,
        remote=["k0s_1.raw.zst", "homebrew_1.raw.zst"],
        local={"k0s": "k0s_@v.raw.zst", "homebrew": "homebrew_@v.raw.zst"},
        enabled=["k0s", "homebrew"],
    )
    result = run_helper(etc, lib)
    assert result.returncode == 0, result.stderr
    assert (etc / "k0s.feature.d").is_dir()
    assert (etc / "homebrew.feature.d").is_dir()
    assert "no deprecated sysupdate features found" in result.stdout


def test_missing_etc_directory_is_a_noop(tmp_path: Path) -> None:
    lib = tmp_path / "usr" / "lib" / "sysupdate.d"
    lib.mkdir(parents=True)
    result = run_helper(tmp_path / "does-not-exist", lib)
    assert result.returncode == 0, result.stderr
    assert "nothing to do" in result.stdout


def test_existing_archive_is_not_clobbered(tmp_path: Path) -> None:
    etc, lib = _make_tree(tmp_path, remote=[], local={}, enabled=["homebrew"])
    (etc / "homebrew.feature.d.disabled").mkdir()
    result = run_helper(etc, lib)
    assert result.returncode == 0, result.stderr
    assert "already archived" in result.stderr
    assert not (etc / "homebrew.feature.d.disabled" / "homebrew.feature.d").exists()


def test_features_list_accepts_spaces_and_commas(tmp_path: Path) -> None:
    etc, lib = _make_tree(
        tmp_path, remote=["x_1.raw"], local={}, enabled=["k0s", "homebrew"]
    )
    (lib / "10-example.transfer").write_text(
        f"[Transfer]\nFeatures=k0s, homebrew\n[Source]\nType=url-file\n"
        f"Path=file://{tmp_path}/release/\nMatchPattern=x_@v.raw\n",
        encoding="utf-8",
    )
    result = run_helper(etc, lib)
    assert result.returncode == 0, result.stderr
    assert (etc / "k0s.feature.d").is_dir()
    assert (etc / "homebrew.feature.d").is_dir()


def test_archived_feature_is_restored_when_release_ships_it_again(
    tmp_path: Path,
) -> None:
    etc, lib = _make_tree(
        tmp_path,
        remote=["zfs_1.3.raw.zst"],
        local={"zfs": "zfs_@v.raw.zst"},
        enabled=[],
    )
    (etc / "zfs.feature.d.disabled").mkdir()
    result = run_helper(etc, lib)
    assert result.returncode == 0, result.stderr
    assert (etc / "zfs.feature.d").is_dir()
    assert not (etc / "zfs.feature.d.disabled").exists()
    assert "restored" in result.stdout


def test_archived_feature_stays_archived_while_release_lacks_it(
    tmp_path: Path,
) -> None:
    etc, lib = _make_tree(
        tmp_path, remote=[], local={"zfs": "zfs_@v.raw.zst"}, enabled=[]
    )
    (etc / "zfs.feature.d.disabled").mkdir()
    assert run_helper(etc, lib).returncode == 0
    assert (etc / "zfs.feature.d.disabled").is_dir()
    assert not (etc / "zfs.feature.d").exists()


def test_manifest_is_fetched_once_per_url(tmp_path: Path) -> None:
    etc, lib = _make_tree(
        tmp_path,
        remote=["a_1.raw"],
        local={"a": "a_@v.raw", "b": "b_@v.raw", "c": "c_@v.raw"},
        enabled=["a"],
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "curl.log"
    curl = bindir / "curl"
    curl.write_text(f'#!/bin/sh\necho x >> {log}\nexec /usr/bin/curl "$@"\n')
    curl.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "SYSUPDATE_ETC_DIR": str(etc),
        "SYSUPDATE_LIB_DIR": str(lib),
    }
    subprocess.run([str(SCRIPT)], env=env, check=True, capture_output=True)
    assert len(log.read_text().splitlines()) == 1
