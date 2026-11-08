"""Contracts for the homelab Ignition templates (files/homelab/templates).

Four templates, one per runtime and role: Butane has no conditionals and the
role decides which units are linked (a node must never run kubeadm init or
start a k0s controller), so the role is the file one picks. Each .bu is the
source; the .ign next to it is its compiled Ignition 3.6 config (`just
homelab-templates`, pinned butane; `just homelab-templates 1` checks
byte-for-byte). Here the .ign is checked against the .bu semantically, so
the gate needs neither podman nor the network.
"""


import base64
import gzip
import json
import re
import urllib.parse
from pathlib import Path

import pytest
import yaml

from _systemd import SystemdFile, preset

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "files" / "homelab" / "templates"
EXAMPLE = ROOT / "files" / "homelab" / "sysext" / "homelab.conf.example"
SYSUPDATE = ROOT / "files" / "os" / "sysupdate.d"
PRESETS = sorted((ROOT / "files" / "os" / "systemd" / "system-preset").glob("*.preset"))
JUSTFILE = ROOT / "Justfile"

UNIT_DIRS = [
    ROOT / "files" / "os" / "systemd" / "system",
    ROOT / "files" / "kubeadm" / "sysext",
    ROOT / "files" / "k0s" / "sysext",
]

CONF = "/etc/bluefin/homelab.conf"
SEED = "/etc/bluefin/homelab.conf.template"

# The add-on sysexts' features: a control plane turns them on (only it
# applies them); a node does not need them.
ADDONS = ("argo-workflows", "mcp", "kubestellar")

# name: (runtime, role, sysupdate features, units enabled by preset, links)
EXPECTED = {
    "homelab-control-plane": (
        "kubeadm",
        "control-plane",
        {"kubeadm", "homelab", *ADDONS},
        {"sshd.service", "bluefin-sysext-fetch.service"},
        {"kubeadm-init.service"},
    ),
    "homelab-node": (
        "kubeadm",
        "node",
        {"kubeadm", "homelab"},
        {"sshd.service", "bluefin-sysext-fetch.service"},
        set(),
    ),
    "homelab-k0s-control-plane": (
        "k0s",
        "control-plane",
        {"homelab", *ADDONS},
        {"sshd.service", "bluefin-sysext-fetch.service", "k0s-first-boot.service"},
        set(),
    ),
    "homelab-k0s-node": (
        "k0s",
        "node",
        {"homelab"},
        {"sshd.service", "bluefin-sysext-fetch.service"},
        {"k0s-first-boot-fetch.service"},
    ),
}

MONITORING = ("KUBE_PROMETHEUS_STACK", "LOKI", "ALLOY")


def butane(name: str) -> dict:
    return yaml.safe_load((TEMPLATES / f"{name}.bu").read_text(encoding="utf-8"))


def ignition(name: str) -> dict:
    return json.loads((TEMPLATES / f"{name}.ign").read_text(encoding="utf-8"))


def data_url(contents: dict) -> str:
    """Decode an Ignition data: URL (plain or gzip+base64), as Ignition does."""
    source = contents["source"]
    assert source.startswith("data:"), source
    meta, _, payload = source[len("data:") :].partition(",")
    raw = base64.b64decode(payload) if meta.endswith(";base64") else urllib.parse.unquote_to_bytes(payload)
    if contents.get("compression") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8")


def bu_files(name: str) -> dict[str, dict]:
    return {f["path"]: f for f in butane(name)["storage"]["files"]}


def ign_files(name: str) -> dict[str, dict]:
    return {f["path"]: f for f in ignition(name)["storage"]["files"]}


def bu_links(name: str) -> dict[str, dict]:
    return {link["path"]: link for link in butane(name)["storage"].get("links", [])}


def conf(name: str) -> str:
    return bu_files(name)[SEED]["contents"]["inline"]


