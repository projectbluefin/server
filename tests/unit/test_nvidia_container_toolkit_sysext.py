"""Contracts for the NVIDIA Container Toolkit (CDI) sysext."""


import re
import subprocess
import tomllib
from pathlib import Path

import yaml

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "files" / "nvidia-container-toolkit" / "sysext"
DROPIN = SRC / "nvidia-cdi-refresh-bluefin.conf"
TOOLKIT = ROOT / "elements" / "nvidia" / "nvidia-container-toolkit.bst"
SYSEXT = ROOT / "elements" / "oci" / "nvidia-container-toolkit-sysext.bst"
VERSIONS = ROOT / "include" / "nvidia-container-toolkit.yml"
CONTAINERD_CONFIG = ROOT / "files" / "kubeadm" / "sysext" / "config.toml"
CONTAINERD_DROPIN = SRC / "containerd-nvidia-container-runtime.toml"
CONTAINERD_DROPIN_PATH = "/usr/share/bluefin/containerd/conf.d/nvidia-container-runtime.toml"

# The legacy stack: the plain runtime (mode "auto" resolves to it), the OCI
# prestart hook and libnvidia-container.
FORBIDDEN = ("nvidia-container-runtime.legacy", "libnvidia-container", "runtime-hook", "oci-hook", "hooks.d")


