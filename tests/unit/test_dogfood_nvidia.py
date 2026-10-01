"""The NVIDIA QEMU check asserts the contract the sysext actually ships.

``scripts/dogfood-nvidia.sh`` boots a disk install in QEMU, merges a driver
sysext and then greps a handful of ``PROBE <key>=<value>`` lines out of the
serial log. Every one of those expectations is a literal copy of something
that lives somewhere else in the tree: the extension-release template, the
module list, the unit names, the nouveau blacklist. Nothing re-derives them,
so renaming a unit or adding a module leaves the grep matching a stale string
-- or silently never matching, which only shows up when somebody has a GPU-less
host and two hours to spend. The script is also not run by any workflow, so CI
never notices either.

These tests tie each expectation back to the file it was copied from, without
booting anything.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dogfood-nvidia.sh"
DISKLESS = ROOT / "scripts" / "dogfood-diskless.sh"
JUSTFILE = ROOT / "Justfile"
SYSEXT_SRC = ROOT / "files" / "nvidia" / "sysext"
RELEASE_TEMPLATE = SYSEXT_SRC / "extension-release.nvidia"
MODPROBE_CONF = SYSEXT_SRC / "modprobe-nvidia.conf"
DRIVER_RECIPE = ROOT / "include" / "nvidia-driver.yml"
FLAVOURS_FILE = ROOT / "include" / "nvidia.yml"
IMAGE_FILE = ROOT / "include" / "image.yml"

TEXT = SCRIPT.read_text(encoding="utf-8")
PROBE_KEY = re.compile(r"PROBE (?P<key>[a-z][a-z0-9-]*)=")
# "PROBE guard=... ldconfig-unit=..." reports two keys from one echo.
EMITTED_KEY = re.compile(r"(?:PROBE | )(?P<key>[a-z][a-z0-9-]*)=")


def variables(path: Path) -> dict[str, str]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["variables"]


def flavours() -> list[str]:
    return sorted(
        name.removesuffix("-version")
        for name in variables(FLAVOURS_FILE)
        if name.endswith("-version")
    )


def probe_lines(text: str) -> tuple[list[str], list[str]]:
    """``(emitting, asserting)`` lines: an echo into the log, and a grep of it."""
    emitting, asserting = [], []
    for line in text.splitlines():
        if "PROBE " not in line:
            continue
        if "echo" in line:
            emitting.append(line)
        elif "grep" in line:
            asserting.append(line)
    return emitting, asserting


def asserted_keys() -> set[str]:
    _, asserting = probe_lines(TEXT)
    return {match["key"] for line in asserting for match in PROBE_KEY.finditer(line)}


def emitted_keys() -> set[str]:
    # dogfood-diskless.sh appends its own "PROBE failed=" to every probe it runs.
    emitting = probe_lines(TEXT)[0] + probe_lines(DISKLESS.read_text(encoding="utf-8"))[0]
    return {match["key"] for line in emitting for match in EMITTED_KEY.finditer(line)}


def queried_units() -> set[str]:
    return set(re.findall(r"\b(nvidia-[a-z-]+\.service)\b", TEXT))


def test_the_check_stops_at_the_first_failed_step() -> None:
    # Every step is a bare command whose failure must end the run; without
    # this the script would report PASS after a boot that never happened.
    assert "set -euo pipefail" in TEXT


def test_every_asserted_probe_key_is_one_the_probe_emits() -> None:
    # A grep for a key nothing prints can only ever fail, and a key that is
    # printed but never greped is an expectation somebody dropped.
    missing = asserted_keys() - emitted_keys()
    assert not missing, f"asserted but never printed: {sorted(missing)}"


def test_the_probe_runs_on_a_disk_boot_after_an_install() -> None:
    # The point of this check is a disk install, not another diskless boot:
    # a sysext in /var/lib/extensions only exists once /var is on disk.
    assert "dogfood-install.sh" in TEXT
    assert "DOGFOOD_BOOT=disk" in TEXT
    assert "/var/lib/extensions" in TEXT


def test_the_expected_extension_release_is_the_one_the_sysext_writes() -> None:
    # include/sysext.yml appends VERSION_ID= and then ARCHITECTURE= to the
    # staged template, so the merged file reads in exactly this order.
    template = RELEASE_TEMPLATE.read_text(encoding="utf-8").splitlines()
    assert template == ["NAME=@NVIDIA_FLAVOUR@", "ID=bluefin-server", "EXTENSION_RELOAD_MANAGER=1"]
    expected = [
        "NAME=${flavour}",
        "ID=bluefin-server",
        "EXTENSION_RELOAD_MANAGER=1",
        "VERSION_ID=${ver}",
        "ARCHITECTURE=x86-64",
    ]
    assert f'PROBE release={" ".join(expected)} ' in TEXT


def test_the_probe_checks_a_signature_for_every_module_the_driver_ships() -> None:
    # Unsigned or missing modules are the failure this check exists to catch,
    # so the module list and the expected "sha512 " count must track
    # include/nvidia-driver.yml rather than a hand-kept copy.
    modules = variables(DRIVER_RECIPE)["nvidia-modules"].split()
    assert f'for m in {" ".join(modules)}; do' in TEXT
    assert f'PROBE sig={"sha512 " * len(modules)}' in TEXT


def test_the_probe_only_queries_units_the_sysext_ships() -> None:
    shipped = {path.name for path in SYSEXT_SRC.glob("*.service")}
    unknown = queried_units() - shipped
    assert not unknown, f"not shipped by files/nvidia/sysext: {sorted(unknown)}"


@pytest.mark.parametrize(
    ("unit", "expected"),
    [("nvidia-flavour-guard.service", "guard"), ("nvidia-ldconfig.service", "ldconfig-unit")],
)
def test_the_units_expected_active_without_a_gpu_are_ungated(unit: str, expected: str) -> None:
    # These two run on any machine, so the probe may demand "active"; a
    # condition added later would make them skip and the assertion stale.
    parsed = SystemdFile(SYSEXT_SRC / unit)
    gates = [key for key in parsed.sections.get("Unit", {}) if key.startswith(("Condition", "Assert"))]
    assert not gates, f"{unit} is now gated by {gates}"
    assert not parsed.commands("ExecCondition")
    assert f"{expected}=active" in TEXT


def test_the_driver_load_is_skipped_by_an_exec_condition_not_a_unit_condition() -> None:
    # "load-unit=exec-condition inactive" is what systemd reports for an
    # ExecCondition= that exits non-zero; a [Unit] Condition would report
    # ConditionResult=no instead and never match.
    parsed = SystemdFile(SYSEXT_SRC / "nvidia-load.service")
    assert parsed.commands("ExecCondition")
    assert not [key for key in parsed.sections["Unit"] if key.startswith(("Condition", "Assert"))]
    assert "PROBE load-unit=exec-condition inactive" in TEXT


@pytest.mark.parametrize(
    ("unit", "key"),
    [("nvidia-device-nodes.service", "nodes-unit"), ("nvidia-persistenced.service", "persistenced")],
)
def test_the_gpu_only_units_are_skipped_by_a_unit_condition(unit: str, key: str) -> None:
    # ConditionResult=no is only reported for a [Unit] Condition*=, which is
    # what the probe greps for these two.
    parsed = SystemdFile(SYSEXT_SRC / unit)
    assert [name for name in parsed.sections["Unit"] if name.startswith("Condition")]
    assert f"{key}=no" in TEXT


def test_the_expected_nouveau_blacklist_count_matches_the_modprobe_drop_in() -> None:
    # "modprobe -c | grep -cx 'blacklist nouveau'" counts lines, so a second
    # blacklist line anywhere in the sysext would break the check.
    lines = MODPROBE_CONF.read_text(encoding="utf-8").splitlines()
    count = sum(1 for line in lines if line.strip() == "blacklist nouveau")
    assert f"PROBE nouveau-blacklisted={count}" in TEXT


def test_the_just_recipe_passes_a_built_flavour_and_the_image_version() -> None:
    # The script splits <flavour>_<version>.raw.zst on the last underscore and
    # checks both halves against the guest, so the recipe has to hand it a
    # flavour that exists and the image version the sysext was locked to.
    recipe = next(
        line for line in JUSTFILE.read_text(encoding="utf-8").splitlines() if "dogfood-nvidia.sh" in line
    )
    default = re.search(r'dogfood-nvidia FLAVOUR="([^"]+)"', JUSTFILE.read_text(encoding="utf-8"))
    assert default and default[1] in flavours()
    assert "{{FLAVOUR}}_$(sed -n 's/^  image-version:" in recipe
    assert ".raw.zst" in recipe
    assert (ROOT / "elements" / "oci" / f"{default[1]}-sysext.bst").is_file()
    assert variables(IMAGE_FILE)["image-version"]


def test_the_script_is_shellcheck_clean(shellcheck: str) -> None:
    subprocess.run([shellcheck, "-S", "style", str(SCRIPT)], check=True)
