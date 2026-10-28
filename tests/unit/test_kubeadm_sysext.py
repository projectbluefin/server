"""Contracts for the kubeadm worker sysext and the kernel options it relies on."""


import configparser
import re
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "files" / "kubeadm" / "sysext"
BIN = ROOT / "elements" / "kubeadm" / "kubeadm-bin.bst"
SYSEXT = ROOT / "elements" / "oci" / "kubeadm-sysext.bst"
IMAGE = ROOT / "elements" / "oci" / "bluefin-server-image.bst"
VERSIONS = ROOT / "include" / "kubeadm.yml"
KERNEL_PATCH = ROOT / "patches" / "freedesktop-sdk" / "0006-linux-kubernetes-cilium-networking.patch"


def unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def versions() -> dict[str, str]:
    return yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))["variables"]


def test_versions_stay_on_the_cluster_nodes_series() -> None:
    # Patch releases arrive through .github/workflows/track-binaries.yml; a
    # series change is a deliberate edit here (docs/skills/kubeadm-sysext.md).
    pinned = versions()
    series = {}
    for name, version in pinned.items():
        if name != "pause-image":
            assert re.fullmatch(r"\d+\.\d+\.\d+", version), name
            series[name] = version.rsplit(".", 1)[0]
    assert series == {
        "kubernetes-version": "1.35",
        "crictl-version": "1.35",
        "containerd-version": "2.1",
        "runc-version": "1.3",
        "cni-plugins-version": "1.1",
    }
    assert pinned["pause-image"] == "registry.k8s.io/pause:3.10.1"


def test_every_download_is_pinned_by_sha256() -> None:
    sources = yaml.safe_load(BIN.read_text(encoding="utf-8"))["sources"]
    assert len(sources) == 7
    for source in sources:
        assert source["kind"] in ("remote", "tar")
        assert re.fullmatch(r"[0-9a-f]{64}", source["ref"]), source["url"]
    urls = " ".join(s["url"] for s in sources)
    assert "containerd-static-%{containerd-version}-linux-amd64.tar.gz" in urls
    assert "runc.amd64" in urls
    for b in ("kubelet", "kubeadm", "kubectl"):
        assert f"k8s_dl:release/v%{{kubernetes-version}}/bin/linux/amd64/{b}" in urls


def test_binaries_land_where_booty_expects_them() -> None:
    text = BIN.read_text(encoding="utf-8")
    for b in ("kubelet", "kubeadm", "kubectl", "crictl", "containerd", "containerd-shim-runc-v2", "ctr"):
        assert re.search(rf"\b{re.escape(b)}\b", text)
    assert '"${bin}/runc"' in text
    assert '%{libexecdir}/cni' in text


def test_sysext_ships_nothing_under_opt() -> None:
    text = SYSEXT.read_text(encoding="utf-8") + BIN.read_text(encoding="utf-8")
    assert "sysext/opt" not in text and "install-root}/opt" not in text
    assert 'ERROR: sysext ships' in SYSEXT.read_text(encoding="utf-8")


def test_sysext_is_version_locked_and_in_the_signed_release_set() -> None:
    text = SYSEXT.read_text(encoding="utf-8")
    assert 'sysext-release: "kubeadm_%{image-version}"' in text
    assert 'sysext-image: "kubeadm_%{image-version}"' in text
    release = dict(
        line.split("=", 1) for line in (SRC / "extension-release.kubeadm").read_text().splitlines() if "=" in line
    )
    assert release == {"NAME": "kubeadm", "ID": "bluefin-server", "EXTENSION_RELOAD_MANAGER": "1"}
    image = IMAGE.read_text(encoding="utf-8")
    assert "filename: oci/kubeadm-sysext.bst" in image
    assert "/sysext/kubeadm/kubeadm_%{image-version}.raw.zst" in image
    assert "sha256sum --binary *.raw *.efi *.raw.zst *.spdx.json *.bu *.ign > SHA256SUMS" in image
    assert "oci/kubeadm-sysext.bst" in (ROOT / "Justfile").read_text(encoding="utf-8")


