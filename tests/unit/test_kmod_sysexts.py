"""Kernel-module sysexts ship no module index; the base image's helper loads them.

A modules.* index inside a sysext shadows the base image's and every other
module sysext's through the overlay. Each module sysext ships only its own
modules under /usr/lib/modules/<kver>/extra/<name>/, and its load unit runs
/usr/libexec/bluefin-sysext-modules (bluefin-host), which indexes the
merged tree under /run and loads through `modprobe -d`.

Every base-image unit that runs `systemd-sysext refresh` at boot is ordered
after the module load units: the refresh unmerges /usr for a moment, and a
load running then finds no module (zfs-load-module.service failed that way
in the boot test's A/B update, racing nvidia-container-toolkit-activate).
"""


import re
from pathlib import Path

import pytest
import yaml

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
ELEMENTS = ROOT / "elements"
HELPER = ROOT / "files" / "homelab" / "cluster" / "internal" / "host" / "kmods" / "kmods.go"
HELPER_PATH = "/usr/libexec/bluefin-sysext-modules"
ZFS_SRC = ROOT / "files" / "zfs" / "sysext"
NVIDIA_SRC = ROOT / "files" / "nvidia" / "sysext"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def nvidia_stage() -> str:
    return load(ROOT / "include" / "nvidia-driver.yml")["variables"]["nvidia-sysext-stage"]


def module_sysexts() -> dict[str, str]:
    out = {}
    for path in sorted((ELEMENTS / "oci").glob("*-sysext.bst")):
        element = load(path)
        deps = [d if isinstance(d, str) else d["filename"] for d in element.get("build-depends", [])]
        if any(d.endswith("-signed.bst") for d in deps):
            commands = "\n".join(element["config"]["install-commands"])
            out[path.name] = commands.replace("%{nvidia-sysext-stage}", nvidia_stage())
    return out


def test_the_module_sysexts_are_known() -> None:
    assert sorted(module_sysexts()) == ["nvidia-open-595-sysext.bst", "zfs-sysext.bst"]


@pytest.mark.parametrize("element", sorted(module_sysexts()))
def test_no_module_sysext_builds_or_ships_a_module_index(element: str) -> None:
    script = module_sysexts()[element]
    assert "depmod" not in script
    assert "modules.dep" not in script and "depmod-root" not in script
    assert re.search(r"find \S+ -name 'modules\.\*'", script), "the build must fail if a modules.* file would ship"
    deps = [d if isinstance(d, str) else d["filename"] for d in load(ELEMENTS / "oci" / element)["build-depends"]]
    assert "freedesktop-sdk.bst:components/kmod.bst" not in deps, "nothing in the sysext build runs kmod"


@pytest.mark.parametrize("element", sorted(module_sysexts()))
def test_modules_stay_locked_to_the_image_kernel(element: str) -> None:
    element_yaml = load(ELEMENTS / "oci" / element)
    deps = {d["filename"]: d["config"]["location"] for d in element_yaml["build-depends"] if isinstance(d, dict)}
    assert deps["bluefin-server/kernel-modules.bst"] == "/kernel-modules"
    script = module_sysexts()[element]
    assert 'kver="$(ls "/kernel-modules${moddir}")"' in script
    assert re.search(r'if \[ "\$\{(zfs|nv)_kver\}" != "\$\{kver\}" \]', script)


def test_each_sysext_keeps_its_modules_in_its_own_directory() -> None:
    zfs = module_sysexts()["zfs-sysext.bst"]
    assert 'mkdir "${moddir}/${kver}/extra/zfs"' in zfs
    assert 'mv "${moddir}/${kver}/extra/${m}.ko.zst" "${moddir}/${kver}/extra/zfs/"' in zfs
    assert 'rm -rf "sysext%{indep-libdir}/modules-load.d"' in zfs, "systemd-modules-load cannot find them"
    nvidia = nvidia_stage()
    assert '[ "$(ls -A "${modroot}/extra")" != nvidia ]' in nvidia
    driver = load(ROOT / "include" / "nvidia-driver.yml")["variables"]["nvidia-driver-install"]
    assert "INSTALL_MOD_DIR=extra/nvidia" in driver


def test_load_units_go_through_the_helper() -> None:
    zfs = SystemdFile(ZFS_SRC / "zfs-load-module.service")
    assert zfs.commands() == [[HELPER_PATH, "zfs"]]
    assert "systemd-sysext.service" in zfs.words("Unit", "After")
    nvidia = SystemdFile(NVIDIA_SRC / "nvidia-load.service")
    assert nvidia.commands() == [["/usr/libexec/nvidia-load"]]
    assert "systemd-sysext.service" in nvidia.words("Unit", "After")
    # nvidia-load evicts nouveau, then loads the four modules through the helper.
    text = (NVIDIA_SRC / "nvidia-load").read_text(encoding="utf-8")
    assert f'helper="${{NVIDIA_LOAD_HELPER:-{HELPER_PATH}}}"' in text
    assert 'modules="nvidia nvidia-uvm nvidia-modeset nvidia-drm"' in text
    assert '"${helper}" ${modules}' in text


