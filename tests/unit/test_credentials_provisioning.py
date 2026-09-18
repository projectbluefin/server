"""Contracts for first-boot systemd credential provisioning."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ELEMENT = REPO_ROOT / "elements" / "bluefin-server" / "os-creds-prov.bst"
STACK = REPO_ROOT / "elements" / "bluefin-server" / "os-stack.bst"
FIRSTBOOT = (
    REPO_ROOT
    / "files"
    / "os"
    / "creds"
    / "systemd"
    / "system"
    / "bluefin-firstboot-credentials.service"
)
FIRSTBOOT_PRESET = (
    REPO_ROOT
    / "files"
    / "os"
    / "systemd"
    / "system-preset"
    / "zz-enable-bluefin-firstboot-credentials.preset"
)
NETWORK_GENERATOR_PRESET = (
    REPO_ROOT
    / "files"
    / "os"
    / "systemd"
    / "system-preset"
    / "zz-enable-systemd-network-generator.preset"
)
NETWORK_GENERATOR_DROPIN = (
    REPO_ROOT
    / "files"
    / "os"
    / "creds"
    / "systemd"
    / "system"
    / "systemd-network-generator.service.d"
    / "10-bluefin-credentials.conf"
)
NETWORK = REPO_ROOT / "files" / "os" / "systemd" / "network" / "20-wired.network"
TPM2_SKILL = REPO_ROOT / "docs" / "skills" / "tpm2-credential-sealing.md"


def test_creds_provisioning_element_stages_all_credential_consumers() -> None:
    data = yaml.safe_load(ELEMENT.read_text(encoding="utf-8"))

    assert data["kind"] == "manual"
    assert "base/base-stack.bst" in data["build-depends"]
    assert "bluefin-server/os-creds-prov.bst" in STACK.read_text(encoding="utf-8")

    sources = {source["directory"]: source["path"] for source in data["sources"]}
    assert sources == {
        "sysusers-src": "files/os/sysusers.d",
        "systemd-src": "files/os/creds/systemd/system",
    }

    commands = "\n".join(data["config"]["install-commands"])
    assert "/usr/lib/sysusers.d/" in commands
    assert "cp -a systemd-src/." in commands


def test_firstboot_credentials_are_noninteractive_and_presence_gated() -> None:
    unit = FIRSTBOOT.read_text(encoding="utf-8")

    for credential in (
        "firstboot.locale",
        "firstboot.locale-messages",
        "firstboot.keymap",
        "firstboot.timezone",
        "firstboot.hostname",
    ):
        assert f"ConditionCredential=|{credential}" in unit
        assert f"ImportCredential={credential}" in unit

    assert "ExecStart=systemd-firstboot --force --welcome=no" in unit
    assert "--prompt" not in unit
    assert "ConditionPathIsReadWrite=/etc" in unit
    assert "ConditionPathExists=!/etc/.bluefin-firstboot-credentials" in unit
    assert (
        "After=systemd-remount-fs.service systemd-sysusers.service "
        "systemd-tmpfiles-setup.service"
        in unit
    )
    assert "WantedBy=sysinit.target" in unit
    assert FIRSTBOOT_PRESET.read_text(encoding="utf-8") == (
        "enable bluefin-firstboot-credentials.service\n"
    )


def test_network_credentials_override_dhcp_without_removing_fallback() -> None:
    network = NETWORK.read_text(encoding="utf-8")
    skill = TPM2_SKILL.read_text(encoding="utf-8")

    assert network == "[Match]\nName=e*\n\n[Network]\nDHCP=ipv4\n"
    assert "network.network.*" in skill
    assert "network.netdev.*" in skill
    assert NETWORK_GENERATOR_DROPIN.read_text(encoding="utf-8") == (
        "[Service]\n"
        "ImportCredential=network.conf.*\n"
        "ImportCredential=network.link.*\n"
        "ImportCredential=network.netdev.*\n"
        "ImportCredential=network.network.*\n"
    )
    assert "systemd-network-generator" in skill
    assert "/run/systemd/network/" in skill
    assert "10-static.network" in skill
    assert NETWORK_GENERATOR_PRESET.read_text(encoding="utf-8") == (
        "enable systemd-network-generator.service\n"
    )


def test_tpm2_sealing_docs_cover_all_supported_credential_names() -> None:
    skill = TPM2_SKILL.read_text(encoding="utf-8")

    for credential in (
        "passwd.hashed-password.root",
        "tmpfiles.extra",
        "network.network.10-static",
        "firstboot.hostname",
    ):
        assert credential in skill

    assert "--with-key=tpm2" in skill
    assert "--tpm2-pcrs=7+11" in skill
    assert "/loader/credentials/" in skill
