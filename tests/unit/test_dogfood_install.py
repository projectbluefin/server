"""The install/update/rollback QEMU check asserts a contract held elsewhere.

``scripts/dogfood-install.sh`` boots an image set in QEMU, installs it, updates
it and then greps ``PROBE <key>=<value>`` lines out of the serial log. Like
``dogfood-nvidia.sh`` before it, every one of those expectations is a literal
copy of something that lives somewhere else in the tree: the sysupdate feature
names, the unit names its probes query, the message the boot deadline logs.
Nothing re-derives them, so renaming a feature or a unit leaves a grep matching
a stale string -- or silently never matching, which only shows up on a host
with QEMU, Secure Boot keys and an hour to spend. No workflow runs the script,
so CI never notices either.

These tests tie each expectation back to the file it was copied from, and drive
the argument handling that runs before QEMU is ever started, without booting
anything.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dogfood-install.sh"
DISKLESS = ROOT / "scripts" / "dogfood-diskless.sh"
DEADLINE = ROOT / "files" / "os" / "update-check" / "usr" / "libexec" / "bluefin-boot-deadline"
SYSUPDATE_D = ROOT / "files" / "os" / "sysupdate.d"
TOOLKIT_SYSUPDATE_D = ROOT / "files" / "os" / "sysupdate.nvidia-container-toolkit.d"
UNIT_DIRS = ROOT / "files"
ZFS_SYSEXT = ROOT / "elements" / "oci" / "zfs-sysext.bst"

TEXT = SCRIPT.read_text(encoding="utf-8")
# "PROBE after-rollback kured-flag=none" reports a key behind a prefix word.
PROBE_KEY = re.compile(r"PROBE(?:-LOG)? (?:[a-z][a-z0-9-]* )?(?P<key>[a-z][a-z0-9-]*)=")
# "PROBE nvidia-driver=... image=... file=..." reports several keys per echo.
EMITTED_KEY = re.compile(r"(?:PROBE |PROBE-LOG | )(?P<key>[a-z][a-z0-9-]*)=")
# Units this repository ships, as opposed to the ones systemd itself provides.
OWN_UNIT = re.compile(r"\b((?:bluefin|nvidia|zfs|run-bluefin)[a-z0-9.-]*\.(?:service|timer|target|mount))\b")


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
    # dogfood-diskless.sh runs the probe and adds its own lines to the log.
    emitting = probe_lines(TEXT)[0] + probe_lines(DISKLESS.read_text(encoding="utf-8"))[0]
    return {match["key"] for line in emitting for match in EMITTED_KEY.finditer(line)}


def shipped_units() -> set[str]:
    units = {path.name for path in UNIT_DIRS.rglob("*") if path.suffix in {".service", ".timer", ".target", ".mount"}}
    # The ZFS sysext brings its own units with it: the element installs them
    # and wires zfs.target up, so they never appear under files/.
    return units | set(OWN_UNIT.findall(ZFS_SYSEXT.read_text(encoding="utf-8")))


def run(tmp_path: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
    image = tmp_path / "img"
    image.mkdir(exist_ok=True)
    return subprocess.run(
        ["bash", str(SCRIPT), *(args or (str(image),))],
        env={**os.environ, "DOGFOOD_STATE": str(tmp_path / "state"), **env},
        capture_output=True,
        text=True,
    )


def test_the_check_stops_at_the_first_failed_step() -> None:
    # Every expectation is a bare grep whose failure must end the run; without
    # this the script would print PASS after an update that never happened.
    assert "set -euo pipefail" in TEXT


def test_every_asserted_probe_key_is_one_the_probe_emits() -> None:
    # A grep for a key nothing prints can only ever fail, and that failure is
    # indistinguishable from the regression the check exists to catch.
    missing = asserted_keys() - emitted_keys()
    assert not missing, f"asserted but never printed: {sorted(missing)}"


def test_every_unit_the_probes_query_is_one_the_tree_ships() -> None:
    # The probes ask systemd about units by name. A renamed unit makes
    # is-active/show answer about a unit that does not exist, which reads as a
    # plain failure rather than as a stale probe.
    shipped = shipped_units()
    queried = set(OWN_UNIT.findall(TEXT))
    # bluefin-boot-deadline.timer's drop-in is written by the broken-boot probe
    # itself, and dogfood-broken.service is created by the same probe.
    missing = {unit for unit in queried if unit not in shipped}
    assert not missing, f"queried but not shipped: {sorted(missing)}"


def test_the_sysext_choices_map_to_features_sysupdate_actually_defines() -> None:
    # DOGFOOD_SYSEXT names are translated to sysupdate feature names, which the
    # update probe enables by writing /etc/sysupdate.d/<feature>.feature.d/.
    # A feature with no .feature file is silently never enabled, so the update
    # would quietly ship without the sysext the run is meant to prove.
    features = set(re.findall(r'features="\$\{features\} ([a-z0-9.-]+)"', TEXT))
    assert features == {"zfs", "nvidia-open-595"}
    for feature in features:
        assert (SYSUPDATE_D / f"{feature}.feature").is_file(), f"no {feature}.feature in files/os/sysupdate.d"


def test_the_transfer_directories_it_rewrites_are_the_ones_the_image_ships() -> None:
    # The probe redirects every transfer's Path= at the local HTTP server by
    # copying /usr/lib/sysupdate*.d/*.transfer into /etc. A directory that the
    # image does not ship copies nothing, and the update then silently fetches
    # from the real https:// origin instead of the version under test.
    assert any(SYSUPDATE_D.glob("*.transfer"))
    assert any(TOOLKIT_SYSUPDATE_D.glob("*.transfer"))
    assert "/usr/lib/sysupdate.d/*.transfer" in TEXT
    assert "/usr/lib/sysupdate.nvidia-container-toolkit.d/*.transfer" in TEXT


def test_the_counted_deadline_message_is_the_one_the_deadline_logs() -> None:
    # The unit-mode rollback asserts an exact count of deadline log lines. The
    # text is a copy of bluefin-boot-deadline's own message; if that is
    # reworded the count becomes 0 and the rollback reads as broken.
    deadline = DEADLINE.read_text(encoding="utf-8")
    assert "did not reach boot-complete.target" in deadline
    assert "rebooting so systemd-boot falls back" in deadline
    assert "did not reach boot-complete.target .*rebooting so systemd-boot falls back" in TEXT
    # The journal is filtered on this substring before the lines are counted.
    assert "grep 'boot deadline'" in TEXT
    assert "boot deadline" in deadline


def test_an_unknown_sysext_is_refused_before_anything_boots(tmp_path: Path) -> None:
    result = run(tmp_path, DOGFOOD_SYSEXT="bogus")
    assert result.returncode != 0
    assert "DOGFOOD_SYSEXT must list zfs and/or nvidia" in result.stderr
    assert not (tmp_path / "state" / "install.probe").exists()


def test_a_sysext_list_with_one_bad_entry_is_refused(tmp_path: Path) -> None:
    # The list is comma-separated; a typo next to a good name must not be
    # silently dropped, which would run the check without that sysext.
    result = run(tmp_path, DOGFOOD_SYSEXT="zfs,nvidai")
    assert result.returncode != 0
    assert "DOGFOOD_SYSEXT must list zfs and/or nvidia" in result.stderr


def test_the_image_directory_is_required(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={**os.environ, "DOGFOOD_STATE": str(tmp_path / "state")},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "usage:" in result.stderr
