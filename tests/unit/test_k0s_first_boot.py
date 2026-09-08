"""Contracts for retry-safe k0s sysext first-boot activation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICE = (
    ROOT / "files" / "os" / "systemd" / "system" / "k0s-first-boot.service"
)
PRESET = (
    ROOT
    / "files"
    / "os"
    / "systemd"
    / "system-preset"
    / "zz-enable-k0s-first-boot.preset"
)
ELEMENT = ROOT / "elements" / "bluefin-server" / "os-k0s-first-boot.bst"
STACK = ROOT / "elements" / "bluefin-server" / "os-stack.bst"


def test_k0s_first_boot_retries_until_controller_starts() -> None:
    service = SERVICE.read_text(encoding="utf-8")

    assert "ConditionPathExists=!/var/lib/k0s/.first-boot-complete" in service
    assert "Wants=network-online.target" in service
    assert "After=network-online.target" in service
    assert "Before=multi-user.target" not in service
    assert "Type=oneshot" in service
    assert "StateDirectory=k0s" in service
    assert "Restart=on-failure" in service
    assert "ExecStart=/usr/bin/systemd-sysupdate update" in service
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