def settings(text: str) -> dict[str, str]:
    """The KEY=value lines systemd's EnvironmentFile= would read."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            out[key] = value
    return out


def unit_file(unit: str) -> Path | None:
    return next((d / unit for d in UNIT_DIRS if (d / unit).exists()), None)


def test_every_template_is_listed_and_paired() -> None:
    assert sorted(p.stem for p in TEMPLATES.glob("*.bu")) == sorted(EXPECTED)
    assert sorted(p.stem for p in TEMPLATES.glob("*.ign")) == sorted(EXPECTED)
    assert {p.name for p in TEMPLATES.iterdir()} == {f"{n}.{e}" for n in EXPECTED for e in ("bu", "ign")}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_butane_source_is_fcos_1_7_and_committed_ignition_is_3_6(name: str) -> None:
    bu = butane(name)
    assert (bu["variant"], bu["version"]) == ("fcos", "1.7.0")
    assert ignition(name)["ignition"]["version"] == "3.6.0"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_committed_ignition_matches_butane_source(name: str) -> None:
    """The committed .ign says what the YAML-parsed .bu says.

    Butane is not run here: `just homelab-templates 1` recompiles and compares
    byte-for-byte.
    """
    bu, ign = butane(name), ignition(name)
    bfiles, ifiles = bu_files(name), ign_files(name)
    assert bfiles.keys() == ifiles.keys()
    for path, f in bfiles.items():
        assert data_url(ifiles[path]["contents"]) == f["contents"]["inline"], path
        assert ifiles[path]["mode"] == f["mode"], path
        assert ifiles[path].get("overwrite") is f.get("overwrite"), path
    ilinks = {link["path"]: link for link in ign["storage"].get("links", [])}
    assert {p: (link["target"], link.get("overwrite")) for p, link in ilinks.items()} == {
        p: (link["target"], link.get("overwrite")) for p, link in bu_links(name).items()
    }
    assert ign["systemd"]["units"] == bu["systemd"]["units"]
    assert [(u["name"], u["sshAuthorizedKeys"]) for u in ign["passwd"]["users"]] == [
        (u["name"], u["ssh_authorized_keys"]) for u in bu["passwd"]["users"]
    ]
    # Nothing else: no disks, no kernel arguments, no remote config.
    assert set(ign) == {"ignition", "passwd", "storage", "systemd"}
    assert set(ign["ignition"]) == {"version"}
    assert set(ign["storage"]) <= {"files", "links"}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_the_butane_source_is_self_contained(name: str) -> None:
    # The USB installer passes the .bu itself as the ignition.config
    # credential (Ignition >= 2.27 transpiles Butane at boot), so it cannot
    # reference local files the way `butane --files-dir` would resolve them.
    for f in butane(name)["storage"]["files"]:
        assert set(f["contents"]) == {"inline"}, f["path"]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_template_enables_exactly_its_units_and_features(name: str) -> None:
    runtime, role, features, units, links = EXPECTED[name]
    files = bu_files(name)
    enabled = {
        p.split("/")[3].removesuffix(".feature.d")
        for p, f in files.items()
        if p.startswith("/etc/sysupdate.d/")
    }
    assert enabled == features
    for feature in features:
        assert (SYSUPDATE / f"{feature}.feature").exists(), feature
        drop_in = files[f"/etc/sysupdate.d/{feature}.feature.d/50-homelab.conf"]["contents"]["inline"]
        assert drop_in == "[Feature]\nEnabled=true\n"
    bu = butane(name)
    assert {u["name"] for u in bu["systemd"]["units"]} == units
    assert all(u == {"name": u["name"], "enabled": True} for u in bu["systemd"]["units"])
    wants = "/etc/systemd/system/multi-user.target.wants/"
    assert {p.removeprefix(wants) for p in bu_links(name)} == links
    for path, link in bu_links(name).items():
        unit = path.removeprefix(wants)
        assert link["target"] == f"/usr/lib/systemd/system/{unit}"
        assert link["overwrite"] is True
        assert unit_file(unit) is not None, unit
    for unit in units - {"sshd.service"}:
        assert unit_file(unit) is not None, unit
        # Opt-in: only a provisioning config like this one enables it.
        assert preset(unit, PRESETS) == "disable", unit
    assert settings(conf(name))["HOMELAB_ROLE"] == role
    if runtime == "kubeadm":
        assert "k0s-first-boot.service" not in units | links
    else:
        assert "kubeadm" not in features and "kubeadm-init.service" not in links
    assert (role == "control-plane") == (set(ADDONS) <= features)
    if role == "node":
        assert not set(ADDONS) & features
        # A node never initialises a cluster or starts a k0s controller.
        assert not {"kubeadm-init.service", "k0s-first-boot.service"} & (units | links)


def test_the_k0s_control_plane_can_be_joined() -> None:
    # The k0s sysext's controller defaults to --single, which nodes cannot join.
    args = bu_files("homelab-k0s-control-plane")["/etc/sysconfig/k0s"]["contents"]["inline"]
    controller = settings(args)["K0S_CONTROLLER_ARGS"].split()
    assert "--single" not in controller
    assert {"--enable-worker", "--no-taints"} <= set(controller)
    unit = SystemdFile(ROOT / "files" / "k0s" / "sysext" / "k0scontroller.service")
    assert "-/etc/sysconfig/k0s" in unit.values("Service", "EnvironmentFile")


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_homelab_conf_is_seeded_once(name: str) -> None:
    # Ignition applies the config on every boot that carries it; the
    # template's copy creates homelab.conf only while it is absent, so edits
    # on an installed node, and a joined node's removal of its passphrase,
    # stay.
    files = bu_files(name)
    assert CONF not in files
    seed = files[SEED]
    assert seed["mode"] == 0o600 and seed["overwrite"] is True
    rule = files["/etc/tmpfiles.d/50-bluefin-homelab.conf"]["contents"]["inline"].split()
    assert rule == ["C", CONF, "-", "-", "-", "-", SEED]
    # Every file is rewritten on every application: idempotent.
    assert all(f.get("overwrite") is True for f in files.values())


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_template_carries_no_secret_and_monitoring_stays_off(name: str) -> None:
    text = (TEMPLATES / f"{name}.bu").read_text(encoding="utf-8")
    values = settings(conf(name))
    assert "HOMELAB_JOIN_PASSPHRASE" not in values
    assert not {f"HOMELAB_{m}" for m in MONITORING} & values.keys()
    assert "#HOMELAB_JOIN_PASSPHRASE=" in conf(name)
    assert not re.search(r"PRIVATE KEY|password_hash|passwordHash|ssh-(ed25519|rsa) AAAA[A-Za-z0-9+/]{20}", text)
    [user] = butane(name)["passwd"]["users"]
    assert user["name"] == "root" and set(user) == {"name", "ssh_authorized_keys"}
    # The key placeholder is an authorized_keys comment line: harmless until
    # replaced, and sshd allows root with a key only.
    assert [k.startswith("# REPLACE") for k in user["ssh_authorized_keys"]] == [True]


@pytest.mark.parametrize("name", ["homelab-control-plane", "homelab-k0s-control-plane"])
def test_control_plane_conf_is_the_example_with_the_role_set(name: str) -> None:
    # homelab.conf.example (shipped in the homelab sysext) is the one list of
    # keys, defaults and commented optional blocks; a control-plane template
    # is exactly that with its role set.
    example = EXAMPLE.read_text(encoding="utf-8")
    assert conf(name) == example.replace("#HOMELAB_ROLE=control-plane\n", "HOMELAB_ROLE=control-plane\n", 1)
    for block in ("METALLB_ADDRESSES", "ACME_EMAIL", "ARGOCD_ROOT_REPO", "NFS_SERVER", "DEMOCRATIC_CSI", "GPU_OPERATOR"):
        assert f"#HOMELAB_{block}=" in conf(name), block


@pytest.mark.parametrize("name", ["homelab-node", "homelab-k0s-node"])
def test_node_conf_uses_only_keys_of_the_example(name: str) -> None:
    keys = set(re.findall(r"^#?(HOMELAB_[A-Z_]+)=", conf(name), re.M))
    example_keys = set(re.findall(r"^#?(HOMELAB_[A-Z_]+)=", EXAMPLE.read_text(encoding="utf-8"), re.M))
    assert keys == {"HOMELAB_ROLE", "HOMELAB_JOIN_PASSPHRASE", "HOMELAB_CONTROL_PLANE"}
    assert keys <= example_keys
    assert conf("homelab-node") == conf("homelab-k0s-node")


def test_the_element_stages_exactly_the_templates_directory() -> None:
    element = yaml.safe_load((ROOT / "elements" / "homelab" / "homelab-templates.bst").read_text(encoding="utf-8"))
    assert element["kind"] == "import"
    assert element["sources"] == [{"kind": "local", "path": "files/homelab/templates"}]


def test_the_compiler_is_pinned() -> None:
    text = JUSTFILE.read_text(encoding="utf-8")
    image = re.search(r'butane_image := env\("BUTANE_IMAGE", "([^"]+)"\)', text)
    assert image is not None and re.search(r"@sha256:[0-9a-f]{64}$", image[1])
    assert "--strict" in text.split("homelab-templates CHECK")[1].split("\n\n")[0]
