"""Contracts for retry-safe k0s sysext first-boot activation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICE = (
    ROOT / "files" / "os" / "systemd" / "system" / "k0s-first-boot.service"
)
FETCH_SERVICE = (
    ROOT
    / "files"
    / "os"
    / "systemd"
    / "system"
    / "k0s-first-boot-fetch.service"
)
PRESET = (
    ROOT
    / "files"
    / "os"
    / "systemd"
    / "system-preset"
    / "zz-enable-k0s-first-boot.preset"
)
NETWORK = ROOT / "files" / "os" / "systemd" / "network" / "20-wired.network"
NETWORK_PRESET = (
    ROOT
    / "files"
    / "os"
    / "systemd"
    / "system-preset"
    / "zz-enable-networkd.preset"
)
ELEMENT = ROOT / "elements" / "bluefin-server" / "os-k0s-first-boot.bst"
NETWORK_ELEMENT = ROOT / "elements" / "bluefin-server" / "os-networkd.bst"
K0S_UPDATE_ELEMENT = (
    ROOT / "elements" / "bluefin-server" / "os-k0s-sysupdate.bst"
)
STACK = ROOT / "elements" / "bluefin-server" / "os-stack.bst"


def test_seeded_install_skips_the_network_fetch() -> None:
    assert FETCH_SERVICE.is_file(), "the conditional k0s fetch unit is missing"
    fetch_service = FETCH_SERVICE.read_text(encoding="utf-8")
    first_boot = SERVICE.read_text(encoding="utf-8")

    assert "ConditionPathExists=!/var/lib/extensions/k0s.raw" in fetch_service
    assert (
        "ExecStart=/usr/bin/systemd-sysupdate --component=k0s update"
        in fetch_service
    )
    assert "systemd-sysupdate" not in first_boot


def test_missing_seed_fetches_before_activation_without_blocking_activation_retry() -> None:
    assert FETCH_SERVICE.is_file(), "the conditional k0s fetch unit is missing"
    fetch_service = FETCH_SERVICE.read_text(encoding="utf-8")
    first_boot = SERVICE.read_text(encoding="utf-8")

    assert "Type=oneshot" in fetch_service
    assert "Restart=on-failure" in fetch_service
    assert "ConditionPathExists=!/var/lib/extensions/k0s.raw" in fetch_service
    assert "Before=k0s-first-boot.service" in fetch_service
    assert "Wants=k0s-first-boot-fetch.service" in first_boot
    assert "Requires=k0s-first-boot-fetch.service" not in first_boot
    assert "After=k0s-first-boot-fetch.service" in first_boot
    assert (
        "ExecStartPre=/usr/bin/test -e /var/lib/extensions/k0s.raw"
        in first_boot
    )
    assert "AssertPathExists=/var/lib/extensions/k0s.raw" not in first_boot
    assert "ExecStart=/usr/bin/systemd-sysext merge" in first_boot


def test_k0s_first_boot_retries_until_controller_starts() -> None:
    service = SERVICE.read_text(encoding="utf-8")

    assert "ConditionPathExists=!/var/lib/k0s/.first-boot-complete" in service
    assert "Wants=network-online.target" in service
    assert "After=network-online.target" in service
    assert "Before=multi-user.target" not in service
    assert "Type=oneshot" in service
    assert "StateDirectory=k0s" in service
    assert "Restart=on-failure" in service
    assert (
        "ExecStart=/usr/bin/systemd-sysupdate --component=k0s update"
        not in service
    )
    assert "ExecStart=/usr/bin/systemd-sysupdate update" not in service
    assert (
        "ExecStart=/usr/bin/systemctl enable --now systemd-sysext.service"
        in service
    )
    assert "ExecStart=/usr/bin/systemd-sysext merge" in service
    assert (
        "ExecStart=/usr/bin/systemd-tmpfiles --create "
        "/usr/lib/tmpfiles.d/k0s-manifests.conf"
    ) in service
    assert "ExecStart=/usr/bin/systemctl daemon-reload" in service
    assert (
        "ExecStart=/usr/bin/systemctl enable --now k0scontroller.service"
        in service
    )
    assert (
        "ExecStartPost=/usr/bin/touch /var/lib/k0s/.first-boot-complete"
        in service
    )
    assert "ConditionFirstBoot" not in service


def test_k0s_first_boot_is_packaged_and_enabled() -> None:
    assert (
        PRESET.read_text(encoding="utf-8")
        == "enable k0s-first-boot.service\n"
    )
    assert "path: files/os/systemd/system" in ELEMENT.read_text(encoding="utf-8")
    assert "target: /usr/lib/systemd/system" in ELEMENT.read_text(encoding="utf-8")
    assert (
        "bluefin-server/os-k0s-first-boot.bst"
        in STACK.read_text(encoding="utf-8")
    )


def test_installed_os_configures_wired_dhcp_with_networkd() -> None:
    assert NETWORK.read_text(encoding="utf-8") == (
        "[Match]\n"
        "Name=e*\n"
        "\n"
        "[Network]\n"
        "DHCP=ipv4\n"
    )
    assert NETWORK_PRESET.read_text(encoding="utf-8") == (
        "enable systemd-networkd.service\n"
    )
    network_element = NETWORK_ELEMENT.read_text(encoding="utf-8")
    assert "path: files/os/systemd/network" in network_element
    assert "target: /usr/lib/systemd/network" in network_element
    assert "bluefin-server/os-networkd.bst" in STACK.read_text(encoding="utf-8")


def test_k0s_sysupdate_transfer_is_packaged_as_a_component() -> None:
    element = K0S_UPDATE_ELEMENT.read_text(encoding="utf-8")
    assert "path: files/os/sysupdate.k0s.d" in element
    assert "target: /usr/lib/sysupdate.k0s.d" in element
    assert (
        "bluefin-server/os-k0s-sysupdate.bst"
        in STACK.read_text(encoding="utf-8")
    )
