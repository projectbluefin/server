"""Unit tests for systemd-sysupdate reboot coordination.

Asserts contracts for systemd-sysupdate-reboot service, timer, presets,
and drop-in coordination strategies (immediate, maintenance window, lock-based)
while ensuring Kured reboot paths are preserved without collisions.
"""

import configparser
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_SYSTEM_DIR = REPO_ROOT / "files" / "os" / "systemd" / "system"
SYSTEMD_PRESET_DIR = REPO_ROOT / "files" / "os" / "systemd" / "system-preset"
SYSUPDATE_DROPIN_DIR = (
    REPO_ROOT / "files" / "os" / "systemd" / "systemd-sysupdate.service.d"
)
ELEMENTS_DIR = REPO_ROOT / "elements" / "bluefin-server"
OS_STACK = ELEMENTS_DIR / "os-stack.bst"

REBOOT_SERVICE = SYSTEMD_SYSTEM_DIR / "systemd-sysupdate-reboot.service"
REBOOT_TIMER = SYSTEMD_SYSTEM_DIR / "systemd-sysupdate-reboot.timer"
REBOOT_PRESET = SYSTEMD_PRESET_DIR / "zz-enable-sysupdate-reboot.preset"
KURED_HOOK = SYSUPDATE_DROPIN_DIR / "kured-hook.conf"


def load_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str
    parser.read_string(path.read_text())
    return parser


def test_reboot_service_and_timer_exist():
    assert REBOOT_SERVICE.is_file(), "systemd-sysupdate-reboot.service is missing"
    assert REBOOT_TIMER.is_file(), "systemd-sysupdate-reboot.timer is missing"
    assert REBOOT_PRESET.is_file(), "zz-enable-sysupdate-reboot.preset is missing"


def test_reboot_service_contract():
    parser = load_ini(REBOOT_SERVICE)
    assert parser.has_section("Unit")
    assert parser.has_section("Service")
    assert parser.has_section("Install")

    unit = parser["Unit"]
    assert unit.get("ConditionVirtualization") == "!container"

    # Verify lock-based coordination and kured coordination guards
    content = REBOOT_SERVICE.read_text()
    assert "ConditionPathExists=!/run/reboot-lock" in content
    assert "ConditionPathExists=!/etc/reboot-lock" in content
    assert "ConditionPathExists=!/run/kured-active" in content

    service = parser["Service"]
    assert service.get("Type") == "oneshot"
    assert service.get("ExecStart") == "/usr/bin/systemd-sysupdate reboot"

    install = parser["Install"]
    assert install.get("Also") == "systemd-sysupdate-reboot.timer"


def test_reboot_timer_contract():
    parser = load_ini(REBOOT_TIMER)
    assert parser.has_section("Unit")
    assert parser.has_section("Timer")
    assert parser.has_section("Install")

    unit = parser["Unit"]
    assert unit.get("ConditionVirtualization") == "!container"

    timer = parser["Timer"]
    # Maintenance window scheduling
    assert timer.get("OnCalendar") == "*-*-* 04:10:00"
    assert timer.get("RandomizedDelaySec") == "30min"
    assert timer.get("Persistent") == "true"

    install = parser["Install"]
    assert install.get("WantedBy") == "timers.target"


def test_reboot_preset_enables_timer_by_default():
    content = REBOOT_PRESET.read_text()
    assert "enable systemd-sysupdate-reboot.timer" in content


def test_kured_hook_preserved_in_sysupdate_service():
    assert KURED_HOOK.is_file(), "kured-hook.conf is missing"
    content = KURED_HOOK.read_text()
    assert "touch /run/reboot-required" in content


def test_reboot_coordination_packaged_in_elements():
    # systemd unit files packaging
    system_element = (ELEMENTS_DIR / "os-k0s-first-boot.bst").read_text()
    assert "path: files/os/systemd/system" in system_element
    assert "target: /usr/lib/systemd/system" in system_element

    # systemd preset files packaging
    preset_element = (ELEMENTS_DIR / "os-sshd-preset.bst").read_text()
    assert "path: files/os/systemd/system-preset" in preset_element
    assert "target: /usr/lib/systemd/system-preset" in preset_element

    # kured hook packaging
    kured_element = (ELEMENTS_DIR / "os-kured-hook.bst").read_text()
    assert "path: files/os/systemd/systemd-sysupdate.service.d" in kured_element
    assert "target: /usr/lib/systemd/system/systemd-sysupdate.service.d" in kured_element

    # os-stack packaging
    stack_content = OS_STACK.read_text()
    assert "bluefin-server/os-k0s-first-boot.bst" in stack_content
    assert "bluefin-server/os-sshd-preset.bst" in stack_content
    assert "bluefin-server/os-kured-hook.bst" in stack_content
