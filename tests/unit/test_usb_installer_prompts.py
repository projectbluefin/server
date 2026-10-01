"""The USB installer asks as little as possible and reboots on its own.

Every question the installer used to ask on real hardware is answered ahead of
time, and the "Press any key to proceed" hang after a successful install is
gone. The settings that do that live in three files, so they are pinned here:
the sysinstall drop-in, the installer kernel command line, and the dogfood
script that replays the same ExecStart= unattended.
"""

from __future__ import annotations

import re
from pathlib import Path

from _systemd import SystemdFile, preset

ROOT = Path(__file__).resolve().parents[2]
DROPIN = (
    ROOT
    / "files"
    / "os"
    / "systemd"
    / "system"
    / "systemd-sysinstall.service.d"
    / "10-bluefin-installer.conf"
)
BOOT_ELEMENT = ROOT / "elements" / "oci" / "bluefin-server-boot.bst"
DOGFOOD = ROOT / "scripts" / "dogfood-installer.sh"


def install_argv() -> list[str]:
    commands = SystemdFile(DROPIN).commands()
    # The drop-in resets ExecStart= before setting its own.
    assert len(commands) == 1, commands
    return commands[0]


def option(argv: list[str], name: str) -> str | None:
    for word in argv:
        key, _, value = word.partition("=")
        if key == name:
            return value
    return None


def test_the_disk_is_erased_without_a_keep_or_erase_question():
    # The summary's "yes" stays the one confirmation; --erase=yes only removes
    # the separate keep/erase prompt, which has no safe unattended answer.
    assert option(install_argv(), "--erase") == "yes"


def test_sysinstall_does_not_reboot_itself_so_no_key_press_is_awaited():
    # sysinstall's own reboot calls any_key_to_proceed() first, which looks
    # like a halt on a machine nobody is sitting at.
    assert option(install_argv(), "--reboot") == "no"


def test_the_service_manager_reboots_when_the_install_succeeds():
    unit = SystemdFile(DROPIN)
    assert unit.value("Unit", "SuccessAction") == "reboot"
    # SuccessAction= only fires when the unit goes inactive. From systemd v262
    # upstream's unit is Type=oneshot with RemainAfterExit=yes, which would
    # leave it "active (exited)" after a good install and never reboot.
    assert unit.value("Service", "RemainAfterExit") == "no"


def test_the_installer_is_still_registered_in_the_firmware_boot_menu():
    assert option(install_argv(), "--variables") == "yes"


def test_the_keymap_is_answered_by_a_credential_on_the_kernel_command_line():
    # systemd-firstboot only prompts for values it has no credential for, and
    # sysinstall copies the keymap to the target.
    cmdline = BOOT_ELEMENT.read_text(encoding="utf-8").split("installer-cmdline:")[1]
    cmdline = cmdline.split("\nconfig:")[0]
    assert "systemd.set_credential=firstboot.keymap:us" in cmdline


def test_dogfood_only_adds_what_the_image_dropin_does_not_pass():
    # The unattended run re-uses the drop-in's ExecStart=, so repeating its
    # flags here would let the two drift apart unnoticed.
    default = re.search(
        r'install_args="\$\{DOGFOOD_SYSINSTALL_ARGS:-(.*?)\}"',
        DOGFOOD.read_text(encoding="utf-8"),
    )
    assert default is not None
    assert default[1].split() == ["--confirm=no"]


PROMPT_UNIT = (
    ROOT / "files" / "os" / "creds" / "systemd" / "system" / "bluefin-root-password-prompt.service"
)
PRESETS = ROOT / "files" / "os" / "systemd" / "system-preset"


def core_cmdline() -> str:
    text = BOOT_ELEMENT.read_text(encoding="utf-8")
    return text.split("installer-core-cmdline:")[1].split("\nconfig:")[0]


def test_the_installed_disk_asks_for_a_root_password_on_first_boot():
    # Root ships locked and the stock firstboot prompt is removed for headless
    # nodes, so without this a USB-installed machine has no way to log in. The
    # Core profile passes the credential through BLUEFIN_INSTALL_ROOT_PROMPT.
    assert "$BLUEFIN_INSTALL_ROOT_PROMPT" in DROPIN.read_text(encoding="utf-8")
    prefix = "systemd.setenv=BLUEFIN_INSTALL_ROOT_PROMPT="
    [credential] = [w[len(prefix):] for w in core_cmdline().split() if w.startswith(prefix)]
    assert credential == "--set-credential=bluefin.prompt-root-password:1"
    name = credential.partition("=")[2].partition(":")[0]
    unit = SystemdFile(PROMPT_UNIT)
    assert unit.value("Unit", "ConditionCredential") == name
    assert unit.value("Unit", "ConditionFirstBoot") == "yes"
    [argv] = unit.commands()
    assert argv[0] == "systemd-firstboot" and "--prompt-root-password" in argv
    assert preset("bluefin-root-password-prompt.service", PRESETS.glob("*.preset")) == "enable"




def test_the_root_password_prompt_is_on_the_monitor_not_the_serial_console():
    # The disk UKI puts console=ttyS0 last, so /dev/console is the serial port.
    unit = SystemdFile(PROMPT_UNIT)
    assert unit.value("Service", "StandardInput") == "tty"
    assert unit.value("Service", "TTYPath") == "/dev/tty1"
