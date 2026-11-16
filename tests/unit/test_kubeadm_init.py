"""Contracts for the opt-in single-node control plane in the kubeadm sysext.

kubeadm-init.service runs ``kubeadm init`` once from
/etc/kubernetes/bluefin/init.yaml, which kubeadm-init-config.service seeds
from the sysext's default. These tests read the units the way systemd does,
run the init script against stub tools, and render the init config the way
elements/oci/kubeadm-sysext.bst does.
"""


import ipaddress
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from _systemd import SystemdFile, preset, tmpfiles

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "files" / "kubeadm" / "sysext"
SYSEXT = ROOT / "elements" / "oci" / "kubeadm-sysext.bst"
VERSIONS = ROOT / "include" / "kubeadm.yml"
INIT = SRC / "kubeadm-init.service"
SEED = SRC / "kubeadm-init-config.service"
SCRIPT = SRC / "bluefin-kubeadm-init"
CONFIG = SRC / "init.yaml"
SEED_RULES = SRC / "init-tmpfiles.conf"

ETC_CONFIG = "/etc/kubernetes/bluefin/init.yaml"
ADMIN_CONF = "/etc/kubernetes/admin.conf"
SHARE = "/usr/share/bluefin/kubeadm"
CRI_SOCKET = "unix:///run/containerd/containerd.sock"
TAINT = "node-role.kubernetes.io/control-plane:NoSchedule"
# kubeadm's LabelExcludeFromExternalLB, which its mark-control-plane phase puts
# on a control plane next to TAINT; MetalLB's speakers skip a node carrying it.
LABEL = "node.kubernetes.io/exclude-from-external-load-balancers"


def kubernetes_version() -> str:
    return yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))["variables"]["kubernetes-version"]


def rendered_config() -> dict[str, dict]:
    """init.yaml as the sysext build writes it, one document per kind."""
    text = CONFIG.read_text(encoding="utf-8").replace("@KUBERNETES_VERSION@", kubernetes_version())
    docs = [doc for doc in yaml.safe_load_all(text) if doc is not None]
    by_kind = {doc["kind"]: doc for doc in docs}
    assert len(by_kind) == len(docs), "one document per kind"
    return by_kind


def element_script() -> str:
    return yaml.safe_load(SYSEXT.read_text(encoding="utf-8"))["config"]["install-commands"][0]


def test_init_unit_is_shipped_but_no_preset_enables_it() -> None:
    script = element_script()
    assert '"${src}/kubeadm-init.service" "${src}/kubeadm-init-config.service"' in script
    assert 'install -D -m 0755 "${src}/bluefin-kubeadm-init" "sysext%{libexecdir}/bluefin-kubeadm-init"' in script
    presets = sorted((ROOT / "files").rglob("*.preset"))
    assert preset("kubeadm-init.service", presets) == "disable"
    assert "Install" not in SystemdFile(SEED).sections, "the seed unit is only pulled in by kubeadm-init"


def test_init_runs_once_after_containerd_and_the_network() -> None:
    unit = SystemdFile(INIT)
    assert unit.values("Unit", "ConditionPathExists") == [f"!{ADMIN_CONF}", ETC_CONFIG]
    assert "containerd.service" in unit.words("Unit", "Requires")
    for dep in ("network-online.target", "kubeadm-init-config.service"):
        assert dep in unit.words("Unit", "Wants")
    for dep in ("network-online.target", "containerd.service", "kubeadm-init-config.service", "systemd-sysext.service"):
        assert dep in unit.words("Unit", "After")
    assert unit.value("Service", "Type") == "oneshot"
    assert unit.value("Service", "RemainAfterExit") == "yes"
    assert unit.value("Service", "Restart") == "on-failure"
    assert unit.commands() == [["/usr/libexec/bluefin-kubeadm-init"]]
    assert unit.words("Install", "WantedBy") == ["multi-user.target"]


