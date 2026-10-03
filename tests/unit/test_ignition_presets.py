"""Apply Ignition enablement to a populated root using real systemctl offline."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = ROOT / "files/initrd-ignition/usr"
SCRIPT = PAYLOAD / "libexec/bluefin-ignition-presets"


@pytest.fixture
def sysroot(tmp_path):
    if shutil.which("systemctl") is None:
        if os.environ.get("CI") == "true":
            pytest.fail("systemctl is required for offline preset tests")
        pytest.skip("systemctl is not installed")
    (tmp_path / "etc/systemd/system").mkdir(parents=True)
    (tmp_path / "etc/systemd/system-preset").mkdir()
    (tmp_path / "usr/lib/systemd/system").mkdir(parents=True)
    (tmp_path / "usr/lib/systemd/system-preset").mkdir()
    # This is a subsequent boot; PID 1 will not apply presets automatically.
    (tmp_path / "etc/machine-id").write_text("0123456789abcdef0123456789abcdef\n")
    (tmp_path / "usr/lib/systemd/system-preset/80-vendor.preset").write_text("disable *\n")
    return tmp_path


def unit(root, name):
    path = root / "usr/lib/systemd/system" / name
    path.write_text("[Service]\nExecStart=/bin/true\n[Install]\nWantedBy=multi-user.target\n")


def preset(root, contents):
    (root / "etc/systemd/system-preset/20-ignition.preset").write_text(contents)


def enabled_link(root, name):
    return root / "etc/systemd/system/multi-user.target.wants" / name


def apply(root):
    return subprocess.run([str(SCRIPT), str(root)], capture_output=True, text=True)


def test_applies_enable_and_disable_on_repeated_boots(sysroot):
    for name in ("bluefin-sysext-fetch.service", "disabled.service", "local.service", "untouched.service"):
        unit(sysroot, name)
    subprocess.run(
        ["systemctl", f"--root={sysroot}", "enable", "disabled.service", "local.service"],
        check=True, capture_output=True,
    )
    preset(sysroot, "enable bluefin-sysext-fetch.service\ndisable disabled.service\n")
    for _ in range(2):
        result = apply(sysroot)
        assert result.returncode == 0, result.stderr
        assert enabled_link(sysroot, "bluefin-sysext-fetch.service").is_symlink()
        assert not enabled_link(sysroot, "disabled.service").is_symlink()
        # A global preset-all would incorrectly disable this local choice.
        assert enabled_link(sysroot, "local.service").is_symlink()
        assert not enabled_link(sysroot, "untouched.service").is_symlink()


def test_template_instances_and_preset_precedence(sysroot):
    unit(sysroot, "worker@.service")
    unit(sysroot, "override.service")
    preset(sysroot, "# Ignition template instances\nenable worker@.service one two\nenable override.service\n")
    (sysroot / "etc/systemd/system-preset/00-local.preset").write_text("disable override.service\n")
    result = apply(sysroot)
    assert result.returncode == 0, result.stderr
    assert enabled_link(sysroot, "worker@one.service").is_symlink()
    assert enabled_link(sysroot, "worker@two.service").is_symlink()
    assert not enabled_link(sysroot, "override.service").is_symlink()


@pytest.mark.parametrize("contents", [None, "", "# no unit selections\n\n"])
def test_no_preset_is_a_noop(sysroot, contents):
    unit(sysroot, "local.service")
    subprocess.run(["systemctl", f"--root={sysroot}", "enable", "local.service"], check=True, capture_output=True)
    if contents is not None:
        preset(sysroot, contents)
    result = apply(sysroot)
    assert result.returncode == 0, result.stderr
    assert enabled_link(sysroot, "local.service").is_symlink()


def test_missing_units_are_ignored_like_first_boot_presets(sysroot):
    preset(sysroot, "enable missing.service\n")
    result = apply(sysroot)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("fail_command", ["list-unit-files", "preset"])
def test_systemctl_failure_is_not_hidden(sysroot, monkeypatch, fail_command):
    preset(sysroot, "enable example.service\n")
    stub = sysroot / "bin"
    stub.mkdir()
    tool = stub / "systemctl"
    tool.write_text(
        f'#!/bin/sh\n[ "$2" = "{fail_command}" ] && exit 42\n'
        'echo "example.service disabled disabled"\n'
    )
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{stub}:{os.environ['PATH']}")
    assert apply(sysroot).returncode == 42


def test_a_changed_config_replaces_previous_rules(sysroot):
    unit(sysroot, "changed.service")
    preset(sysroot, "enable changed.service\n")
    assert apply(sysroot).returncode == 0
    service = SystemdFile(PAYLOAD / "lib/systemd/system/ignition-files.service")
    # Run the actual pre-files cleanup against the test root, then emulate
    # Ignition's append-only writer with the next boot's new selection.
    for command in service.commands("ExecStartPre"):
        subprocess.run([arg.replace("/sysroot", str(sysroot)) for arg in command], check=True)
    with (sysroot / "etc/systemd/system-preset/20-ignition.preset").open("a") as stream:
        stream.write("disable changed.service\n")
    result = apply(sysroot)
    assert result.returncode == 0, result.stderr
    assert not enabled_link(sysroot, "changed.service").is_symlink()


def test_masked_units_stay_masked(sysroot):
    unit(sysroot, "masked.service")
    (sysroot / "etc/systemd/system/masked.service").symlink_to("/dev/null")
    preset(sysroot, "enable masked.service\n")
    result = apply(sysroot)
    assert result.returncode == 0, result.stderr
    assert (sysroot / "etc/systemd/system/masked.service").readlink() == Path("/dev/null")
    assert not enabled_link(sysroot, "masked.service").is_symlink()


def test_presets_run_after_files_and_before_switch_root():
    service = SystemdFile(PAYLOAD / "lib/systemd/system/ignition-files.service")
    assert service.value("Service", "ExecStartPost") == "/usr/libexec/bluefin-ignition-presets /sysroot"
    assert "initrd-cleanup.service" in service.words("Unit", "Before")
    assert service.value("Unit", "OnFailure") == "emergency.target"
