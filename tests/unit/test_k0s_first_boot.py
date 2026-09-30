"""Contracts for retry-safe k0s sysext first-boot activation."""

import posixpath
import subprocess
from pathlib import Path

import pytest
import yaml

from _systemd import SystemdFile, preset, tmpfiles

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "files" / "os" / "systemd" / "system"
SERVICE = UNITS / "k0s-first-boot.service"
FETCH_SERVICE = UNITS / "k0s-first-boot-fetch.service"
PRESETS = sorted((ROOT / "files" / "os" / "systemd" / "system-preset").glob("*.preset"))
NETWORK = ROOT / "files" / "os" / "systemd" / "network" / "20-wired.network"
TMPFILES = ROOT / "files" / "os" / "tmpfiles.d"
ELEMENTS = ROOT / "elements"
ELEMENT = ELEMENTS / "bluefin-server" / "os-k0s-first-boot.bst"
NETWORK_ELEMENT = ELEMENTS / "bluefin-server" / "os-networkd.bst"
K0S_UPDATE_ELEMENT = ELEMENTS / "bluefin-server" / "os-k0s-sysupdate.bst"
RESOLV_ELEMENT = ELEMENTS / "bluefin-server" / "os-resolv-conf.bst"
STACK = ELEMENTS / "bluefin-server" / "os-stack.bst"


def installed_at(element: Path) -> dict[str, str]:
    """Where each local source of an import element lands in the image."""
    data = yaml.safe_load(element.read_text(encoding="utf-8"))
    assert data["kind"] == "import", element
    config = data.get("config", {})
    assert config.get("source", "/") == "/", element
    return {
        source["path"]: posixpath.join(config.get("target", "/"), source.get("directory", ""))
        .rstrip("/")
        for source in data["sources"]
        if source["kind"] == "local"
    }


def in_os_stack(element: Path) -> bool:
    depends = yaml.safe_load(STACK.read_text(encoding="utf-8"))["depends"]
    return element.relative_to(ELEMENTS).as_posix() in depends


def words(unit: SystemdFile) -> list[str]:
    return [word for argv in unit.all_commands() for word in argv]


def test_seeded_install_skips_the_network_fetch() -> None:
    fetch = SystemdFile(FETCH_SERVICE)

    assert "!/var/lib/k0s/k0s.raw" in fetch.values("Unit", "ConditionPathExists")
    assert fetch.commands() == [["/usr/bin/systemd-sysupdate", "--component=k0s", "update"]]
    assert not [w for w in words(SystemdFile(SERVICE)) if "systemd-sysupdate" in w]


def test_missing_seed_fetches_before_activation_without_blocking_activation_retry() -> None:
    fetch = SystemdFile(FETCH_SERVICE)
    first_boot = SystemdFile(SERVICE)

    assert fetch.value("Service", "Type") == "oneshot"
    assert fetch.value("Service", "Restart") == "on-failure"
    assert "!/var/lib/k0s/k0s.raw" in fetch.values("Unit", "ConditionPathExists")
    assert "k0s-first-boot.service" in fetch.words("Unit", "Before")
    assert "k0s-first-boot-fetch.service" in first_boot.words("Unit", "Wants")
    assert "k0s-first-boot-fetch.service" in first_boot.words("Unit", "After")
    for hard in ("Requires", "Requisite", "BindsTo"):
        assert "k0s-first-boot-fetch.service" not in first_boot.words("Unit", hard), (
            "a failed fetch must not fail the activation job"
        )
    assert ["/usr/bin/test", "-e", "/var/lib/k0s/k0s.raw"] in first_boot.commands("ExecStartPre")
    start = first_boot.commands()
    install = [
        "/usr/bin/install", "-D", "-m", "0644", "/var/lib/k0s/k0s.raw", "/run/extensions/k0s.raw"
    ]
    refresh = ["/usr/bin/systemd-sysext", "refresh"]
    assert install in start and refresh in start
    assert start.index(install) < start.index(refresh)


def test_k0s_first_boot_retries_until_controller_starts() -> None:
    unit = SystemdFile(SERVICE)
    commands = unit.commands()

    assert unit.values("Unit", "ConditionPathExists") == []
    assert unit.values("Unit", "ConditionFirstBoot") == []
    assert "network-online.target" in unit.words("Unit", "Wants")
    assert "network-online.target" in unit.words("Unit", "After")
    assert "multi-user.target" not in unit.words("Unit", "Before")
    assert unit.value("Service", "Type") == "oneshot"
    assert unit.value("Service", "StateDirectory") == "k0s"
    assert unit.value("Service", "Restart") == "on-failure"
    assert ["/usr/bin/systemd-sysext", "refresh"] in commands
    assert ["/usr/bin/systemctl", "daemon-reload"] in commands
    for forbidden in ("systemd-sysupdate", "systemd-sysext.service", ".first-boot-complete"):
        assert not [w for w in words(unit) if forbidden in w], forbidden
    assert not [w for w in words(unit) if "kubeflex" in w], "the KubeStellar sysext seeds its own state"