@pytest.mark.parametrize("unit", sorted([*ZFS_SRC.glob("*.service"), *NVIDIA_SRC.glob("*.service")]), ids=lambda p: p.name)
def test_no_module_sysext_unit_runs_a_bare_modprobe(unit: Path) -> None:
    for argv in SystemdFile(unit).all_commands():
        text = " ".join(argv)
        assert not re.search(r"(^|[\s/'])modprobe(\s|$)", text), (unit.name, text)


def test_the_base_image_ships_the_tools_the_helper_runs() -> None:
    base = load(ELEMENTS / "bluefin-server" / "os-base.bst")["depends"]
    for dep in ("components/kmod.bst", "components/util-linux-full.bst", "public-stacks/runtime-gnu.bst"):
        assert f"freedesktop-sdk.bst:{dep}" in base


def test_the_helper_is_inert_in_the_base_image() -> None:
    for path in (ROOT / "files" / "os").rglob("*"):
        if path.is_file():
            assert "bluefin-sysext-modules" not in path.read_text(encoding="utf-8", errors="replace"), path


def test_the_helper_indexes_under_run_and_loads_with_modprobe_d() -> None:
    text = HELPER.read_text(encoding="utf-8")
    assert 'basedir := h.Env("BLUEFIN_KMOD_BASEDIR", "/run/bluefin/kmods")' in text
    assert 'h.Exec("depmod", "-b", tmp, kver)' in text
    assert '[]string{"modprobe", "-d", basedir, "-S", kver, "-a", "--"}' in text
    (links,) = re.findall(r"var linked = \[\]string\{([^}]+)\}", text)
    names = re.findall(r'"([^"]+)"', links)
    assert names[:3] == ["kernel", "extra", "updates"]
    assert all(not n.startswith("modules.") or n in (
        "modules.order", "modules.builtin", "modules.builtin.modinfo", "modules.builtin.ranges"
    ) for n in names)


def test_the_nvidia_guard_only_refuses_a_second_flavour() -> None:
    guard = (NVIDIA_SRC / "nvidia-flavour-guard.service").read_text(encoding="utf-8")
    assert "zfs" not in guard.lower()
    assert "extension-release.nvidia-open-*" in guard
    for unit in NVIDIA_SRC.glob("*.service"):
        assert "zfs" not in unit.read_text(encoding="utf-8").lower(), unit.name
    for unit in ZFS_SRC.glob("*.service"):
        assert "nvidia" not in unit.read_text(encoding="utf-8").lower(), unit.name


def test_docs_state_the_rule_once_and_no_exclusivity() -> None:
    skill = (ROOT / "docs" / "skills" / "systemd-sysext-extensions.md").read_text(encoding="utf-8")
    assert "## Kernel-module sysexts" in skill
    assert "ships no `modules.*` index" in skill
    for path in [ROOT / "AGENTS.md", ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"mutually\s+exclusive", text), path


OS_UNITS = ROOT / "files" / "os" / "systemd" / "system"
LOAD_UNITS = ("nvidia-load.service", "zfs-load-module.service")


def runs_sysext_refresh(unit: Path) -> bool:
    conf = SystemdFile(unit)
    commands = [c for key in ("ExecStartPre", "ExecStart", "ExecStartPost") for c in conf.values("Service", key)]
    return any(re.search(r"(^|/)systemd-sysext refresh\b", c.lstrip("-+!@:")) for c in commands)


def boot_refreshers() -> list[str]:
    # Units that run the refresh themselves, plus bluefin-sysext-fetch.service,
    # whose helper runs it (sysextfetch.go).
    fetch = ROOT / "files" / "homelab" / "cluster" / "internal" / "host" / "sysextfetch" / "sysextfetch.go"
    assert '{"systemd-sysext", "refresh"}' in fetch.read_text(encoding="utf-8")
    direct = [p.name for p in sorted(OS_UNITS.glob("*.service")) if runs_sysext_refresh(p)]
    return sorted(direct + ["bluefin-sysext-fetch.service"])


def test_the_load_units_and_boot_refreshers_are_known() -> None:
    assert sorted(p.name for p in NVIDIA_SRC.glob("nvidia-load.service")) + \
        sorted(p.name for p in ZFS_SRC.glob("zfs-load-module.service")) == list(LOAD_UNITS)
    assert boot_refreshers() == ["bluefin-sysext-fetch.service", "k0s-first-boot.service",
                                 "nvidia-container-toolkit-activate.service"]


@pytest.mark.parametrize("refresher", boot_refreshers())
def test_boot_refreshers_wait_for_the_module_loads(refresher: str) -> None:
    after = " ".join(SystemdFile(OS_UNITS / refresher).values("Unit", "After")).split()
    for unit in LOAD_UNITS:
        assert unit in after, f"{refresher} must be After={unit}"
