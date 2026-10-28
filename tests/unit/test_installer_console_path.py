"""The USB installer's console path from "boot the stick" to a login (#311).

Three small units around stock systemd-sysinstall, each with a helper tested
in its own bats file:

- bluefin-installer-disk.service asks for the target disk with each disk's
  size and model (sysinstall v261 shows a by-id name only) and hands it to
  sysinstall, which still checks the fit and asks for "yes";
- bluefin-installer-done.service shows "installed" and when to remove the
  stick, then restarts;
- bluefin-root-password-prompt.service (installed disk, first boot) asks for
  a root password until root has one.

This pins how they are wired, so a cancelled question never lets sysinstall
start and a good install always restarts.
"""


import re
import stat
from pathlib import Path

import pytest

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "files" / "os" / "creds" / "systemd" / "system"
LIBEXEC = ROOT / "files" / "os" / "libexec"
DROPIN = ROOT / "files" / "os" / "systemd" / "system" / "systemd-sysinstall.service.d" / "10-bluefin-installer.conf"
CREDS_ELEMENT = ROOT / "elements" / "bluefin-server" / "os-creds-prov.bst"
DISK = UNITS / "bluefin-installer-disk.service"
DONE = UNITS / "bluefin-installer-done.service"
PROMPT = UNITS / "bluefin-root-password-prompt.service"
HOMELAB = UNITS / "bluefin-homelab-install.service"
HELPERS = ("bluefin-installer-disk", "bluefin-installer-done", "bluefin-root-password-prompt")
SCREENS = (
    "bluefin-home-server-install.service",
    "bluefin-homelab-install.service",
    "bluefin-installer-disk.service",
    "bluefin-installer-done.service",
    "bluefin-installer-secure-boot.service",
)


def test_sysinstall_cannot_start_without_the_disk_question():
    dropin = SystemdFile(DROPIN)
    # Requires= + After=: a cancelled question fails sysinstall's start job.
    assert "bluefin-installer-disk.service" in dropin.words("Unit", "Requires")
    assert "bluefin-installer-disk.service" in dropin.words("Unit", "After")
    disk = SystemdFile(DISK)
    assert "systemd-sysinstall.service" in disk.words("Unit", "Before")
    # After the Secure Boot check and the Homelab node's passphrase prompt,
    # and skipped (not failed) when the check did not pass.
    assert {"bluefin-installer-secure-boot.service", "bluefin-homelab-install.service"} <= set(
        disk.words("Unit", "After")
    )
    assert disk.commands("ExecCondition") == [
        ["/usr/bin/systemctl", "is-active", "--quiet", "bluefin-installer-secure-boot.service"]
    ]


def test_the_chosen_disk_is_sysinstalls_device_argument():
    dropin = SystemdFile(DROPIN)
    [line] = dropin.values("Service", "ExecStart")
    assert line.split()[-1] == "$BLUEFIN_INSTALL_TARGET"
    # Set empty, so with no file (unattended, or the question skipped) it is
    # no argument at all and PID 1 does not log an unset variable.
    assert "BLUEFIN_INSTALL_TARGET=" in dropin.words("Service", "Environment")
    [argv] = dropin.commands()
    assert argv[0] == "systemd-sysinstall" and not argv[-1].startswith("/dev/")
    disk = SystemdFile(DISK)
    runtime = disk.value("Service", "RuntimeDirectory")
    assert f"-/run/{runtime}/sysinstall.env" in dropin.values("Service", "EnvironmentFile")
    # The file outlives the question: its unit stays active until the reboot.
    assert disk.value("Service", "RemainAfterExit") == "yes"
    helper = (LIBEXEC / "bluefin-installer-disk").read_text(encoding="utf-8")
    assert 'out="${RUNTIME_DIRECTORY:?no runtime directory}"' in helper
    assert "printf 'BLUEFIN_INSTALL_TARGET=%s\\n'" in helper


def test_the_disk_list_is_the_one_sysinstall_would_show():
    helper = (LIBEXEC / "bluefin-installer-disk").read_text(encoding="utf-8")
    # The same varlink call as sysinstall v261's acquire_device_list(), so
    # the stick (the device backing /usr) is never offered.
    assert "io.systemd.Repart.ListCandidateDevices '{\"ignoreRoot\":true}'" in helper
    assert "exec:/usr/bin/systemd-repart" in helper


def test_unattended_installs_are_not_asked_for_the_disk():
    # Their sysinstall drop-in credential names the disk in ExecStart=.
    assert "systemd.unit-dropin.systemd-sysinstall.service*" in SystemdFile(DISK).values(
        "Service", "ImportCredential"
    )


def test_the_done_screen_follows_a_good_install_and_restarts():
    dropin = SystemdFile(DROPIN)
    assert dropin.words("Unit", "OnSuccess") == ["bluefin-installer-done.service"]
    # A failed install keeps the machine up with its error on the monitor.
    assert dropin.value("Unit", "FailureAction") == "none"
    done = SystemdFile(DONE)
    assert done.value("Unit", "SuccessAction") == "reboot"
    assert done.value("Unit", "FailureAction") == "reboot"
    assert done.value("Service", "Type") == "oneshot"
    assert done.commands() == [["/usr/libexec/bluefin-installer-done"]]


@pytest.mark.parametrize("name", SCREENS)
def test_the_questions_and_the_done_screen_are_on_the_monitor(name: str):
    unit = SystemdFile(UNITS / name)
    assert unit.value("Service", "StandardInput") == "tty"
    assert unit.value("Service", "StandardOutput") == "tty"
    assert unit.value("Service", "TTYPath") == "/dev/console"


@pytest.mark.parametrize("name", SCREENS)
def test_installer_units_cannot_start_on_an_installed_node(name: str):
    # Pulled in by the installer only: no [Install] section, no preset.
    assert SystemdFile(UNITS / name).sections.get("Install") is None
    presets = " ".join(p.read_text(encoding="utf-8") for p in (ROOT / "files" / "os" / "systemd" / "system-preset").glob("*.preset"))
    assert name.removesuffix(".service") not in presets


def test_the_root_password_prompt_imports_the_credentials_that_answer_it():
    unit = SystemdFile(PROMPT)
    assert set(unit.values("Service", "ImportCredential")) == {
        "passwd.hashed-password.root",
        "passwd.plaintext-password.root",
    }
    assert unit.commands() == [["/usr/libexec/bluefin-root-password-prompt"]]


def test_the_helpers_are_installed_and_executable():
    element = CREDS_ELEMENT.read_text(encoding="utf-8")
    for name in HELPERS:
        script = LIBEXEC / name
        assert f"libexec-src/{name}" in element
        assert f'"%{{install-root}}/usr/libexec/{name}"' in element
        assert script.stat().st_mode & stat.S_IXUSR
        assert script.read_text(encoding="utf-8").startswith("#!/usr/bin/bash\n")


def test_no_helper_ships_a_password():
    for name in HELPERS:
        text = (LIBEXEC / name).read_text(encoding="utf-8")
        assert not re.search(r"\$(?:1|2[abxy]|5|6|y)\$[./0-9A-Za-z]+\$", text), name
        assert "plaintext-password.root=" not in text, name

def test_interactive_prompts_mute_console():
    for path in (DISK, DONE, HOMELAB):
        unit = SystemdFile(path)
        assert "bluefin-installer-mute-console.service" in unit.words("Unit", "Wants"), path.name
        assert "bluefin-installer-mute-console.service" in unit.words("Unit", "After"), path.name