def test_seed_copies_the_default_only_for_the_init_unit() -> None:
    seed = SystemdFile(SEED)
    assert "kubeadm-init.service" in seed.words("Unit", "Before")
    assert seed.values("Unit", "ConditionPathExists") == [f"!{ADMIN_CONF}"]
    assert seed.commands() == [["/usr/bin/systemd-tmpfiles", "--create", f"{SHARE}/init-tmpfiles.conf"]]
    rules = {rule.path: rule for rule in tmpfiles(SEED_RULES)}
    assert (rules[ETC_CONFIG].type, rules[ETC_CONFIG].argument) == ("C", f"{SHARE}/init.yaml")
    assert rules["/etc/kubernetes/bluefin"].type == "d"
    # Outside tmpfiles.d: systemd-tmpfiles-setup and containerd.service's
    # `systemd-tmpfiles --create kubeadm.conf` never apply it on a worker.
    script = element_script()
    assert '"${src}/init-tmpfiles.conf" "sysext%{datadir}/bluefin/kubeadm/init-tmpfiles.conf"' in script
    assert not [line for line in script.splitlines() if "init-tmpfiles.conf" in line and "tmpfiles.d" in line]
    assert all(rule.path != ETC_CONFIG for rule in tmpfiles(SRC / "tmpfiles-kubeadm.conf"))


def test_build_renders_the_shipped_kubernetes_version_and_validates_it() -> None:
    script = element_script()
    assert 'printf \'%s\\n\' "${template//@KUBERNETES_VERSION@/%{kubernetes-version}}" > "${init}"' in script
    assert "*$'\\n''kubernetesVersion: v%{kubernetes-version}'$'\\n'*) ;;" in script
    assert '/kubeadm%{bindir}/kubeadm config validate --config "${init}"' in script
    assert CONFIG.read_text(encoding="utf-8").count("@KUBERNETES_VERSION@") == 1


def test_init_config_is_kubeadm_v1beta4_for_this_sysext() -> None:
    config = rendered_config()
    assert set(config) == {"InitConfiguration", "ClusterConfiguration", "KubeletConfiguration"}
    init, cluster, kubelet = (config[k] for k in ("InitConfiguration", "ClusterConfiguration", "KubeletConfiguration"))
    assert init["apiVersion"] == cluster["apiVersion"] == "kubeadm.k8s.io/v1beta4"
    assert kubelet["apiVersion"] == "kubelet.config.k8s.io/v1beta1"

    containerd = tomllib.loads((SRC / "config.toml").read_text(encoding="utf-8"))
    socket = "unix://" + containerd["grpc"]["address"]
    assert init["nodeRegistration"]["criSocket"] == socket == CRI_SOCKET
    assert kubelet["containerRuntimeEndpoint"] == socket
    assert kubelet["cgroupDriver"] == "systemd"
    assert containerd["plugins"]["io.containerd.cri.v1.runtime"]["containerd"]["runtimes"]["runc"]["options"]["SystemdCgroup"]

    assert cluster["kubernetesVersion"] == f"v{kubernetes_version()}"
    assert cluster["imageRepository"] == "registry.k8s.io"
    assert cluster["clusterName"] == "bluefin"
    pods = ipaddress.ip_network(cluster["networking"]["podSubnet"])
    services = ipaddress.ip_network(cluster["networking"]["serviceSubnet"])
    assert pods.is_private and services.is_private and not pods.overlaps(services)

    # Auto-detected unless the operator sets them in the /etc copy.
    assert "localAPIEndpoint" not in init
    assert "name" not in init["nodeRegistration"]
    assert "controlPlaneEndpoint" not in cluster


def test_controller_manager_flexvolume_dir_is_the_kubelets_writable_one() -> None:
    # kubeadm mounts flex-volume-plugin-dir into kube-controller-manager as a
    # DirectoryOrCreate hostPath; its /usr default cannot be created.
    args = {a["name"]: a["value"] for a in rendered_config()["ClusterConfiguration"]["controllerManager"]["extraArgs"]}
    kubelet = SystemdFile(SRC / "kubelet.service", SRC / "10-kubeadm.conf").commands()[-1]
    assert f"--volume-plugin-dir={args['flex-volume-plugin-dir']}" in kubelet
    assert args["flex-volume-plugin-dir"].startswith("/var/")


