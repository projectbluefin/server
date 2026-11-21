"""A diskless node keeps the identity it can: its MAC for DHCP, and host keys it is given.

networkd's default DHCP client ID derives from /etc/machine-id, which a
diskless boot (root=tmpfs) regenerates every time and which differs between
the initrd and the host: two clients per boot, a new one each boot. The MAC
is stable. Installed nodes keep their machine ID and the default.
"""


from pathlib import Path

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
NETWORK = ROOT / "files" / "os" / "systemd" / "network"
WIRED = NETWORK / "20-wired.network"
DISKLESS = NETWORK / "15-wired-diskless.network"
INITRD = ROOT / "files" / "initrd" / "usr" / "lib" / "systemd" / "network" / "90-initrd-dhcp.network"
KEYGEN = ROOT / "files" / "os" / "systemd" / "system" / "ssh-host-keygen.service"
SKILL = ROOT / "docs" / "skills" / "tpm2-credential-sealing.md"


def test_the_diskless_network_identifies_the_client_by_mac() -> None:
    network = SystemdFile(DISKLESS)
    assert network.value("DHCPv4", "ClientIdentifier") == "mac"
    assert network.value("Match", "KernelCommandLine") == "root=tmpfs"
    assert network.value("Match", "Name") == WIRED.read_text(encoding="utf-8").split("Name=", 1)[1].split()[0]


def test_the_diskless_network_repeats_the_wired_one_otherwise() -> None:
    wired, diskless = SystemdFile(WIRED), SystemdFile(DISKLESS)
    for key in ("DHCP", "MulticastDNS", "LLMNR"):
        assert diskless.value("Network", key) == wired.value("Network", key), key


def test_installed_nodes_keep_the_default_client_identifier() -> None:
    # An installed node's machine ID persists, and changing the identifier would
    # change its lease the day it updates into this image.
    assert SystemdFile(WIRED).value("DHCPv4", "ClientIdentifier") is None


def test_the_diskless_network_sorts_between_the_static_credential_and_the_wired_file() -> None:
    # networkd applies the first matching file in name order: a credential
    # 10-static.network still overrides it, and it wins over 20-wired.network.
    assert "10-static.network" < DISKLESS.name < WIRED.name


def test_the_initrd_identifies_its_dhcp_client_by_mac_too() -> None:
    # The initrd's request and the host's must be one client, or each boot
    # takes two leases.
    assert SystemdFile(INITRD).value("DHCPv4", "ClientIdentifier") == "mac"


def test_a_delivered_host_key_stops_the_generator() -> None:
    unit = SystemdFile(KEYGEN)
    assert unit.value("Unit", "ConditionPathExists") == "!/etc/ssh/ssh_host_ed25519_key"
    assert "sshd.service" in unit.words("Unit", "Before")


def test_the_docs_show_the_credential_that_keeps_the_host_key() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "f~ /etc/ssh/ssh_host_ed25519_key 0600 root root -" in skill
    assert "15-wired-diskless.network" in skill