def element(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def commands(path: Path) -> str:
    config = element(path)["config"]
    return "\n".join(line for key in ("build-commands", "install-commands") for line in config.get(key, []))


def test_version_is_pinned_once_and_the_source_by_the_tags_commit() -> None:
    atoms = yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))["variables"]
    version, commit = atoms["nvidia-container-toolkit-version"], atoms["nvidia-container-toolkit-commit"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert re.fullmatch(r"[0-9a-f]{40}", commit)
    [source] = element(TOOLKIT)["sources"]
    assert source["kind"] == "git_repo"
    assert source["url"] == "github:NVIDIA/nvidia-container-toolkit.git"
    # git-describe form, exactly on the tag: BuildStream fetches the tag and
    # that commit, and the tracker moves both atoms together.
    assert source["ref"] == "v%{nvidia-container-toolkit-version}-0-g%{nvidia-container-toolkit-commit}"
    for path in (TOOLKIT, SYSEXT):
        text = path.read_text(encoding="utf-8")
        assert version not in text and commit not in text, path
        assert "include/nvidia-container-toolkit.yml" in element(path)["(@)"]


def test_builds_offline_from_the_vendored_modules() -> None:
    env = element(TOOLKIT)["environment"]
    assert "-mod=vendor" in env["GOFLAGS"].split()
    assert env["GOTOOLCHAIN"] == "local"
    assert "freedesktop-sdk.bst:components/go.bst" in element(TOOLKIT)["build-depends"]


def test_only_the_cdi_binaries_are_built_and_shipped() -> None:
    build = commands(TOOLKIT)
    assert re.search(r"for cmd in nvidia-ctk nvidia-cdi-hook nvidia-container-runtime\.cdi; do", build)
    assert 'go build -o "${cmd}"' in build and '"./cmd/${cmd}"' in build
    assert 'install -D -m 0755 -t "%{install-root}%{bindir}" nvidia-ctk nvidia-cdi-hook nvidia-container-runtime.cdi' in build
    assert "./cmd/nvidia-container-runtime\n" not in build and '"./cmd/nvidia-container-runtime"' not in build, (
        "the plain runtime takes its mode from /etc and defaults to the legacy stack"
    )
    shipped = build + commands(SYSEXT) + "".join(p.read_text() for p in SRC.iterdir())
    for name in FORBIDDEN:
        assert name not in shipped, name
    for spec in ("nvidia.yaml",):
        assert spec not in shipped, f"no CDI spec is baked in ({spec})"
    assert "/etc/nvidia-container-runtime" not in shipped, "no runtime config: the .cdi binary needs none"


def test_the_runtime_is_the_cdi_variant_under_the_expected_name() -> None:
    build = commands(TOOLKIT)
    assert 'ln -s nvidia-container-runtime.cdi "%{install-root}%{bindir}/nvidia-container-runtime"' in build
    sysext = commands(SYSEXT)
    assert "for bin in nvidia-ctk nvidia-cdi-hook nvidia-container-runtime.cdi; do" in sysext
    assert '[ "$(readlink "sysext%{bindir}/nvidia-container-runtime")" = nvidia-container-runtime.cdi ]' in sysext


def test_containerd_gets_the_nvidia_handler_only_with_the_sysext() -> None:
    sysext = commands(SYSEXT)
    assert f'"sysext{CONTAINERD_DROPIN_PATH.replace("/usr/share", "%{datadir}")}"' in sysext
    assert "install -D -m 0644 sysext-src/containerd-nvidia-container-runtime.toml" in sysext
    dropin = tomllib.loads(CONTAINERD_DROPIN.read_text(encoding="utf-8"))
    assert dropin["version"] == 3
    runtime = dropin["plugins"]["io.containerd.cri.v1.runtime"]
    assert set(runtime) == {"containerd"} and set(runtime["containerd"]) == {"runtimes"}, "no default_runtime_name"
    nvidia = runtime["containerd"]["runtimes"]
    assert set(nvidia) == {"nvidia"}
    assert nvidia["nvidia"]["runtime_type"] == "io.containerd.runc.v2"
    assert nvidia["nvidia"]["options"] == {"BinaryName": "/usr/bin/nvidia-container-runtime", "SystemdCgroup": True}
    # The kubeadm sysext's containerd imports the sysext's conf.d by glob, so a
    # node without the toolkit has no "nvidia" handler and nothing to import.
    config = tomllib.loads(CONTAINERD_CONFIG.read_text(encoding="utf-8"))
    assert str(Path(CONTAINERD_DROPIN_PATH).parent / "*.toml") in config["imports"]
    assert "/etc/containerd/conf.d/*.toml" in config["imports"]


def test_upstream_cdi_units_are_wired_into_multi_user() -> None:
    build = commands(TOOLKIT)
    for unit in ("deployments/systemd/nvidia-cdi-refresh.service", "deployments/systemd/nvidia-cdi-refresh.path"):
        assert unit in build
    assert "deployments/systemd/10-container-engines.conf" in build
    assert "90-nvidia-container-toolkit.preset" not in build
    sysext = commands(SYSEXT)
    assert 'mkdir -p "${unitdir}/multi-user.target.wants"' in sysext
    assert "for u in nvidia-cdi-refresh.service nvidia-cdi-refresh.path; do" in sysext
    assert 'ln -s "../${u}" "${unitdir}/multi-user.target.wants/${u}"' in sysext
    assert '"${unitdir}/nvidia-cdi-refresh.service.d/50-bluefin.conf"' in sysext


def test_driver_units_are_ordered_after_but_never_required() -> None:
    dropin = SystemdFile(DROPIN)
    assert set(dropin.words("Unit", "After")) == {"nvidia-ldconfig.service", "nvidia-device-nodes.service"}
    for key in ("Requires", "Requisite", "BindsTo", "PartOf", "Upholds"):
        assert not dropin.values("Unit", key), key


def _pci_device(root: Path, name: str, vendor: str, klass: str) -> None:
    device = root / name
    device.mkdir(parents=True)
    (device / "vendor").write_text(vendor + "\n")
    (device / "class").write_text(klass + "\n")


def _gpu_condition(sysfs: Path) -> int:
    [argv] = SystemdFile(DROPIN).commands("ExecCondition")
    assert argv[:2] == ["/bin/sh", "-c"]
    script = argv[2].replace("/sys/bus/pci/devices", str(sysfs))
    return subprocess.run(["sh", "-c", script], check=False).returncode


def test_refresh_is_skipped_not_failed_without_an_nvidia_gpu(tmp_path: Path) -> None:
    # ExecCondition= exit codes 1-254 skip the unit; 0 runs it.
    sysfs = tmp_path / "devices"
    sysfs.mkdir()
    assert _gpu_condition(sysfs) == 1
    _pci_device(sysfs, "0000:00:01.0", "0x8086", "0x030000")
    _pci_device(sysfs, "0000:00:02.0", "0x10de", "0x040300")
    assert _gpu_condition(sysfs) == 1
    _pci_device(sysfs, "0000:01:00.0", "0x10de", "0x030000")
    assert _gpu_condition(sysfs) == 0
    three_d = tmp_path / "3d"
    _pci_device(three_d, "0000:02:00.0", "0x10de", "0x030200")
    assert _gpu_condition(three_d) == 0


# The ExecCondition= of upstream's deployments/systemd/nvidia-cdi-refresh.service (v1.20.1).
UPSTREAM_REFRESH = """[Service]
Type=oneshot
ExecCondition=/bin/sh -c '/usr/bin/grep -qE "/(nvidia|nvidia-current)[.]ko" /lib/modules/%v/modules.dep || [ -e /dev/dxg ]'
ExecStart=/usr/bin/nvidia-ctk cdi generate
"""


def test_refresh_runs_on_a_gpu_node_although_the_base_module_index_lacks_nvidia(tmp_path: Path) -> None:
    upstream = tmp_path / "nvidia-cdi-refresh.service"
    upstream.write_text(UPSTREAM_REFRESH)
    [argv] = SystemdFile(upstream, DROPIN).commands("ExecCondition")
    assert "modules.dep" not in " ".join(argv), "the driver's modules are never in the base image's index"
    sysfs = tmp_path / "devices"
    _pci_device(sysfs, "0000:01:00.0", "0x10de", "0x030000")
    script = argv[2].replace("/sys/bus/pci/devices", str(sysfs))
    assert subprocess.run(["sh", "-c", script], check=False).returncode == 0


def test_own_version_axis_not_locked_to_the_image() -> None:
    release = dict(
        line.split("=", 1)
        for line in (SRC / "extension-release.nvidia-container-toolkit").read_text().splitlines()
        if "=" in line
    )
    assert release == {"NAME": "nvidia-container-toolkit", "ID": "_any", "EXTENSION_RELOAD_MANAGER": "1"}
    variables = element(SYSEXT)["variables"]
    assert variables["sysext-release"] == "nvidia-container-toolkit"
    assert variables["sysext-image"] == "nvidia-container-toolkit-%{nvidia-container-toolkit-version}"
    assert variables["sysext-version"] == "%{nvidia-container-toolkit-version}"
    assert "include/image.yml" not in element(SYSEXT)["(@)"]
    assert "image-version" not in SYSEXT.read_text(encoding="utf-8")


def test_sysext_ships_only_usr() -> None:
    sysext = commands(SYSEXT)
    assert 'ERROR: sysext ships' in sysext
    for text in (commands(TOOLKIT), sysext):
        assert "install-root}/etc" not in text and "sysext/etc" not in text and "sysext/opt" not in text


def test_kubeadm_containerd_keeps_cdi_on_and_runc_as_the_default() -> None:
    # containerd 2.1 defaults: enable_cdi = true, cdi_spec_dirs = ["/etc/cdi", "/var/run/cdi"].
    runtime = tomllib.loads(CONTAINERD_CONFIG.read_text(encoding="utf-8"))["plugins"]["io.containerd.cri.v1.runtime"]
    assert runtime.get("enable_cdi", True) is True
    assert "/var/run/cdi" in runtime.get("cdi_spec_dirs", ["/etc/cdi", "/var/run/cdi"])
    assert runtime["containerd"]["default_runtime_name"] == "runc"
    assert "nvidia" not in runtime["containerd"]["runtimes"], "the handler comes from the toolkit sysext's drop-in"


def test_justfile_validates_builds_and_exports_the_sysext() -> None:
    justfile = (ROOT / "Justfile").read_text(encoding="utf-8")
    validate = next(line for line in justfile.splitlines() if "just bst show --deps all" in line)
    assert "oci/nvidia-container-toolkit-sysext.bst" in validate
    assert "just bst build oci/nvidia-container-toolkit-sysext.bst" in justfile
    assert "just bst artifact checkout oci/nvidia-container-toolkit-sysext.bst" in justfile
