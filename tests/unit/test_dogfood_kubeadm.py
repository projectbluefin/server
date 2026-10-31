"""The kubeadm control-plane QEMU check stays tied to what the sysext ships.

``scripts/dogfood-kubeadm.sh`` is run by hand (it needs guest internet), so
nothing else notices when a unit is renamed or a path moves under it.
"""


import re
from pathlib import Path

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dogfood-kubeadm.sh"
DISKLESS = ROOT / "scripts" / "dogfood-diskless.sh"
SRC = ROOT / "files" / "kubeadm" / "sysext"
TEXT = SCRIPT.read_text(encoding="utf-8")


def test_ignition_links_the_unit_the_sysext_installs() -> None:
    wanted_by = SystemdFile(SRC / "kubeadm-init.service").words("Install", "WantedBy")
    assert f'"path": "/etc/systemd/system/{wanted_by[0]}.wants/kubeadm-init.service"' in TEXT
    assert '"target": "/usr/lib/systemd/system/kubeadm-init.service"' in TEXT
    sysext = (ROOT / "elements" / "oci" / "kubeadm-sysext.bst").read_text(encoding="utf-8")
    assert 'unitdir="${lib}/systemd/system"' in sysext and 'lib="sysext%{indep-libdir}"' in sysext
    assert '"path": "/etc/extensions/${name}.raw"' in TEXT
    assert '"verification": {"hash": "sha256-${sum}"}' in TEXT


def test_probe_checks_the_paths_the_init_unit_uses() -> None:
    seed = (SRC / "init-tmpfiles.conf").read_text(encoding="utf-8")
    script = (SRC / "bluefin-kubeadm-init").read_text(encoding="utf-8")
    for path in ("/etc/kubernetes/bluefin/init.yaml", "/usr/share/bluefin/kubeadm/init.yaml"):
        assert path in seed and path in TEXT
    assert "kubeconfig=/etc/kubernetes/admin.conf" in TEXT and "admin=/etc/kubernetes/admin.conf" in script
    assert "enabled=enabled,enabled," in TEXT and "systemctl enable containerd.service kubelet.service" in script


def test_every_asserted_probe_key_is_emitted() -> None:
    emitted = {m[1] for t in (TEXT, DISKLESS.read_text(encoding="utf-8")) for line in t.splitlines()
               if "echo" in line for m in re.finditer(r"(?:PROBE | )([a-z][a-z-]*)=", line)}
    asserted = {m[1] for line in TEXT.splitlines() if line.startswith("grep")
                for m in re.finditer(r"PROBE ([a-z][a-z-]*)=", line)}
    assert asserted and asserted <= emitted


def test_test_only_cni_is_pinned_and_recipe_exists() -> None:
    assert re.search(r"^cilium_sha256=[0-9a-f]{64}$", TEXT, re.M)
    assert 'sha256sum -c --quiet -' in TEXT
    assert "dogfood-kubeadm:\n    bash scripts/dogfood-kubeadm.sh dist/diskless" in (ROOT / "Justfile").read_text(encoding="utf-8")
