"""Executed coverage for bluefin-sysext-modules (bluefin-host).

The helper runs against a fake /usr/lib/modules/<kver> tree. depmod and
modprobe are logging stubs on PATH: the depmod stub writes a modules.dep
listing every module it can reach through the linked tree (following
symlinks, like kmod's depmod), so the tests see what the real one would index
without real ELF modules.
"""


import os
import re
import subprocess
from pathlib import Path

import pytest

KVER = "7.2.2"


class Kmods:
    def __init__(self, tmp: Path, host_bin: Path) -> None:
        self.helper = host_bin / "bluefin-sysext-modules"
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.log = tmp / "calls.log"
        self.log.touch()
        self.usr = tmp / "usr"
        self.basedir = tmp / "run" / "bluefin" / "kmods"
        self.src = self.usr / "lib" / "modules" / KVER
        (self.src / "kernel" / "drivers" / "gpu" / "drm").mkdir(parents=True)
        (self.usr / "lib" / "extension-release.d").mkdir(parents=True)
        # The base image: its modules, depmod inputs and its own index.
        (self.src / "kernel" / "drivers" / "gpu" / "drm" / "drm.ko.zst").touch()
        (self.src / "modules.order").write_text("kernel/drivers/gpu/drm/drm.ko.zst\n", encoding="utf-8")
        (self.src / "modules.builtin").touch()
        (self.src / "modules.builtin.modinfo").touch()
        (self.src / "modules.dep").write_text("kernel/drivers/gpu/drm/drm.ko.zst:\n", encoding="utf-8")
        (self.src / "modules.alias").touch()
        self.depmod(
            f'echo "depmod $*" >> "{self.log}"\n'
            '[ "$1" = -b ] || exit 64\n'
            'dir="$2/lib/modules/$3"\n'
            "(cd \"${dir}\" && find -L . -name '*.ko*' | sed 's|^\\./||; s|$|:|' | sort) > \"${dir}/modules.dep\"\n"
        )
        self.stub("modprobe", f'echo "modprobe $*" >> "{self.log}"\nexit ${{MODPROBE_RC:-0}}\n')

    def stub(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def depmod(self, body: str) -> None:
        self.stub("depmod", body)

    def add_sysext(self, name: str, *modules: str) -> None:
        (self.src / "extra" / name).mkdir(parents=True, exist_ok=True)
        for m in modules:
            (self.src / "extra" / name / f"{m}.ko.zst").touch()
        (self.usr / "lib" / "extension-release.d" / f"extension-release.{name}").write_text("ID=bluefin-server\n", encoding="utf-8")

    def __call__(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        full = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            BLUEFIN_KMOD_USR=str(self.usr),
            BLUEFIN_KMOD_BASEDIR=str(self.basedir),
            BLUEFIN_KVER=KVER,
            **env,
        )
        return subprocess.run([str(self.helper), *args], capture_output=True, text=True, env=full, timeout=30)

    def calls(self, tool: str) -> list[str]:
        return [line for line in self.log.read_text(encoding="utf-8").splitlines() if line.startswith(tool + " ")]

    @property
    def tree(self) -> Path:
        return self.basedir / "usr" / "lib" / "modules" / KVER


@pytest.fixture()
def kmods(tmp_path: Path, host_bin: Path) -> Kmods:
    return Kmods(tmp_path, host_bin)


def test_without_arguments_it_prints_usage_and_exits_2(kmods: Kmods) -> None:
    result = kmods()
    assert result.returncode == 2
    assert result.stderr == "usage: bluefin-sysext-modules MODULE... | --basedir\n"
    assert kmods.calls("depmod") == []


@pytest.mark.parametrize("args", [("-r", "zfs"), ("--basedir", "zfs")])
def test_an_option_other_than_a_lone_basedir_is_refused_before_any_work(kmods: Kmods, args: tuple[str, ...]) -> None:
    assert kmods(*args).returncode == 2
    assert kmods.calls("depmod") == []


def test_a_kernel_without_a_module_tree_fails(kmods: Kmods) -> None:
    subprocess.run(["rm", "-rf", str(kmods.src)], check=True)
    result = kmods("zfs")
    assert result.returncode == 1
    assert result.stderr == f"bluefin-sysext-modules: no modules for kernel {KVER} in {kmods.src}\n"


def test_indexes_the_base_and_every_sysexts_modules_then_modprobes_from_the_run_tree(kmods: Kmods) -> None:
    kmods.add_sysext("zfs", "spl", "zfs")
    kmods.add_sysext("nvidia", "nvidia", "nvidia-uvm")
    result = kmods("zfs")
    assert result.returncode == 0, result.stderr

    (depmod,) = kmods.calls("depmod")
    assert re.fullmatch(rf"depmod -b {re.escape(str(kmods.basedir))}\.[A-Za-z0-9]+ {KVER}", depmod)
    assert kmods.calls("modprobe") == [f"modprobe -d {kmods.basedir} -S {KVER} -a -- zfs"]
    assert os.readlink(kmods.basedir / "lib") == "usr/lib"
    for entry in ("kernel", "extra", "modules.order", "modules.builtin", "modules.builtin.modinfo"):
        assert os.readlink(kmods.tree / entry) == str(kmods.src / entry)
    # The base image's own index is never reused: depmod writes a new one.
    assert not (kmods.tree / "modules.dep").is_symlink() and not (kmods.tree / "modules.alias").exists()
    assert (kmods.tree / "modules.dep").read_text(encoding="utf-8").splitlines() == [
        "extra/nvidia/nvidia-uvm.ko.zst:",
        "extra/nvidia/nvidia.ko.zst:",
        "extra/zfs/spl.ko.zst:",
        "extra/zfs/zfs.ko.zst:",
        "kernel/drivers/gpu/drm/drm.ko.zst:",
    ]
    assert f"bluefin-sysext-modules: indexed 5 modules for {KVER} in {kmods.basedir}\n" in result.stderr


def test_loads_several_modules_in_one_modprobe_a_call(kmods: Kmods) -> None:
    kmods.add_sysext("nvidia", "nvidia", "nvidia-uvm", "nvidia-modeset", "nvidia-drm")
    assert kmods("nvidia", "nvidia-uvm", "nvidia-modeset", "nvidia-drm").returncode == 0
    assert kmods.calls("modprobe") == [f"modprobe -d {kmods.basedir} -S {KVER} -a -- nvidia nvidia-uvm nvidia-modeset nvidia-drm"]


def test_an_unchanged_module_set_reuses_the_index(kmods: Kmods) -> None:
    kmods.add_sysext("zfs", "spl", "zfs")
    kmods("zfs")
    assert kmods("zfs").returncode == 0
    assert len(kmods.calls("depmod")) == 1
    assert len(kmods.calls("modprobe")) == 2


def test_a_newly_merged_sysext_rebuilds_the_index(kmods: Kmods) -> None:
    kmods.add_sysext("zfs", "spl", "zfs")
    kmods("zfs")
    kmods.add_sysext("nvidia", "nvidia")
    assert kmods("nvidia").returncode == 0
    assert len(kmods.calls("depmod")) == 2
    assert "extra/nvidia/nvidia.ko.zst:" in (kmods.tree / "modules.dep").read_text(encoding="utf-8").splitlines()


def test_an_unmerged_sysext_drops_out_of_the_index(kmods: Kmods) -> None:
    kmods.add_sysext("zfs", "spl", "zfs")
    kmods.add_sysext("nvidia", "nvidia")
    kmods("zfs")
    subprocess.run(["rm", "-rf", str(kmods.src / "extra" / "nvidia"), str(kmods.usr / "lib" / "extension-release.d" / "extension-release.nvidia")], check=True)
    kmods("zfs")
    assert len(kmods.calls("depmod")) == 2
    assert "nvidia" not in (kmods.tree / "modules.dep").read_text(encoding="utf-8")


def test_basedir_prints_the_base_directory_and_loads_nothing(kmods: Kmods) -> None:
    kmods.add_sysext("zfs", "zfs")
    result = kmods("--basedir")
    assert result.returncode == 0
    assert result.stdout == f"{kmods.basedir}\n"
    assert len(kmods.calls("depmod")) == 1
    assert kmods.calls("modprobe") == []


def test_modprobes_failure_is_the_helpers_exit_status(kmods: Kmods) -> None:
    kmods.add_sysext("nvidia", "nvidia")
    assert kmods("nvidia", MODPROBE_RC="1").returncode == 1


def test_a_failed_depmod_leaves_no_index_behind(kmods: Kmods) -> None:
    kmods.add_sysext("zfs", "zfs")
    kmods.depmod("exit 1\n")
    assert kmods("zfs").returncode != 0
    assert not (kmods.basedir / "stamp").exists()
    leftovers = [p.name for p in kmods.basedir.parent.iterdir() if p.name.startswith("kmods.") and p.name != "kmods.lock"]
    assert leftovers == []
    assert kmods.calls("modprobe") == []
