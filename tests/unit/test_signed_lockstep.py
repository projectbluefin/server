"""Contracts for signed downloads, version-locked sysexts and HTTP-boot Ignition."""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SYSUPDATE = ROOT / "files" / "os" / "sysupdate.d"
BOOT = ROOT / "elements" / "oci" / "bluefin-server-boot.bst"
KEYS = ROOT / "elements" / "bluefin-server" / "os-sysupdate-keys.bst"
INITRD = ROOT / "elements" / "bluefin-server" / "initrd" / "initrd-stack.bst"
IGN = ROOT / "files" / "initrd-ignition" / "usr"


def ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def test_diskless_pull_verifies_the_signature() -> None:
    boot = BOOT.read_text(encoding="utf-8")
    assert "rd.systemd.pull=raw,machine,verify=signature,blockdev,bootorigin:" in boot
    assert "verify=no" not in boot


def test_keyring_updates_with_usr_and_replaces_fsdk_vendor_key() -> None:
    keys = yaml.safe_load(KEYS.read_text(encoding="utf-8"))
    assert keys["sources"] == [{"kind": "local", "path": "files/boot-keys/import-pubring.pgp"}]
    assert keys["config"]["target"] == "/usr/lib/systemd"
    # Dependency order must make our key win in every consumer; allow only
    # this replacement, without masking unrelated staging collisions.
    assert "freedesktop-sdk.bst:components/systemd.bst" in keys["runtime-depends"]
    assert keys["public"]["bst"]["overlap-whitelist"] == ["/usr/lib/systemd/import-pubring.pgp"]
    for stack in (INITRD, ROOT / "elements/bluefin-server/os-stack.bst"):
        assert "bluefin-server/os-sysupdate-keys.bst" in yaml.safe_load(stack.read_text())["depends"]
    assert "freedesktop-sdk.bst:components/gnupg.bst" in INITRD.read_text()


@pytest.mark.parametrize("name,transfer", [("zfs", "30-zfs.transfer"), ("kubestellar", "31-kubestellar.transfer"), ("kubeadm", "32-kubeadm.transfer"), ("nvidia-open-595", "33-nvidia-open-595.transfer")])
def test_version_locked_sysexts_are_optional_features(name: str, transfer: str) -> None:
    feature = ini(SYSUPDATE / f"{name}.feature")["Feature"]
    assert feature.get("Enabled", "false") == "false", "features are opt-in"
    t = ini(SYSUPDATE / transfer)
    assert t["Transfer"]["Features"] == name
    assert t["Transfer"]["ProtectVersion"] == "%A"
    assert t["Target"]["Path"] == "/var/lib/extensions"
    assert t["Target"]["MatchPattern"] == f"{name}_@v.raw"


@pytest.mark.parametrize("element,name", [("zfs-sysext.bst", "zfs"), ("kubestellar-sysext.bst", "kubestellar"), ("kubeadm-sysext.bst", "kubeadm"), ("nvidia-open-595-sysext.bst", "nvidia-open-595")])
def test_extension_release_name_carries_the_image_version(element: str, name: str) -> None:
    text = (ROOT / "elements" / "oci" / element).read_text(encoding="utf-8")
    assert f'sysext-release: "{name}_%{{image-version}}"' in text
    assert f'sysext-image: "{name}_%{{image-version}}"' in text


def test_sysext_units_are_started_after_a_boot_time_merge() -> None:
    unit = ini(ROOT / "files" / "os" / "systemd" / "system" / "bluefin-sysext-activate.service")
    assert unit["Unit"]["After"] == "systemd-sysext.service"
    assert unit["Service"]["ExecStart"] == "/usr/bin/systemctl start --no-block multi-user.target"


def test_http_booted_nodes_look_for_ignition_next_to_the_uki() -> None:
    helper = (IGN / "libexec" / "bluefin-ignition-credentials").read_text(encoding="utf-8")
    origin = (ROOT / "files" / "boot-origin" / "usr" / "libexec" / "bluefin-boot-origin").read_text(encoding="utf-8")
    assert "/usr/libexec/bluefin-boot-origin" in helper
    assert "StubDeviceURL-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f" in origin
    assert "rd.systemd.pull=*)" in origin and "*:http://*|*:https://*)" in origin, "iPXE-chainloaded nodes use the explicit pull URL"
    assert "NODE_CONFIG=bluefin-node.ign" in helper
    for stage in ("disks", "fetch", "fetch-offline", "files", "mount"):
        unit = (IGN / "lib" / "systemd" / "system" / f"ignition-{stage}.service").read_text(encoding="utf-8")
        assert "ConditionPathExists=/run/ignition/user.ign" in unit