def test_the_sysext_preset_disables_its_units() -> None:
    lines = [
        line.split()
        for line in (SRC / "80-kubeadm.preset").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert lines == [
        ["disable", "containerd.service"],
        ["disable", "kubelet.service"],
        ["disable", "kubeadm-init.service"],
    ]


def test_containerd_config_keys() -> None:
    cfg = tomllib.loads((SRC / "config.toml").read_text(encoding="utf-8"))
    assert cfg["version"] == 3
    assert cfg["root"] == "/var/lib/containerd"
    assert cfg["state"] == "/run/containerd"
    assert cfg["grpc"]["address"] == "/run/containerd/containerd.sock"
    images = cfg["plugins"]["io.containerd.cri.v1.images"]
    assert images["pinned_images"]["sandbox"] == versions()["pause-image"]
    assert images["registry"]["config_path"] == "/etc/containerd/certs.d"
    assert cfg["imports"] == ["/usr/share/bluefin/containerd/conf.d/*.toml", "/etc/containerd/conf.d/*.toml"]
    runtime = cfg["plugins"]["io.containerd.cri.v1.runtime"]
    assert runtime["ignore_image_defined_volumes"] is True
    assert runtime["containerd"]["default_runtime_name"] == "runc"
    runc = runtime["containerd"]["runtimes"]["runc"]
    assert runc["runtime_type"] == "io.containerd.runc.v2"
    assert runc["options"] == {"BinaryName": "/usr/bin/runc", "SystemdCgroup": True}
    assert runtime["cni"] == {"bin_dirs": ["/opt/cni/bin", "/usr/libexec/cni"], "conf_dir": "/etc/cni/net.d"}


def test_etc_config_is_seeded_writable_before_containerd_starts() -> None:
    tmpfiles = (SRC / "tmpfiles-kubeadm.conf").read_text(encoding="utf-8")
    assert "C /etc/containerd/config.toml - - - - /usr/share/bluefin/containerd/config.toml" in tmpfiles
    assert "d /etc/containerd/conf.d 0755 root root -" in tmpfiles
    assert "C /etc/crictl.yaml - - - - /usr/share/bluefin/kubeadm/crictl.yaml" in tmpfiles
    service = (SRC / "containerd.service").read_text(encoding="utf-8")
    pre = [line.split("=", 1)[1] for line in service.splitlines() if line.startswith("ExecStartPre=")]
    assert pre[0] == "/usr/bin/systemd-tmpfiles --create kubeadm.conf"
    # The migration runs after tmpfiles (which may have just seeded the file
    # on a fresh install) and before the kubelet modules are loaded; once it
    # is idempotent an installed node from before `imports` existed picks up
    # the glob on the next containerd start (issue #351).
    # It is `-`-prefixed (best effort): a config the helper cannot rewrite
    # (immutable, read-only /etc) must not keep containerd from starting.
    assert "-/usr/libexec/bluefin-kubeadm-containerd-migrate" in pre
    assert pre.index("-/usr/libexec/bluefin-kubeadm-containerd-migrate") < pre.index("/usr/bin/modprobe overlay")
    assert "/usr/bin/modprobe br_netfilter" in pre
    assert pre.index("/usr/bin/modprobe br_netfilter") < pre.index("/usr/lib/systemd/systemd-sysctl 90-kubeadm.conf")
    svc = unit(SRC / "containerd.service")
    assert svc["Service"]["ExecStart"] == "/usr/bin/containerd"
    assert svc["Unit"]["RequiresMountsFor"] == "/var/lib/containerd"
    crictl = yaml.safe_load((SRC / "crictl.yaml").read_text(encoding="utf-8"))
    assert crictl["runtime-endpoint"] == "unix:///run/containerd/containerd.sock"


def test_kubeadm_sysext_ships_the_config_migration_helper() -> None:
    bst = SYSEXT.read_text(encoding="utf-8")
    assert "bluefin-kubeadm-containerd-migrate" in bst
    # The helper lives under %{libexecdir}, the same idiom every sibling
    # helper the images ship uses (bluefin-kubeadm-init, nvidia-load,
    # bluefin-homelab-apply); containerd.service calls it by its absolute
    # path, so the install path must match.
    assert 'sysext%{libexecdir}/bluefin-kubeadm-containerd-migrate' in bst
    helper = SRC / "bluefin-kubeadm-containerd-migrate"
    assert helper.exists(), "the helper script ships with the sysext"
    assert helper.stat().st_mode & 0o111, "the helper is executable"


def test_host_modules_and_sysctls() -> None:
    assert [m for m in (SRC / "modules-load-kubeadm.conf").read_text().splitlines() if m and m[0] != "#"] == [
        "overlay",
        "br_netfilter",
    ]
    sysctl = (SRC / "sysctl-90-kubeadm.conf").read_text()
    for key in ("net.ipv4.ip_forward", "net.bridge.bridge-nf-call-iptables", "net.bridge.bridge-nf-call-ip6tables"):
        assert f"{key} = 1" in sysctl


def test_kubelet_units_follow_kubeadm() -> None:
    kubelet = unit(SRC / "kubelet.service")["Service"]
    assert kubelet["RestartSec"] == "10" and kubelet["Restart"] == "always"
    dropin = (SRC / "10-kubeadm.conf").read_text(encoding="utf-8")
    for needle in (
        "--bootstrap-kubeconfig=/etc/kubernetes/bootstrap-kubelet.conf --kubeconfig=/etc/kubernetes/kubelet.conf",
        "--config=/var/lib/kubelet/config.yaml",
        "EnvironmentFile=-/var/lib/kubelet/kubeadm-flags.env",
        "EnvironmentFile=-/etc/default/kubelet",
        "--volume-plugin-dir=/var/lib/kubelet/volumeplugins",
        "ExecStart=\nExecStart=/usr/bin/kubelet ",
    ):
        assert needle in dropin


@pytest.mark.parametrize(
    "option",
    [
        "VXLAN", "GENEVE", "NET_CLS_BPF", "NET_SCH_INGRESS", "NET_ACT_BPF",
        "INET_DIAG", "INET_TCP_DIAG", "INET_UDP_DIAG",
        "NETFILTER_XT_TARGET_NOTRACK",
    ],
)
def test_kernel_options_are_added_as_modules(option: str) -> None:
    added = [line[1:] for line in KERNEL_PATCH.read_text().splitlines() if line.startswith("+") and not line.startswith("+++")]
    assert f"module {option}" in added


def test_kernel_patch_targets_fsdk_linux_config_script() -> None:
    text = KERNEL_PATCH.read_text()
    assert "+++ b/files/linux/fdsdk-config.sh" in text
    assert "+enable INET_DIAG_DESTROY" in text
