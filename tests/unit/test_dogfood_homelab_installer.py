"""Exercise the Homelab installer's host-side log checks without booting QEMU."""

import re
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/dogfood-homelab-installer.sh"
VERSION = "26.09.2"
BASE = ("homelab", "kubeadm")
ALL = ("argo-workflows", "homelab", "kubeadm", "kubestellar", "mcp")
# The firmware console of a key enrollment boot whose reset hung, as QEMU
# writes it.
HUNG_ENROLLMENT = (
    "Enrolling secure boot keys from directory: \\loader\\keys\\auto\r\n"
    "Custom Secure Boot keys successfully enrolled, rebooting the system now!\r\n"
)


def check_logs(tmp_path, *, cp=ALL, node=BASE, seed=ALL):
    for role, merged in (("cp", cp), ("node", node)):
        creds = "ignition.config.cred"
        if role == "node":
            creds = "bluefin-cluster.passphrase.cred " + creds
        (tmp_path / f"{role}-2-install.ttyS1.log").write_text(
            "PROBE sysinstall=success 0 homelab-install=success\n"
            "PROBE esp-seed=SHA256SUMS "
            + " ".join(f"{name}_{VERSION}.raw.zst" for name in seed)
            + f" \nPROBE esp-creds={creds}\n"
        )
        extra = (
            "PROBE conf role=control-plane passphrase-lines=0\n"
            "PROBE cp-init=active apply=active/success\n"
            "PROBE cp-nodes-ready=2 nodes=2\n"
            if role == "cp"
            else "PROBE conf role=node passphrase-lines=0\n"
            "PROBE node-joined=yes kubelet=active\n"
            "PROBE node-ready=True\n"
        )
        (tmp_path / f"{role}-3-disk.ttyS1.log").write_text(
            f"PROBE os=bluefin-server {VERSION} secureboot=enabled tpm=tpm0\n"
            "PROBE root=xfs ignition=applied\n"
            f"PROBE fetch=success {'-'.join(merged)}-via-seed seed-left=0\n"
            "PROBE merged="
            + " ".join(f"{name}_{VERSION}" for name in merged)
            + " \nPROBE failed=0\n"
            + extra
        )
    checks = SCRIPT.read_text().split("check() {", 1)[1]
    return subprocess.run(
        ["bash", "-c", 'set -euo pipefail; state="$1"; ver="$2"; '
         'installer=fixture.raw; rc=0; fail() { echo "$*" >&2; exit 1; }; '
         "check() {" + checks, "checks", str(tmp_path), VERSION],
        capture_output=True,
        text=True,
    )


def test_control_plane_addons_and_base_only_node_pass(tmp_path):
    result = check_logs(tmp_path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("change", [{"cp": BASE}, {"node": ALL}, {"seed": BASE}])
def test_incorrect_role_or_seed_sets_fail(tmp_path, change):
    result = check_logs(tmp_path, **change)
    assert result.returncode != 0
    assert "FAIL:" in result.stderr


def enroll_finish():
    """The done-regex, timeout and serial install() hands finish for the key
    enrollment boot."""
    call = re.search(r'^ *finish "\$\{role\}-1-enroll" "\$\{VM_PID\}" (.+?) \|\| fail ', SCRIPT.read_text(), re.M)
    assert call
    return shlex.split(call[1])


def finish(tmp_path, *args):
    """finish <args> for cp-1-enroll against a stand-in QEMU that never exits;
    prints finish's status and whether QEMU still runs once it returns."""
    for serial, text in (("ttyS0", HUNG_ENROLLMENT), ("ttyS1", ""), ("ttyS2", "")):
        (tmp_path / f"cp-1-enroll.{serial}").write_text(text)
    body = re.search(r"^finish\(\) \{\n.*?^\}\n", SCRIPT.read_text(), re.M | re.S)[0]
    return subprocess.run(
        ["bash", "-c", 'set -euo pipefail; state="$1"; shift\n' + body
         + "sleep 300 </dev/null >/dev/null 2>&1 &\npid=$!\n"
         "trap 'kill \"${pid}\" 2>/dev/null || true' EXIT\n"
         'rc=0; finish cp-1-enroll "${pid}" "$@" || rc=$?\n'
         'if kill -0 "${pid}" 2>/dev/null; then echo "rc=${rc} qemu running"; else echo "rc=${rc} qemu stopped"; fi\n',
         "finish", str(tmp_path), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_enrollment_marker_ends_a_boot_whose_reset_hangs(tmp_path):
    marker, _, serial = enroll_finish()
    result = finish(tmp_path, marker, "20", serial)
    assert result.stdout.splitlines()[-1] == "rc=0 qemu stopped", result.stderr
    assert marker in (tmp_path / f"cp-1-enroll.{serial}.log").read_text()


def test_without_a_serial_only_the_probe_console_ends_a_boot(tmp_path):
    # The install and disk boots end on their probe's ttyS1 lines.
    marker, _, _ = enroll_finish()
    result = finish(tmp_path, marker, "2")
    assert result.stdout.splitlines()[-1] == "rc=1 qemu stopped"


def test_the_enrollment_checks_the_marker_it_waits_for_on_the_firmware_console():
    marker, _, serial = enroll_finish()
    assert serial == "ttyS0"
    assert f"grep -aq '{marker}' \"${{state}}/${{role}}-1-enroll.{serial}.log\" || fail" in SCRIPT.read_text()
