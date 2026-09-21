"""Contracts for Kubernetes control-plane bring-up and cluster seeding.

``systemd-analyze verify`` is not available in this repo's test environment, so
the unit invariants that a verifier would catch are asserted here instead:
ordering edges, the placement of the idempotency guard, and the fact that every
unit the preset enables can actually be enabled.

The guard placement is the subtle one. systemd marks a unit whose ``Condition*``
fails as *skipped*, not failed, and treats it as satisfied for everything
ordered after it. That is exactly what ``kubeadm-init.service`` wants on a
second boot, and exactly what ``bluefin-cluster-bootstrap.service`` must never
have: a condition there would silently no-op the seed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "files" / "os" / "systemd" / "system"
PRESET_DIR = ROOT / "files" / "os" / "systemd" / "system-preset"

KUBEADM_INIT = SYSTEM / "kubeadm-init.service"
CLUSTER_REPO = SYSTEM / "bluefin-cluster-repo.service"
CLUSTER_BOOTSTRAP = SYSTEM / "bluefin-cluster-bootstrap.service"
KUBELET = SYSTEM / "kubelet.service"
KUBELET_DROPIN = SYSTEM / "kubelet.service.d" / "10-kubeadm.conf"
SYSEXT_DROPIN = (
    ROOT
    / "files"
    / "os"
    / "systemd"
    / "systemd-sysext.service.d"
    / "10-daemon-reload.conf"
)
PRESET = PRESET_DIR / "zz-enable-cluster-bootstrap.preset"
REPO_HELPER = ROOT / "files" / "os" / "libexec" / "bluefin-cluster-repo"
KUBEADM_CONFIG = ROOT / "files" / "kubernetes" / "kubeadm.yaml"

NETWORK = SYSTEM.parent / "network" / "20-wired.network"
NETWORK_PRESET = PRESET_DIR / "zz-enable-networkd.preset"

ELEMENT = ROOT / "elements" / "bluefin-server" / "os-cluster-bootstrap.bst"
NETWORK_ELEMENT = ROOT / "elements" / "bluefin-server" / "os-networkd.bst"
SYSUPDATE_ELEMENT = (
    ROOT / "elements" / "bluefin-server" / "os-kubernetes-sysupdate.bst"
)
STACK = ROOT / "elements" / "bluefin-server" / "os-stack.bst"

SEED_ROOT = "/usr/share/bluefin/seed"
SEED_PHASES = ("00-cilium", "10-argocd-core", "15-gitd", "20-root-app")

UNITS = (KUBEADM_INIT, CLUSTER_REPO, CLUSTER_BOOTSTRAP, KUBELET)


def unit(path: Path) -> dict[str, dict[str, list[str]]]:
    """Parse a unit file into ``{section: {key: [values...]}}``.

    ``configparser`` collapses repeated keys, and repeated keys are the whole
    point of a unit file: ``ExecStart=`` order *is* the seed order.
    """
    sections: dict[str, dict[str, list[str]]] = {}
    current: dict[str, list[str]] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
            continue
        assert current is not None, f"{path.name}: {line!r} precedes any section"
        key, _, value = line.partition("=")
        current.setdefault(key.strip(), []).append(value.strip())
    return sections


def exec_starts(path: Path) -> list[str]:
    return unit(path)["Service"].get("ExecStart", [])


@pytest.mark.parametrize("path", UNITS, ids=lambda p: p.name)
def test_every_unit_parses_and_can_be_enabled(path: Path) -> None:
    sections = unit(path)
    assert "Unit" in sections and "Service" in sections
    assert sections["Install"]["WantedBy"] == ["multi-user.target"], (
        f"{path.name} has no [Install] WantedBy, so the preset cannot enable it"
    )


def test_preset_enables_exactly_the_units_that_are_shipped() -> None:
    enabled = [
        line.removeprefix("enable ")
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert enabled == [
        "kubelet.service",
        "kubeadm-init.service",
        "bluefin-cluster-repo.service",
        "bluefin-cluster-bootstrap.service",
    ]
    for name in enabled:
        assert (SYSTEM / name).is_file(), f"preset enables missing unit {name}"


def test_the_idempotency_guard_lives_on_kubeadm_init_alone() -> None:
    """A skipped unit satisfies its dependents; a skipped seed is a dead node."""
    init = unit(KUBEADM_INIT)
    assert init["Unit"]["ConditionPathExists"] == ["!/etc/kubernetes/admin.conf"]

    for path in (CLUSTER_BOOTSTRAP,):
        guards = [
            key
            for key in unit(path)["Unit"]
            if key.startswith(("Condition", "Assert"))
        ]
        assert guards == [], (
            f"{path.name} carries {guards}; a failed condition marks the unit "
            "skipped rather than failed, silently no-opping the first boot seed"
        )


def test_kubeadm_init_waits_for_the_sysext_merge_and_the_runtime() -> None:
    init = unit(KUBEADM_INIT)["Unit"]
    requires = set(init.get("Requires", []))
    wants = set(init.get("Wants", []))
    after = set(init.get("After", []))

    # systemd-sysext.service is part of systemd and exists when the boot
    # transaction is computed, so requiring it is safe and correct: without the
    # merge there is no /usr/bin/kubeadm to run.
    assert "systemd-sysext.service" in requires
    assert "systemd-sysext.service" in after

    # containerd.service is different. It arrives *inside* the merge, so it does
    # not exist yet when systemd resolves dependencies. This previously read
    # `Requires=containerd.service`, and systemd dropped kubeadm-init's job from
    # the boot transaction outright — conditions never evaluated, kubeadm never
    # ran, nothing in `systemctl list-units --failed`. Observed on a real boot:
    # preset 12:06:10, merge 12:06:11, multi-user 12:06:13.
    assert "containerd.service" not in requires, (
        "containerd.service does not exist when the boot transaction is "
        "computed; a hard requirement silently drops this unit's job"
    )
    assert "containerd.service" in wants
    assert "containerd.service" in after

    assert "network-online.target" in after


def test_kubeadm_init_stays_active_so_dependents_can_order_on_it() -> None:
    service = unit(KUBEADM_INIT)["Service"]
    assert service["Type"] == ["oneshot"]
    assert service["RemainAfterExit"] == ["yes"], (
        "without RemainAfterExit the unit deactivates immediately and ordering "
        "on it tells a dependent nothing about the control plane"
    )


def test_kubeadm_init_reads_the_staged_config_and_skips_kube_proxy() -> None:
    commands = exec_starts(KUBEADM_INIT)
    assert commands == [
        "/usr/bin/kubeadm init --config /usr/share/bluefin/kubeadm.yaml "
        "--skip-phases=addon/kube-proxy"
    ], "Cilium supplies the kube-proxy replacement; installing both fights"


def test_sysext_merge_reloads_systemd_and_starts_the_merged_runtime() -> None:
    """Making a merged unit visible is not the same as running it.

    containerd.service and its own multi-user.target.wants symlink both live
    inside the sysext, so neither exists when systemd computes the boot
    transaction. The reload makes them visible afterwards, but a reload does not
    enqueue jobs for a target that is already active or already in flight — so
    whether containerd starts comes down to whether the merge happened to land
    before multi-user.target was queued.

    That race was observed resolving both ways on the same image::

        boot A  merge 12:06:11.75, multi-user 12:06:13.14  -> containerd active
        boot B  merge 12:21:10.24, multi-user not reached  -> containerd inactive

    On boot B kubeadm-init blocked forever waiting for a CRI socket that never
    appeared. The explicit start removes the race; it is idempotent when the
    symlink did win.
    """
    post = unit(SYSEXT_DROPIN)["Service"]["ExecStartPost"]

    assert "/usr/bin/systemctl daemon-reload" in post, (
        "without a reload, ordering edges resolve against units systemd has "
        "never read"
    )
    assert "/usr/bin/systemctl start --no-block containerd.service" in post, (
        "containerd.service must be started explicitly: its enablement symlink "
        "arrives with the merge, too late for systemd to act on"
    )
    assert post.index("/usr/bin/systemctl daemon-reload") < post.index(
        "/usr/bin/systemctl start --no-block containerd.service"
    ), "the unit must be read before it can be started"


def test_kubelet_is_configured_by_kubeadm_rather_than_by_the_image() -> None:
    service = unit(KUBELET)["Service"]
    assert service["Restart"] == ["always"]
    assert unit(KUBELET)["Unit"]["StartLimitIntervalSec"] == ["0"], (
        "the kubelet restarts until kubeadm has written its config; a start "
        "limit would leave the node permanently down"
    )

    dropin = unit(KUBELET_DROPIN)["Service"]
    assert dropin["ExecStart"][0] == "", (
        "the drop-in must clear the inherited ExecStart before adding its own"
    )
    assert "$KUBELET_KUBEADM_ARGS" in dropin["ExecStart"][1]
    assert "-/var/lib/kubelet/kubeadm-flags.env" in dropin["EnvironmentFile"]


def test_cluster_repo_is_ordered_before_the_seed_and_is_re_runnable() -> None:
    repo = unit(CLUSTER_REPO)
    assert repo["Unit"]["Before"] == ["bluefin-cluster-bootstrap.service"]
    assert repo["Service"]["Type"] == ["oneshot"]
    assert repo["Service"]["StateDirectory"] == ["bluefin"]
    assert exec_starts(CLUSTER_REPO) == ["/usr/libexec/bluefin-cluster-repo"]


def test_cluster_repo_helper_publishes_a_servable_bare_repository() -> None:
    helper = REPO_HELPER.read_text(encoding="utf-8")
    assert REPO_HELPER.stat().st_mode & 0o111, "the helper must be executable"
    assert "REPO=/var/lib/bluefin/cluster.git" in helper
    assert "SEED=/usr/share/bluefin/cluster" in helper
    assert "BRANCH=main" in helper
    assert "git init --bare" in helper
    assert 'touch "${REPO}/git-daemon-export-ok"' in helper, (
        "git-daemon refuses to serve a repository that is not exported"
    )
    assert "umask 022" in helper, (
        "git-daemon reads the hostPath mount as a non-root uid"
    )


def test_seed_runs_every_phase_in_order_under_the_admin_kubeconfig() -> None:
    bootstrap = unit(CLUSTER_BOOTSTRAP)
    assert bootstrap["Service"]["Environment"] == [
        "KUBECONFIG=/etc/kubernetes/admin.conf"
    ]
    applied = [
        command.rsplit(" ", 1)[-1]
        for command in exec_starts(CLUSTER_BOOTSTRAP)
        if " apply " in command
    ]
    assert applied == [f"{SEED_ROOT}/{phase}" for phase in SEED_PHASES]


def test_seed_applies_server_side_and_never_prunes() -> None:
    for command in exec_starts(CLUSTER_BOOTSTRAP):
        assert "prune" not in command, (
            f"{command}: kubectl rejects --prune alongside --server-side, and "
            "the seed is append-only by design; Argo CD owns pruning downstream"
        )
        if " apply " not in command:
            continue
        assert "--server-side --force-conflicts" in command, command
        assert "-k " in command, f"{command} must apply a kustomization"


def test_seed_waits_for_the_api_server_before_it_applies_anything() -> None:
    """The probe that keeps Wants= diagnosable and the first apply meaningful.

    Relaxing kubeadm-init to ``Wants=`` stopped one transient failure stranding
    this unit, but it also removed the single legible
    ``Job ... failed with result 'dependency'`` line that made the stranding
    visible. Without a probe, a control plane that never arrives shows up as
    thirty rounds of kubectl connection errors and then a gate timeout with no
    stated cause.

    The probe also sharpens what a failure means: once it passes, the API server
    is answering, so anything failing below is a genuine apply failure rather
    than a control plane that has not arrived yet.
    """
    pre = unit(CLUSTER_BOOTSTRAP)["Service"].get("ExecStartPre", [])

    assert pre, (
        "no ExecStartPre: the seed would start applying against an API server "
        "that may not exist yet, and the retries would be unreadable"
    )
    probe = " ".join(pre)
    assert "/readyz" in probe, (
        "probe the apiserver's /readyz endpoint; it is the cheapest call that "
        "proves it is serving and needs no RBAC beyond the admin kubeconfig"
    )
    assert "exit 1" in probe, (
        "the probe must fail loudly rather than returning quietly, or a control "
        "plane that never arrives is indistinguishable from one that did"
    )
    assert probe_bound(unit(CLUSTER_BOOTSTRAP)["Service"]) > 0, (
        "the probe must declare a finite bound. `exit 1` alone is not enough: "
        "`until cond; do ...; done; exit 1` has an unreachable failure path and "
        "still loops forever, sharing TimeoutStartSec with the apply phases and "
        "consuming the whole budget before phase 1 runs — so systemd's kill gets "
        "attributed to the seed rather than to the control plane, which is the "
        "exact ambiguity this probe exists to remove"
    )
    assert "echo" in probe, (
        "the probe must say why it is waiting, or a stalled control plane is "
        "indistinguishable from a slow one in the journal"
    )


def probe_bound(service: dict[str, list[str]]) -> int:
    """Seconds the ExecStartPre probe is allowed to spend, from its own bound.

    The probe bounds itself by attempt count rather than a ``--timeout`` flag,
    so this reads ``seq N`` and multiplies by the loop's sleep. Returns 0 when
    no bound is declared, which the callers treat as a failure rather than as
    "costs nothing" — an unbounded probe costs the entire budget.
    """
    total = 0
    for step in service.get("ExecStartPre", []):
        attempts = re.findall(r"seq (\d+)", step)
        sleeps = re.findall(r"sleep (\d+)", step)
        if attempts and sleeps:
            total += int(attempts[0]) * int(sleeps[0])
    return total


def test_start_timeout_covers_every_bounded_step() -> None:
    """A budget smaller than its parts kills the unit mid-chain.

    systemd enforces TimeoutStartSec across ExecStartPre plus every ExecStart.
    If the bounded waits sum past it, the unit is killed partway through and the
    kill reads as a generic timeout instead of naming the phase that stalled —
    the same loss of attribution the probe above exists to prevent.

    Previously the four kubectl waits alone summed to 2100s against a 1800s
    budget.
    """
    service = unit(CLUSTER_BOOTSTRAP)["Service"]
    budget = int(service["TimeoutStartSec"][0])

    steps = service.get("ExecStartPre", []) + service.get("ExecStart", [])
    declared = sum(
        int(match) for step in steps for match in re.findall(r"--timeout=(\d+)s", step)
    )
    bound = probe_bound(service)

    assert budget > declared + bound, (
        f"TimeoutStartSec={budget}s does not cover the bounded steps "
        f"({declared}s of kubectl --timeout plus {bound}s of probe), so "
        f"systemd can kill the seed mid-chain and the failure loses its cause"
    )


def test_seed_waits_for_the_node_to_leave_notready_before_argo() -> None:
    commands = exec_starts(CLUSTER_BOOTSTRAP)
    cilium = next(i for i, c in enumerate(commands) if c.endswith("/00-cilium"))
    argocd = next(
        i for i, c in enumerate(commands) if c.endswith("/10-argocd-core")
    )
    waits = [
        c for c in commands[cilium + 1 : argocd] if "wait" in c and " node " in c
    ]
    assert waits and "--for=condition=Ready" in waits[0], (
        "without CNI the node stays NotReady and carries a NoSchedule taint, "
        "so every Argo pod would be Pending forever"
    )


def test_seed_waits_for_the_git_bridge_before_handing_over_to_argo() -> None:
    commands = exec_starts(CLUSTER_BOOTSTRAP)
    gitd = next(i for i, c in enumerate(commands) if c.endswith("/15-gitd"))
    root_app = next(
        i for i, c in enumerate(commands) if c.endswith("/20-root-app")
    )
    waits = commands[gitd + 1 : root_app]
    assert any(
        "deployment/bluefin-git-daemon" in c and "--namespace bluefin-system" in c
        for c in waits
    ), (
        "the root Application cannot sync until the daemon serving "
        "/var/lib/bluefin/cluster.git is up"
    )


def test_seed_is_ordered_after_both_prerequisite_units() -> None:
    """Ordering is required for both; hard dependency only for the repo.

    ``bluefin-cluster-repo.service`` is a base-OS unit and the seed has nothing
    to apply without the mirrored manifests, so it stays ``Requires=``.

    ``kubeadm-init.service`` must not be, and the distinction is what keeps this
    chain self-healing. A job that dies with ``result 'dependency'`` never runs,
    so its own ``Restart=on-failure`` never engages and systemd never re-queues
    it. Under ``Requires=``, a single failed kubeadm attempt killed this unit
    permanently — observed with kubeadm failing at 12:18:13, succeeding on retry
    at 12:18:59, and the seed staying inactive forever behind a working control
    plane.
    """
    bootstrap = unit(CLUSTER_BOOTSTRAP)["Unit"]

    for name in ("kubeadm-init.service", "bluefin-cluster-repo.service"):
        assert name in bootstrap["After"], f"{name} must be ordered before the seed"

    assert "bluefin-cluster-repo.service" in bootstrap["Requires"]
    assert "kubeadm-init.service" not in bootstrap.get("Requires", []), (
        "a hard requirement on kubeadm-init makes one transient kubeadm failure "
        "strand the seed permanently; use Wants= so Restart=on-failure converges"
    )
    assert "kubeadm-init.service" in bootstrap["Wants"]


def test_kubeadm_config_bootstraps_every_certificate_it_uses() -> None:
    documents = [
        document
        for document in yaml.safe_load_all(
            KUBEADM_CONFIG.read_text(encoding="utf-8")
        )
        if document
    ]
    kinds = {document["kind"]: document for document in documents}
    assert set(kinds) == {
        "InitConfiguration",
        "ClusterConfiguration",
        "KubeletConfiguration",
    }

    kubelet = kinds["KubeletConfiguration"]
    assert kubelet["serverTLSBootstrap"] is True, (
        "kubelet would otherwise generate a self-signed serving certificate"
    )
    assert kubelet["rotateCertificates"] is True
    assert kubelet["cgroupDriver"] == "systemd"


def test_kubeadm_config_does_not_restate_the_kubernetes_version() -> None:
    cluster = next(
        document
        for document in yaml.safe_load_all(
            KUBEADM_CONFIG.read_text(encoding="utf-8")
        )
        if document and document["kind"] == "ClusterConfiguration"
    )
    assert "kubernetesVersion" not in cluster, (
        "kubeadm derives the version from its own binary; restating it here "
        "forks the single source of truth in include/kubernetes.yml"
    )


def test_kubeadm_config_schedules_workload_on_the_only_node() -> None:
    init = next(
        document
        for document in yaml.safe_load_all(
            KUBEADM_CONFIG.read_text(encoding="utf-8")
        )
        if document and document["kind"] == "InitConfiguration"
    )
    assert init["nodeRegistration"]["taints"] == [], (
        "the default control-plane NoSchedule taint leaves every workload "
        "Pending on a single-node appliance"
    )
    assert (
        init["nodeRegistration"]["criSocket"]
        == "unix:///run/containerd/containerd.sock"
    )


def test_cluster_bootstrap_element_stages_units_config_and_helper() -> None:
    element = ELEMENT.read_text(encoding="utf-8")
    assert "path: files/os/systemd/system" in element
    assert "path: files/os/systemd/systemd-sysext.service.d" in element
    assert "path: files/kubernetes/kubeadm.yaml" in element
    assert "path: files/os/libexec" in element
    assert '"${OUT}/usr/share/bluefin/kubeadm.yaml"' in element
    assert '"${OUT}/usr/libexec/bluefin-cluster-repo"' in element
    assert "bluefin-server/os-cluster-bootstrap.bst" in STACK.read_text(
        encoding="utf-8"
    )


def test_stack_pulls_in_git_for_the_manifest_bridge() -> None:
    stack = STACK.read_text(encoding="utf-8")
    assert "freedesktop-sdk.bst:components/git.bst" in stack, (
        "bluefin-cluster-repo.service shells out to git; without it the root "
        "Application has nothing to sync from"
    )
    assert "bluefin-server/os-cluster-manifests.bst" in stack


def test_kubernetes_sysupdate_transfer_is_packaged_as_a_component() -> None:
    element = SYSUPDATE_ELEMENT.read_text(encoding="utf-8")
    assert "path: files/os/sysupdate.kubernetes.d" in element
    assert "target: /usr/lib/sysupdate.kubernetes.d" in element
    assert "bluefin-server/os-kubernetes-sysupdate.bst" in STACK.read_text(
        encoding="utf-8"
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