@pytest.mark.parametrize(
    ("token", "role"),
    [
        (None, "k0scontroller.service"),
        ("", "k0scontroller.service"),
        ("K0S-JOIN-TOKEN", "k0sworker.service"),
    ],
)
def test_join_token_selects_the_role_first_boot_enables(
    tmp_path: Path, token: str | None, role: str
) -> None:
    scripts = [
        argv[2]
        for argv in SystemdFile(SERVICE).commands()
        if posixpath.basename(argv[0]) == "sh" and argv[1:2] == ["-c"]
    ]
    assert len(scripts) == 1, "expected one sh -c command choosing the k0s role"
    assert "/etc/k0s/token" in scripts[0]
    token_file = tmp_path / "token"
    if token is not None:
        token_file.write_text(token, encoding="utf-8")
    stubs = tmp_path / "bin"
    stubs.mkdir()
    (stubs / "systemctl").write_text('#!/bin/sh\necho "$@" >> "$CALLS"\n', encoding="utf-8")
    (stubs / "systemctl").chmod(0o755)
    calls = tmp_path / "calls"

    subprocess.run(
        ["sh", "-c", scripts[0].replace("/etc/k0s/token", str(token_file))],
        env={"PATH": f"{stubs}:/usr/bin:/bin", "CALLS": str(calls)},
        check=True,
    )

    assert calls.read_text(encoding="utf-8").splitlines() == [f"enable --now {role}"]


def test_k0s_first_boot_is_packaged_but_opt_in() -> None:
    for unit in ("k0s-first-boot.service", "k0s-first-boot-fetch.service"):
        assert preset(unit, PRESETS) == "disable", (
            f"k0s is opt-in: FSDK has no 'disable *' default, so {unit} must be "
            "disabled explicitly and no earlier preset may enable it"
        )
    assert installed_at(ELEMENT)["files/os/systemd/system"] == "/usr/lib/systemd/system"
    assert in_os_stack(ELEMENT)


def test_installed_os_configures_wired_dhcp_with_networkd() -> None:
    network = SystemdFile(NETWORK)

    assert network.sections["Match"] == {"Name": ["e*"]}, "match every wired link, nothing narrower"
    assert network.value("Network", "DHCP") == "ipv4"
    assert preset("systemd-networkd.service", PRESETS) == "enable"
    assert installed_at(NETWORK_ELEMENT)["files/os/systemd/network"] == "/usr/lib/systemd/network"
    assert in_os_stack(NETWORK_ELEMENT)


def test_k0s_sysupdate_transfer_is_packaged_as_a_component() -> None:
    assert installed_at(K0S_UPDATE_ELEMENT)["files/os/sysupdate.k0s.d"] == "/usr/lib/sysupdate.k0s.d"
    assert in_os_stack(K0S_UPDATE_ELEMENT)


def test_presets_sort_between_ignition_and_fsdk_defaults() -> None:
    # systemd reads preset files from every directory in filename order and
    # the first matching line wins. Ignition enables units through
    # /etc/systemd/system-preset/20-ignition.preset, so a vendor preset that
    # sorts before it (e.g. 20-bluefin-sshd.preset: "disable sshd.service")
    # silently overrides a node config's `enabled: true`. Vendor presets,
    # including those a sysext merges into /usr, must still sort before
    # FSDK's 90-systemd.preset to take effect at all.
    presets = sorted(p.name for p in (ROOT / "files").rglob("*.preset"))
    assert presets, "no presets found under files/"
    for name in presets:
        assert "20-ignition.preset" < name < "90-systemd.preset", (
            f"{name} must sort after 20-ignition.preset (so Ignition can "
            "enable units Bluefin disables) and before 90-systemd.preset"
        )


def test_etc_resolv_conf_symlink_is_seeded_for_kubelet() -> None:
    # /etc starts empty on every boot (bluefin-server-usr.bst moves the build's
    # /etc to /usr/share/factory/etc), so /etc/resolv.conf exists only if a
    # tmpfiles.d rule creates it; without it kubelet fails every pod sandbox
    # with "open /etc/resolv.conf: no such file or directory". FSDK's own
    # systemd-resolve.conf links the 127.0.0.53 stub, which is unreachable from
    # a pod's network namespace. systemd-tmpfiles applies the first rule for a
    # path in filename order, so the rule linking resolved's full upstream list
    # must come first and sort before systemd-resolve.conf.
    rules = [
        (conf.name, rule)
        for conf in sorted(TMPFILES.glob("*.conf"))
        for rule in tmpfiles(conf)
        if rule.path == "/etc/resolv.conf"
    ]
    assert rules, "no tmpfiles.d rule creates /etc/resolv.conf"
    name, rule = rules[0]
    assert (rule.type, rule.argument) == ("L", "../run/systemd/resolve/resolv.conf")
    assert name < "systemd-resolve.conf"
    assert installed_at(RESOLV_ELEMENT)["files/os/tmpfiles.d"] == "/usr/lib/tmpfiles.d"
    assert in_os_stack(RESOLV_ELEMENT)
