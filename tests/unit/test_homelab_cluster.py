"""Contracts for the multi-node homelab: bluefin-cluster (files/homelab/cluster),
its units in the homelab sysext, mDNS, and role gating."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

from _systemd import SystemdFile, preset_rules

ROOT = Path(__file__).resolve().parents[2]
SYSEXT_SRC = ROOT / "files" / "homelab" / "sysext"
CLUSTER = ROOT / "files" / "homelab" / "cluster"
ELEMENT = ROOT / "elements" / "oci" / "homelab-sysext.bst"
GO_ELEMENT = ROOT / "elements" / "homelab" / "bluefin-cluster.bst"
MAIN = CLUSTER / "cmd" / "bluefin-cluster" / "main.go"
UNITS = ("bluefin-cluster-prepare.service", "bluefin-cluster-serve.service", "bluefin-cluster-join.service", "bluefin-cluster-hosts.service")
HOMELAB_CONF = "/etc/bluefin/homelab.conf"


def unit(name: str) -> SystemdFile:
    return SystemdFile(SYSEXT_SRC / name)


def install_script() -> str:
    return yaml.safe_load(ELEMENT.read_text())["config"]["install-commands"][0]


def test_every_unit_needs_homelab_conf_and_none_is_preset() -> None:
    presets = [p for d in ("files/os/systemd/system-preset", "files/kubeadm/sysext") for p in (ROOT / d).glob("*.preset")]
    for name in UNITS:
        u = unit(name)
        assert HOMELAB_CONF in u.values("Unit", "ConditionPathExists"), name
        assert not u.values("Install", "WantedBy"), f"{name}: wired by the sysext's static .wants links, not [Install]"
        for path in presets:
            assert all(rule[1] != name for rule in preset_rules(path)), f"{path.name} mentions {name}"


def test_sysext_wires_each_unit_to_its_role() -> None:
    script = install_script()
    for link in (
        "kubeadm-init.service.wants/bluefin-cluster-prepare.service",
        "k0scontroller.service.wants/bluefin-cluster-prepare.service",
        "kubelet.service.wants/bluefin-cluster-serve.service",
        "k0scontroller.service.wants/bluefin-cluster-serve.service",
        "multi-user.target.wants/bluefin-cluster-join.service",
        "multi-user.target.wants/bluefin-cluster-hosts.timer",
    ):
        assert link in script
    assert "cp -a /bluefin-cluster%{prefix}/. sysext%{prefix}/" in script
    deps = yaml.safe_load(ELEMENT.read_text())["build-depends"]
    assert {"filename": "homelab/bluefin-cluster.bst", "config": {"location": "/bluefin-cluster"}} in deps


def test_cluster_units_resolve_names_after_resolved_and_the_network() -> None:
    for name in UNITS:
        after = unit(name).words("Unit", "After")
        assert {"network-online.target", "systemd-resolved.service"} <= set(after), name


def test_prepare_runs_between_the_config_seed_and_kubeadm_init() -> None:
    u = unit("bluefin-cluster-prepare.service")
    assert "kubeadm-init-config.service" in u.words("Unit", "After")
    assert {"kubeadm-init.service", "k0scontroller.service"} <= set(u.words("Unit", "Before"))
    assert u.value("Service", "Type") == "oneshot"
    assert u.commands() == [["/usr/bin/bluefin-cluster", "prepare"]]


def test_serve_keeps_its_state_private() -> None:
    u = unit("bluefin-cluster-serve.service")
    assert u.commands() == [["/usr/bin/bluefin-cluster", "serve"]]
    assert u.value("Service", "StateDirectory") == "bluefin-cluster"
    assert u.value("Service", "StateDirectoryMode") == "0700"
    assert u.value("Service", "UMask") == "0077"
    assert u.value("Service", "Restart") == "on-failure"


def test_join_runs_once_and_never_blocks_boot() -> None:
    u = unit("bluefin-cluster-join.service")
    assert "!/var/lib/bluefin-cluster/joined" in u.values("Unit", "ConditionPathExists")
    # multi-user.target is ordered after what it wants: a oneshot that
    # waits for a control plane would hold up boot.
    assert u.value("Service", "Type") == "simple"
    assert u.value("Service", "ImportCredential") == "bluefin-cluster.passphrase"
    assert u.commands() == [["/usr/bin/bluefin-cluster", "join"]]
    main = MAIN.read_text()
    assert 'joinedMarker  = stateDir + "/joined"' in main
    assert "conf.RemoveKey(conf.DefaultPath, passKey)" in main


def test_role_gating_in_the_program() -> None:
    main = MAIN.read_text()
    for fn, role in (("prepare", "RoleControlPlane"), ("serve", "RoleControlPlane"), ("runJoin", "RoleNode")):
        body = main.split(f"func {fn}(ctx context.Context) error {{", 1)[1].split("\n}\n", 1)[0]
        assert f"c.Role() != conf.{role}" in body, fn


def test_applier_does_nothing_on_a_node() -> None:
    script = (SYSEXT_SRC / "bluefin-homelab-apply").read_text()
    main = script.split("main() {", 1)[1]
    assert main.index('"${HOMELAB_ROLE:-}" = node') < main.index("find_kubeconfig")


def test_dnssd_advertisement_carries_no_secrets() -> None:
    main = MAIN.read_text()
    publish = main.split("func publish(", 1)[1].split("\n}\n", 1)[0]
    txt = re.search(r"TxtText=([^\\]*)\\n", publish).group(1)
    assert txt == "v=1 cluster=%s runtime=%s"
    assert "pass" not in publish.lower() and "token" not in publish.lower()
    assert 'dnssdFile     = "/run/systemd/dnssd/bluefin-cluster.dnssd"' in main
    assert "*.dnssd" in install_script(), "the build refuses a static advertisement in the sysext"
    # serve runs with UMask=0077; systemd-resolved (its own user) must read it.
    assert "os.Chmod(dir, 0o755)" in publish and "os.Chmod(dnssdFile, 0o644)" in publish


def test_mdns_comes_from_the_base_os_not_the_homelab_sysext() -> None:
    base = SystemdFile(ROOT / "files" / "os" / "systemd" / "network" / "20-wired.network")
    assert base.value("Network", "MulticastDNS") == "yes"
    assert "/systemd/network/" not in install_script()
    assert not list(SYSEXT_SRC.glob("*.conf")), "no networkd or resolved drop-ins in the homelab sysext"


def test_homelab_names_a_localhost_node_with_the_base_os_helper() -> None:
    ops = (CLUSTER / "internal" / "ops" / "ops.go").read_text()
    assert 'HostnameHelper = "/usr/libexec/bluefin-hostname"' in ops
    body = ops.split("func EnsureHostname(", 1)[1].split("\n}\n", 1)[0]
    assert "Run(ctx, HostnameHelper)" in body and "machine-id" not in body


def test_passphrase_never_reaches_logs_or_the_image() -> None:
    main = MAIN.read_text()
    for line in main.splitlines():
        if re.search(r"log\.(Info|Warn|Error)\(", line):
            assert not re.search(r"\b(pass|p)\b[,)]", line), line
    assert "0o600" in main.split("func writeIssue(", 1)[1].split("\n}\n", 1)[0]
    assert "'passphrase'" in install_script()


def test_go_build_is_offline_from_vendored_modules() -> None:
    element = yaml.safe_load(GO_ELEMENT.read_text())
    env = element["environment"]
    assert env["GOPROXY"] == "off" and "-mod=vendor" in env["GOFLAGS"] and env["CGO_ENABLED"] == "0"
    assert "freedesktop-sdk.bst:components/go.bst" in element["build-depends"]
    assert [s["path"] for s in element["sources"]] == ["files/homelab/cluster"]
    modules = (CLUSTER / "vendor" / "modules.txt").read_text()
    gomod = (CLUSTER / "go.mod").read_text()
    for mod in re.findall(r"^\t(\S+) (v\S+)", gomod, re.M):
        assert f"# {mod[0]} {mod[1]}" in modules, mod
        assert (CLUSTER / "vendor" / mod[0] / "LICENSE").is_file(), mod


def test_wordlist_is_the_pinned_eff_large_list() -> None:
    data = (CLUSTER / "internal" / "passphrase" / "eff_large_wordlist.txt").read_bytes()
    assert hashlib.sha256(data).hexdigest() == "addd35536511597a02fa0a9ff1e5284677b8883b83e986e43f15a3db996b903e"
    assert len(data.splitlines()) == 7776


def test_hosts_pin_is_refreshed_by_a_timer() -> None:
    u = unit("bluefin-cluster-hosts.service")
    assert u.commands() == [["/usr/bin/bluefin-cluster", "hosts"]]
    timer = SystemdFile(SYSEXT_SRC / "bluefin-cluster-hosts.timer")
    assert timer.value("Timer", "OnUnitActiveSec") == "5min"
    assert HOMELAB_CONF in timer.values("Unit", "ConditionPathExists")
