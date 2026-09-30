"""Contracts for first-boot systemd credential provisioning."""

from __future__ import annotations

from pathlib import Path

import yaml

from _systemd import SystemdFile, preset

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
PRESETS = sorted((REPO_ROOT / "files" / "os" / "systemd" / "system-preset").glob("*.preset"))
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
FIRSTBOOT_HELPER = REPO_ROOT / "files" / "os" / "libexec" / "bluefin-firstboot-credentials"
NETWORK = REPO_ROOT / "files" / "os" / "systemd" / "network" / "20-wired.network"
TPM2_SKILL = REPO_ROOT / "docs" / "skills" / "tpm2-credential-sealing.md"


def test_creds_provisioning_element_stages_all_credential_consumers() -> None:
    data = yaml.safe_load(ELEMENT.read_text(encoding="utf-8"))

    assert data["kind"] == "manual"
    assert "base/base-stack.bst" in data["build-depends"]
    assert "bluefin-server/os-creds-prov.bst" in yaml.safe_load(STACK.read_text(encoding="utf-8"))["depends"]

    sources = {source["directory"]: source["path"] for source in data["sources"]}
    assert sources == {
        "sysusers-src": "files/os/sysusers.d",
        "systemd-src": "files/os/creds/systemd/system",
        "libexec-src": "files/os/libexec",
    }

    commands = "\n".join(data["config"]["install-commands"])
    assert "/usr/lib/sysusers.d/" in commands
    assert "cp -a systemd-src/." in commands
    assert "install -Dm0755 libexec-src/bluefin-firstboot-credentials" in commands
    assert '"%{install-root}/usr/libexec/bluefin-firstboot-credentials"' in commands
    assert FIRSTBOOT_HELPER.is_file()
    assert FIRSTBOOT_HELPER.stat().st_mode & 0o111


def test_firstboot_credentials_are_noninteractive_and_presence_gated() -> None:
    unit = SystemdFile(FIRSTBOOT)
    credentials = {
        "firstboot.locale",
        "firstboot.locale-messages",
        "firstboot.keymap",
        "firstboot.timezone",
        "firstboot.hostname",
    }

    conditions = unit.values("Unit", "ConditionCredential")
    assert all(c.startswith("|") for c in conditions), "any one credential must trigger the unit"
    assert {c[1:] for c in conditions} == credentials
    assert set(unit.values("Service", "ImportCredential")) == credentials

    # The bundled helper applies them, not systemd-firstboot: it also sets the
    # live kernel hostname before systemd-networkd starts, so the first DHCP
    # request already carries firstboot.hostname.
    words = [word for argv in unit.all_commands() for word in argv]
    assert not [w for w in words if "systemd-firstboot" in w or "--prompt" in w]
    assert ["/usr/libexec/bluefin-firstboot-credentials"] in unit.commands()
    assert "systemd-networkd.service" in unit.words("Unit", "Before")
    # ExecStartPost= runs only after ExecStart= succeeded, so a failed helper
    # leaves no stamp and runs again on the next boot.
    assert ["/usr/bin/touch", "/etc/.bluefin-firstboot-credentials"] in unit.commands("ExecStartPost")
    assert "!/etc/.bluefin-firstboot-credentials" in unit.values("Unit", "ConditionPathExists")
    assert "/etc" in unit.values("Unit", "ConditionPathIsReadWrite")
    assert {
        "systemd-remount-fs.service",
        "systemd-sysusers.service",
        "systemd-tmpfiles-setup.service",
    } <= set(unit.words("Unit", "After"))
    assert "sysinit.target" in unit.words("Install", "WantedBy")
    assert preset("bluefin-firstboot-credentials.service", PRESETS) == "enable"


def test_network_credentials_override_dhcp_without_removing_fallback() -> None:
    skill = TPM2_SKILL.read_text(encoding="utf-8")

    # networkd applies the first .network file, in filename order across
    # /run and /usr, that matches a link: the documented 10-static credential
    # must sort before every shipped file, which stays the DHCP fallback.
    assert "10-static.network" in skill
    shipped = sorted(p.name for p in NETWORK.parent.glob("*.network"))
    assert shipped and all(name > "10-static.network" for name in shipped), shipped
    assert SystemdFile(NETWORK).value("Network", "DHCP") == "ipv4"
    assert "network.network.*" in skill
    assert "network.netdev.*" in skill
    assert set(SystemdFile(NETWORK_GENERATOR_DROPIN).values("Service", "ImportCredential")) == {
        "network.conf.*",
        "network.link.*",
        "network.netdev.*",
        "network.network.*",
    }
    assert "systemd-network-generator" in skill
    assert "/run/systemd/network/" in skill
    assert preset("systemd-network-generator.service", PRESETS) == "enable"


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
