"""Unit tests for systemd-sysupdate reboot coordination.

Asserts contracts for systemd-sysupdate-reboot drop-in coordination strategies
(immediate, maintenance window, lock-based) and verifies that Kubernetes hosts
gate reboots via real service liveness rather than non-existent sentinels,
without colliding with upstream systemd units.
"""

import configparser
import os
from pathlib import Path
import subprocess
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_SYSTEM_DIR = REPO_ROOT / "files" / "os" / "systemd" / "system"
SYSTEMD_PRESET_DIR = REPO_ROOT / "files" / "os" / "systemd" / "system-preset"
SYSUPDATE_DROPIN_DIR = (
    REPO_ROOT / "files" / "os" / "systemd" / "systemd-sysupdate.service.d"
)
REBOOT_DROPIN_DIR = (
    REPO_ROOT / "files" / "os" / "systemd" / "systemd-sysupdate-reboot.service.d"
)
ELEMENTS_DIR = REPO_ROOT / "elements" / "bluefin-server"

REBOOT_DROPIN = REBOOT_DROPIN_DIR / "reboot-coordination.conf"
REBOOT_PRESET = SYSTEMD_PRESET_DIR / "80-enable-sysupdate-reboot.preset"
REBOOT_ELEMENT = ELEMENTS_DIR / "os-sysupdate-reboot.bst"
OS_STACK = ELEMENTS_DIR / "os-stack.bst"
KURED_HOOK = SYSUPDATE_DROPIN_DIR / "kured-hook.conf"


def load_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str
    parser.read_string(path.read_text())
    return parser


def test_reboot_coordination_files_exist():
    assert REBOOT_DROPIN.is_file(), "reboot-coordination.conf drop-in is missing"
    assert REBOOT_PRESET.is_file(), "80-enable-sysupdate-reboot.preset is missing"
    assert REBOOT_ELEMENT.is_file(), "os-sysupdate-reboot.bst element is missing"


def test_no_upstream_unit_collision():
    # systemd-sysupdate-reboot.service and .timer are shipped by upstream systemd
    # in freedesktop-sdk.bst:components/systemd.bst (/usr/lib/systemd/system/).
    # Shipping full unit files in files/os/systemd/system collides with upstream.
    service_file = SYSTEMD_SYSTEM_DIR / "systemd-sysupdate-reboot.service"
    timer_file = SYSTEMD_SYSTEM_DIR / "systemd-sysupdate-reboot.timer"
    assert not service_file.exists(), (
        "systemd-sysupdate-reboot.service must not exist in files/os/systemd/system "
        "to avoid colliding with upstream systemd.bst units"
    )
    assert not timer_file.exists(), (
        "systemd-sysupdate-reboot.timer must not exist in files/os/systemd/system "
        "to avoid colliding with upstream systemd.bst units"
    )


def test_reboot_dropin_contract():
    parser = load_ini(REBOOT_DROPIN)
    assert parser.has_section("Unit")
    assert parser.has_section("Service")

    content = REBOOT_DROPIN.read_text()
    # Verify lock-based coordination sentinels
    assert "ConditionPathExists=!/run/reboot-lock" in content
    assert "ConditionPathExists=!/etc/reboot-lock" in content

    # Ensure imaginary sentinels are NOT referenced
    assert "kured-active" not in content, (
        "Condition must not reference /run/kured-active which nothing creates"
    )

    # Verify Kubernetes gating
    service = parser["Service"]
    exec_condition = service.get("ExecCondition", "")
    assert "systemctl is-active" in exec_condition
    assert "k0scontroller.service" in exec_condition
    assert "kubelet.service" in exec_condition


def test_reboot_preset_enables_timer():
    content = REBOOT_PRESET.read_text()
    assert "enable systemd-sysupdate-reboot.timer" in content
    # systemd preset files are evaluated in lexicographic filename order across
    # directories, earliest match wins. freedesktop-sdk ships 90-sysupdate.preset
    # which disables the timer; our preset must sort before 90-sysupdate.preset.
    assert REBOOT_PRESET.name < "90-sysupdate.preset", (
        f"{REBOOT_PRESET.name} must sort before 90-sysupdate.preset to override FSDK's disable"
    )


def test_exec_condition_kubernetes_interlock_logic(tmp_path):
    parser = load_ini(REBOOT_DROPIN)
    exec_condition = parser["Service"]["ExecCondition"]
    # Extract command passed to sh -c or run command directly
    assert exec_condition.startswith("/usr/bin/sh -c ")
    cmd_str = exec_condition[len("/usr/bin/sh -c ") :].strip("'\"")

    # Create mock systemctl
    mock_systemctl = tmp_path / "systemctl"
    mock_env = {**os.environ, "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}"}

    # Case 1: k0scontroller is active -> ExecCondition must fail (exit 1)
    mock_systemctl.write_text("""#!/bin/sh
for arg in "$@"; do
    if [ "$arg" = "k0scontroller.service" ]; then
        exit 0
    fi
done
exit 3
""")
    mock_systemctl.chmod(0o755)

    proc = subprocess.run(["sh", "-c", cmd_str], env=mock_env)
    assert proc.returncode != 0, (
        "ExecCondition should fail (exit non-zero) when k0scontroller is active, "
        "preventing uncoordinated reboot of Kubernetes node"
    )

    # Case 2: kubelet is active -> ExecCondition must fail (exit 1)
    mock_systemctl.write_text("""#!/bin/sh
for arg in "$@"; do
    if [ "$arg" = "kubelet.service" ]; then
        exit 0
    fi
done
exit 3
""")
    mock_systemctl.chmod(0o755)

    proc = subprocess.run(["sh", "-c", cmd_str], env=mock_env)
    assert proc.returncode != 0, (
        "ExecCondition should fail (exit non-zero) when kubelet is active"
    )

    # Case 3: No Kubernetes service is active -> ExecCondition must succeed (exit 0)
    mock_systemctl.write_text("""#!/bin/sh
exit 3
""")
    mock_systemctl.chmod(0o755)

    proc = subprocess.run(["sh", "-c", cmd_str], env=mock_env)
    assert proc.returncode == 0, (
        "ExecCondition should succeed (exit 0) when no Kubernetes service is active, "
        "allowing scheduled reboot on single-node / non-Kubernetes hosts"
    )


def test_reboot_coordination_packaged_in_elements():
    # Verify os-sysupdate-reboot.bst
    element_yaml = yaml.safe_load(REBOOT_ELEMENT.read_text())
    assert element_yaml.get("kind") == "import"
    assert element_yaml.get("config", {}).get("target") == (
        "/usr/lib/systemd/system/systemd-sysupdate-reboot.service.d"
    )
    sources = element_yaml.get("sources", [])
    assert any(
        s.get("path") == "files/os/systemd/systemd-sysupdate-reboot.service.d"
        for s in sources
    )

    # Verify os-stack.bst includes the element
    stack_yaml = yaml.safe_load(OS_STACK.read_text())
    depends = stack_yaml.get("depends", [])
    assert "bluefin-server/os-sysupdate-reboot.bst" in depends
    assert "bluefin-server/os-kured-hook.bst" in depends

    # Verify kured hook creates /run/reboot-required
    assert KURED_HOOK.is_file()
    assert "touch /run/reboot-required" in KURED_HOOK.read_text()
