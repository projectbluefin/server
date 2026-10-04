"""Exercise the Homelab installer's host-side log checks without booting QEMU."""

from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/dogfood-homelab-installer.sh"
VERSION = "26.09.2"
BASE = ("homelab", "kubeadm")
ALL = ("argo-workflows", "homelab", "kubeadm", "kubestellar", "mcp")


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
