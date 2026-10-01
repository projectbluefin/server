"""Contracts for the NVIDIA open-kernel-module driver sysexts (include/nvidia.yml)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from _systemd import SystemdFile, preset_rules

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "files" / "nvidia" / "sysext"
FLAVOURS_FILE = ROOT / "include" / "nvidia.yml"
RECIPE = ROOT / "include" / "nvidia-driver.yml"
ELEMENTS = ROOT / "elements"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def pins() -> dict[str, str]:
    return load(FLAVOURS_FILE)["variables"]


def flavours() -> list[str]:
    return sorted(name.removesuffix("-version") for name in pins() if name.endswith("-version"))


def recipe() -> dict[str, str]:
    return load(RECIPE)["variables"]


def units() -> list[str]:
    return sorted(path.name for path in SRC.glob("*.service"))


def element_files(flavour: str) -> dict[str, Path]:
    return {
        "driver": ELEMENTS / "nvidia" / f"{flavour}.bst",
        "signed": ELEMENTS / "nvidia" / f"{flavour}-signed.bst",
        "sysext": ELEMENTS / "oci" / f"{flavour}-sysext.bst",
    }


def test_flavour_table_matches_the_element_files() -> None:
    assert flavours() == ["nvidia-open-595"]
    assert set(pins()) == {f"{f}-{atom}" for f in flavours() for atom in ("version", "sha256")}
    on_disk = sorted(p.stem for p in (ELEMENTS / "nvidia").glob("nvidia-open-*.bst") if not p.stem.endswith("-signed"))
    assert on_disk == flavours()
    assert sorted(p.name.removesuffix("-sysext.bst") for p in (ELEMENTS / "oci").glob("nvidia-open-*-sysext.bst")) == flavours()


@pytest.mark.parametrize("flavour", flavours())
def test_flavour_pins_a_release_of_its_own_branch(flavour: str) -> None:
    branch = flavour.removeprefix("nvidia-open-")
    assert re.fullmatch(rf"{branch}\.\d+(\.\d+)?", pins()[f"{flavour}-version"])
    assert re.fullmatch(r"[0-9a-f]{64}", pins()[f"{flavour}-sha256"])


@pytest.mark.parametrize("flavour", flavours())
def test_every_flavour_element_uses_the_shared_recipe(flavour: str) -> None:
    for role, path in element_files(flavour).items():
        element = load(path)
        assert {"include/nvidia.yml", "include/nvidia-driver.yml"} <= set(element["(@)"]), path
        assert element["variables"]["nvidia-flavour"] == flavour, path
        assert element["variables"]["nvidia-version"] == f"%{{{flavour}-version}}", path
        assert "strip-binaries" not in element["variables"], "set once, empty, in the recipe"
    assert recipe()["strip-binaries"] == "", "NVIDIA's binaries ship unmodified"


@pytest.mark.parametrize("flavour", flavours())
def test_the_run_file_is_pinned_by_sha256(flavour: str) -> None:
    (source,) = load(element_files(flavour)["driver"])["sources"]
    assert source["kind"] == "remote"
    assert source["url"] == (
        "nvidia_download:XFree86/Linux-x86_64/%{nvidia-version}/NVIDIA-Linux-x86_64-%{nvidia-version}.run"
    )
    assert source["ref"] == f"%{{{flavour}-sha256}}"
    assert load(ROOT / "include" / "aliases.yml")["aliases"]["nvidia_download"] == "https://download.nvidia.com/"


def test_only_the_open_kernel_modules_are_built() -> None:
    build = recipe()["nvidia-driver-build"] + recipe()["nvidia-driver-install"]
    assert re.findall(r"make -C (\S+)", build) == ["payload/kernel-open", "payload/kernel-open"]
    assert "payload/kernel " not in build and "payload/kernel/" not in build
    assert "INSTALL_MOD_DIR=extra/nvidia" in build
    assert build.count('NV_KERNEL_MODULES="%{nvidia-modules}"') == 2
    assert recipe()["nvidia-modules"].split() == ["nvidia", "nvidia-uvm", "nvidia-modeset", "nvidia-drm"]


def test_the_makeself_wrapper_is_never_executed() -> None:
    build = recipe()["nvidia-driver-build"]
    assert '"${run}"' in build and "sh ${run}" not in build and "./${run}" not in build
    assert "chmod" not in build


@pytest.mark.parametrize("flavour", flavours())
def test_modules_are_signed_with_the_module_key(flavour: str) -> None:
    signed = load(element_files(flavour)["signed"])
    assert signed["config"]["install-commands"] == ["%{nvidia-sign}"]
    deps = [d if isinstance(d, str) else d["filename"] for d in signed["build-depends"]]
    assert "bluefin-server/keys/boot-keys.bst" in deps and f"nvidia/{flavour}.bst" in deps
    sign = recipe()["nvidia-sign"]
    assert "sign-file sha512 /boot-keys/linux-module-cert.key module-cert.der" in sign
    assert 'modinfo -F sig_hashalgo "${ko}")" != sha512' in sign


def test_the_headless_userspace_subset_ships_whole() -> None:
    libs = recipe()["nvidia-libs"].split()
    for lib in ("libcuda", "libnvidia-ml", "libnvidia-ptxjitcompiler", "libnvidia-nvvm", "libnvidia-encode",
                "libnvcuvid", "libnvidia-opticalflow", "libnvidia-cfg", "libnvidia-gpucomp",
                "libEGL_nvidia", "libGLX_nvidia", "libnvidia-egl-gbm", "libnvidia-opencl"):
        assert lib in libs
    assert recipe()["nvidia-tools"].split() == ["nvidia-smi", "nvidia-persistenced", "nvidia-modprobe", "nvidia-debugdump"]
    install = recipe()["nvidia-driver-install"]
    assert '$4 == "NATIVE"' in install, "no 32-bit libraries"
    for forbidden in ("nvidia-settings", "nvidia_drv", "nvidia-powerd", "nvngx", "WINE_LIB", "strip "):
        assert forbidden not in install
    for needle in (
        '%{datadir}/licenses/%{nvidia-flavour}/LICENSE',
        '%{indep-libdir}/firmware/nvidia/%{nvidia-version}',
        '%{datadir}/vulkan/icd.d/nvidia_icd.json',
        '%{datadir}/glvnd/egl_vendor.d/10_nvidia.json',
        '%{datadir}/egl/egl_external_platform.d/15_nvidia_gbm.json',
        '%{datadir}/OpenCL/vendors/nvidia.icd',
        'objdump -p',
    ):
        assert needle in install


@pytest.mark.parametrize("flavour", flavours())
def test_sysext_is_locked_to_the_image_version(flavour: str) -> None:
    sysext = load(element_files(flavour)["sysext"])
    assert {"include/image.yml", "include/sysext.yml", "include/arch.yml"} <= set(sysext["(@)"])
    for key, value in {
        "sysext-name": flavour,
        "sysext-image": f"{flavour}_%{{image-version}}",
        "sysext-release": f"{flavour}_%{{image-version}}",
        "sysext-version": "%{image-version}",
        "sysext-architecture": "%{systemd-arch}",
    }.items():
        assert sysext["variables"][key] == value
    assert sysext["config"]["install-commands"] == ["%{nvidia-sysext-stage}", "%{sysext-pack}"]
    assert {"path": "files/nvidia/sysext", "directory": "sysext-src", "kind": "local"} in sysext["sources"]
    deps = {d["filename"]: d["config"]["location"] for d in sysext["build-depends"] if isinstance(d, dict)}
    assert deps == {"bluefin-server/kernel-modules.bst": "/kernel-modules", f"nvidia/{flavour}-signed.bst": "/nvidia-driver"}


def test_extension_release_template() -> None:
    release = dict(line.split("=", 1) for line in (SRC / "extension-release.nvidia").read_text().splitlines())
    assert release == {"NAME": "@NVIDIA_FLAVOUR@", "ID": "bluefin-server", "EXTENSION_RELOAD_MANAGER": "1"}
    stage = recipe()["nvidia-sysext-stage"]
    assert '"${src}/extension-release.%{nvidia-flavour}"' in stage


def test_sysext_ships_nothing_outside_usr() -> None:
    text = RECIPE.read_text(encoding="utf-8")
    assert "ERROR: sysext ships" in recipe()["nvidia-sysext-stage"]
    assert "%{sysconfdir}" not in text and "install-root}/etc" not in text and "sysext/etc" not in text
    assert "/opt" not in text


def test_every_unit_is_installed_and_wanted_by_multi_user_target() -> None:
    stage = recipe()["nvidia-sysext-stage"]
    (listed,) = re.findall(r'^units="([^"]+)"', stage, re.M)
    assert sorted(listed.split()) == units() == [
        "nvidia-device-nodes.service",
        "nvidia-flavour-guard.service",
        "nvidia-ldconfig.service",
        "nvidia-load.service",
        "nvidia-persistenced.service",
    ]
    assert 'ln -s "../${u}" "${unitdir}/multi-user.target.wants/${u}"' in stage
    for name in ("modprobe-nvidia.conf", "sysusers-nvidia.conf", "tmpfiles-nvidia.conf"):
        assert f'"${{src}}/{name}"' in stage
    assert sorted(p.name for p in SRC.iterdir()) == sorted(
        units() + ["extension-release.nvidia", "modprobe-nvidia.conf", "sysusers-nvidia.conf", "tmpfiles-nvidia.conf"]
    )


def test_units_skip_themselves_without_an_nvidia_gpu() -> None:
    load_unit = SystemdFile(SRC / "nvidia-load.service")
    assert load_unit.words("Unit", "Requires") == ["nvidia-flavour-guard.service"]
    assert {"nvidia-flavour-guard.service", "systemd-sysext.service"} <= set(load_unit.words("Unit", "After"))
    assert load_unit.commands() == [
        ["/usr/libexec/bluefin-sysext-modules", "nvidia", "nvidia-uvm", "nvidia-modeset", "nvidia-drm"]
    ]
    nodes = SystemdFile(SRC / "nvidia-device-nodes.service")
    assert nodes.words("Unit", "After") == ["nvidia-load.service"]
    assert nodes.value("Unit", "ConditionPathIsDirectory") == "/sys/module/nvidia"
    persist = SystemdFile(SRC / "nvidia-persistenced.service")
    assert persist.value("Unit", "ConditionPathExists") == "/dev/nvidiactl"
    assert persist.commands("ExecStartPre") == [["/usr/bin/systemd-sysusers", "nvidia.conf"]]
    assert persist.commands() == [["/usr/bin/nvidia-persistenced", "--user", "nvidia-persistenced"]]
    ldconfig = SystemdFile(SRC / "nvidia-ldconfig.service")
    assert ldconfig.words("Unit", "After") == ["systemd-sysext.service"]
    assert ldconfig.commands() == [["/usr/bin/systemd-tmpfiles", "--create", "nvidia.conf"], ["/usr/bin/ldconfig", "-X"]]
    assert "Condition" not in " ".join(ldconfig.sections["Unit"]), "the cache must list the libraries on any node"


def fake_pci(tmp_path: Path, devices: list[tuple[str, str]]) -> Path:
    root = tmp_path / "devices"
    root.mkdir()
    for i, (vendor, cls) in enumerate(devices):
        dev = root / f"0000:00:0{i}.0"
        dev.mkdir()
        (dev / "vendor").write_text(vendor + "\n")
        (dev / "class").write_text(cls + "\n")
    return root


@pytest.mark.parametrize(
    "devices,present",
    [
        ([], False),
        ([("0x1af4", "0x010000"), ("0x1234", "0x030000")], False),
        ([("0x10de", "0x040300")], False),
        ([("0x8086", "0x060000"), ("0x10de", "0x030000")], True),
        ([("0x10de", "0x030200")], True),
    ],
)
def test_gpu_detection(tmp_path: Path, devices: list[tuple[str, str]], present: bool) -> None:
    (argv,) = SystemdFile(SRC / "nvidia-load.service").commands("ExecCondition")
    sysfs = str(fake_pci(tmp_path, devices))
    argv = [word.replace("/sys/bus/pci/devices", sysfs) for word in argv]
    result = subprocess.run(argv, capture_output=True, check=False)
    assert result.returncode == (0 if present else 1), "1 skips the unit; it never fails"


@pytest.mark.parametrize(
    "merged,ok",
    [
        (["nvidia-open-595_1"], True),
        (["nvidia-open-595_1", "nvidia-open-615_1"], False),
        (["nvidia-open-595_1", "zfs_1"], True),
        (["nvidia-open-595_1", "kubestellar_1"], True),
    ],
)
def test_flavour_guard(tmp_path: Path, merged: list[str], ok: bool) -> None:
    for name in merged:
        (tmp_path / f"extension-release.{name}").write_text("ID=bluefin-server\n")
    (argv,) = SystemdFile(SRC / "nvidia-flavour-guard.service").commands()
    argv = [word.replace("/usr/lib/extension-release.d", str(tmp_path)) for word in argv]
    assert argv[0] == "/usr/bin/sh"
    assert (subprocess.run(argv, capture_output=True, check=False).returncode == 0) is ok


def test_nouveau_stays_off_the_gpu() -> None:
    lines = [line for line in (SRC / "modprobe-nvidia.conf").read_text().splitlines() if line and line[0] != "#"]
    assert "blacklist nouveau" in lines and "options nouveau modeset=0" in lines


def test_nothing_in_the_base_image_enables_or_ships_the_driver() -> None:
    for preset in ROOT.joinpath("files").rglob("*.preset"):
        for verb, pattern in preset_rules(preset):
            assert not (verb == "enable" and "nvidia" in pattern), preset
    # /usr carries at most the opt-in delivery plumbing (sysupdate transfers,
    # the toolkit's activation units), never an NVIDIA build element.
    for element in (*(ELEMENTS / "bluefin-server").rglob("*.bst"), ELEMENTS / "oci" / "bluefin-server-usr.bst"):
        text = element.read_text(encoding="utf-8")
        assert "nvidia/" not in text and "oci/nvidia-" not in text, element


@pytest.mark.parametrize("flavour", flavours())
def test_every_flavour_is_in_the_signed_release_set(flavour: str) -> None:
    image = (ELEMENTS / "oci" / "bluefin-server-image.bst").read_text(encoding="utf-8")
    assert f"filename: oci/{flavour}-sysext.bst" in image
    assert f"/sysext/{flavour}/{flavour}_%{{image-version}}.raw.zst" in image
    outer_inventory = image.rsplit('cd "%{install-root}"', 1)[1]
    command = next(line for line in outer_inventory.splitlines() if "> SHA256SUMS" in line)
    assert "*.raw.zst" in command.split()
    publish = (ROOT / "scripts" / "publish-release.sh").read_text(encoding="utf-8")
    assert f'"{flavour}_${{v}}\\\\.raw\\\\.zst"' in publish




@pytest.mark.parametrize("flavour", flavours())
def test_installed_nodes_follow_the_image_through_an_opt_in_feature(flavour: str) -> None:
    sysupdate = ROOT / "files" / "os" / "sysupdate.d"
    assert (sysupdate / f"{flavour}.feature").is_file()
    assert len(list(sysupdate.glob(f"[0-9][0-9]-{flavour}.transfer"))) == 1


@pytest.mark.parametrize("flavour", flavours())
def test_just_targets_build_every_flavour(flavour: str) -> None:
    justfile = (ROOT / "Justfile").read_text(encoding="utf-8")
    assert 'build-nvidia-sysext FLAVOUR="nvidia-open-595": gen-dev-keys' in justfile
    assert "just bst build oci/{{FLAVOUR}}-sysext.bst" in justfile
    assert f"oci/{flavour}-sysext.bst" in justfile, "just validate resolves every flavour"