@pytest.fixture
def run_init(tmp_path: Path):
    """Run bluefin-kubeadm-init against stub systemctl/kubeadm/kubectl.

    Returns ``(returncode, calls, kubeconfig link)``; each call is one argv.
    """

    def run(
        *,
        init_rc: int = 0,
        taints: str = TAINT.split(":")[0],
        nodes: tuple[str, ...] = ("cp",),
        labelled: tuple[str, ...] = ("cp",),
    ) -> tuple[int, list[list[str]], Path]:
        stubs = tmp_path / "bin"
        stubs.mkdir(exist_ok=True)
        calls = tmp_path / "calls"
        calls.write_text("", encoding="utf-8")

        def names(items: tuple[str, ...]) -> str:
            return "printf '" + "".join(f"node/{n}\\n" for n in items) + "'"

        # Only a selector on exactly LABEL finds the `labelled` nodes.
        kubectl = (
            '[ "$1" = get ] && case "$*" in'
            f' *taints*) echo "{taints}";;'
            f' "get nodes -l {LABEL} -o name") {names(labelled)};;'
            f' "get nodes -o name") {names(nodes)};;'
            ' esac'
        )
        for tool, body in {
            "systemctl": "",
            "kubeadm": f'[ "$1" = init ] && exit {init_rc}',
            "kubectl": kubectl,
        }.items():
            (stubs / tool).write_text(
                f'#!/bin/sh\nprintf "%s\\0" {tool} "$@" >> "$CALLS"; printf "\\n" >> "$CALLS"\n{body}\nexit 0\n',
                encoding="utf-8",
            )
            (stubs / tool).chmod(0o755)
        home = tmp_path / "root"
        script = SCRIPT.read_text(encoding="utf-8").replace("/root/.kube", str(home / ".kube"))
        proc = subprocess.run(
            ["sh", "-c", script],
            env={"PATH": f"{stubs}:{os.environ['PATH']}", "CALLS": str(calls)},
            capture_output=True,
            text=True,
        )
        argvs = [line.rstrip("\0").split("\0") for line in calls.read_text(encoding="utf-8").splitlines() if line]
        return proc.returncode, argvs, home / ".kube" / "config"

    return run


def test_init_enables_kubelet_skips_kube_proxy_untaints_and_links_kubeconfig(run_init) -> None:
    rc, calls, kubeconfig = run_init()
    assert rc == 0
    enable = ["systemctl", "enable", "containerd.service", "kubelet.service"]
    init = ["kubeadm", "init", "--config", ETC_CONFIG, "--skip-phases=addon/kube-proxy"]
    untaint = ["kubectl", "taint", "nodes", "--all", f"{TAINT}-"]
    assert enable in calls and init in calls and untaint in calls
    assert calls.index(enable) < calls.index(init) < calls.index(untaint)
    assert not [c for c in calls if c[:2] == ["kubeadm", "reset"]]
    assert kubeconfig.is_symlink() and os.readlink(kubeconfig) == ADMIN_CONF
    assert oct(kubeconfig.parent.stat().st_mode & 0o777) == "0o700"


def test_init_leaves_an_untainted_node_alone(run_init) -> None:
    rc, calls, _ = run_init(taints="example.com/other")
    assert rc == 0
    assert not [c for c in calls if c[:2] == ["kubectl", "taint"]]


def test_init_lets_load_balancers_reach_the_only_node(run_init) -> None:
    # With the label, MetalLB announces no LoadBalancer address from the
    # cluster's only node (#371).
    rc, calls, _ = run_init()
    assert rc == 0
    untaint = ["kubectl", "taint", "nodes", "--all", f"{TAINT}-"]
    unlabel = ["kubectl", "label", "node/cp", f"{LABEL}-"]
    assert unlabel in calls and calls.index(untaint) < calls.index(unlabel)
    assert [c for c in calls if c[:2] == ["kubectl", "label"]] == [unlabel]


def test_init_leaves_a_node_without_the_label_alone(run_init) -> None:
    rc, calls, _ = run_init(labelled=())
    assert rc == 0
    assert not [c for c in calls if c[:2] == ["kubectl", "label"]]


def test_init_keeps_the_label_once_the_cluster_has_other_nodes(run_init) -> None:
    rc, calls, _ = run_init(nodes=("cp", "worker"))
    assert rc == 0
    assert not [c for c in calls if c[:2] == ["kubectl", "label"]]


def test_failed_init_resets_so_the_retry_is_not_skipped(run_init) -> None:
    # admin.conf is written before the control plane is up; left behind, it
    # would make ConditionPathExists=!admin.conf skip every Restart= retry.
    rc, calls, kubeconfig = run_init(init_rc=1)
    assert rc != 0
    assert ["kubeadm", "reset", "--force", "--cri-socket", CRI_SOCKET] in calls
    assert not [c for c in calls if c[0] == "kubectl"]
    assert not kubeconfig.exists() and not kubeconfig.is_symlink()


def test_init_script_is_posix_sh() -> None:
    assert SCRIPT.read_text(encoding="utf-8").startswith("#!/bin/sh\n")
    assert os.access(SCRIPT, os.X_OK)
    assert re.search(r"^set -eu$", SCRIPT.read_text(encoding="utf-8"), re.M)
