"""Contracts for the open-iscsi initiator shipped in the base image."""


from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OS_BASE = ROOT / "elements" / "bluefin-server" / "os-base.bst"
PRESET = ROOT / "files" / "os" / "systemd" / "system-preset" / "80-bluefin-iscsi.preset"
TMPFILES = ROOT / "files" / "os" / "tmpfiles.d" / "30-bluefin-iscsi.conf"
USR = ROOT / "elements" / "oci" / "bluefin-server-usr.bst"
COMPONENT = "freedesktop-sdk.bst:components/open-iscsi.bst"


def preset_lines() -> list[list[str]]:
    return [line.split() for line in PRESET.read_text().splitlines() if line and not line.startswith("#")]


def test_open_iscsi_is_in_the_base_stack_only() -> None:
    assert COMPONENT in yaml.safe_load(OS_BASE.read_text(encoding="utf-8"))["depends"]
    for sysext in (ROOT / "elements").rglob("*sysext*.bst"):
        assert "iscsi" not in sysext.read_text(encoding="utf-8"), sysext
    assert not any("iscsi" in p.name for p in (ROOT / "files" / "kubeadm").rglob("*"))


def test_preset_socket_activates_iscsid_without_auto_login() -> None:
    lines = preset_lines()
    assert ["enable", "iscsid.socket"] in lines
    for unit in ("iscsid.service", "iscsi.service", "iscsiuio.service", "iscsiuio.socket"):
        assert ["disable", unit] in lines
    assert not any(verb == "enable" and unit != "iscsid.socket" for verb, unit in lines)


def test_etc_iscsi_is_present_at_runtime() -> None:
    usr = USR.read_text(encoding="utf-8")
    assert 'mv /sysroot/etc "${factory}"' in usr
    assert "printf 'C /etc/%s - - - - %s\\n'" in usr
    rules = TMPFILES.read_text().splitlines()
    assert "d /etc/iscsi 0755 root root -" in rules
    assert "C /etc/iscsi/iscsid.conf - - - - /usr/share/factory/etc/iscsi/iscsid.conf" in rules
    assert "d /var/lib/iscsi 0755 root root -" in rules


def test_initiator_name_is_generated_by_upstream_guarded_unit() -> None:
    fsdk = next((ROOT / ".bst" / "staged-junctions").glob("freedesktop-sdk.bst/*/elements/components/open-iscsi.bst"), None)
    if fsdk is not None:
        assert "initiatorname.iscsi" in fsdk.read_text(encoding="utf-8"), "FSDK must not ship a fixed name"
    # iscsi-init.service is upstream's (ConditionPathExists=!/etc/iscsi/initiatorname.iscsi,
    # Requires= of iscsid.service); the preset must not enable it at boot.
    assert ["disable", "iscsi-init.service"] in preset_lines()
