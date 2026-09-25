"""Contracts for root credential persistence across DDI slot replacement.

``/etc/shadow`` ships inside the OS DDI, and ``50-root.transfer`` replaces that
filesystem image in both ``bluefin-server-root-*`` slots on every update. The
root credential a host rotates at the console therefore used to roll back to the
credential baked into the image as soon as the other slot booted — the finding
recorded in issue #244.

The fix keeps the authoritative root entry in the persistent ``/var`` partition:
``bluefin-root-cred.service`` restores it into ``/etc/shadow`` before every login
path, and ``bluefin-root-cred-persist.path`` copies changes back out.

These tests pin the parts that fail silently if they drift — the helper's
behaviour against real shadow files, the unit ordering that decides whether a
restore lands before ``getty``/``sshd``, and the enablement symlinks, because
systemd presets are not applied in this image and a unit without one never runs.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ELEMENT = REPO_ROOT / "elements" / "bluefin-server" / "os-root-cred.bst"
STACK = REPO_ROOT / "elements" / "bluefin-server" / "os-stack.bst"
UNITS_ELEMENT = REPO_ROOT / "elements" / "bluefin-server" / "os-k0s-first-boot.bst"
DDI_ELEMENT = REPO_ROOT / "elements" / "oci" / "bluefin-server-ddi.bst"
HELPER = REPO_ROOT / "files" / "os" / "libexec" / "bluefin-root-cred-sync"
SYSTEM_DIR = REPO_ROOT / "files" / "os" / "systemd" / "system"
RESTORE_UNIT = SYSTEM_DIR / "bluefin-root-cred.service"
PERSIST_PATH_UNIT = SYSTEM_DIR / "bluefin-root-cred-persist.path"
PERSIST_UNIT = SYSTEM_DIR / "bluefin-root-cred-persist.service"

SHADOW_PATH = "/etc/shadow"
STATE_PATH = "/var/lib/bluefin-server/root-shadow"

# The credential the image bakes in, and a credential an operator would rotate
# to. Both are written the way shadow(5) writes them, and the hash values are
# irrelevant to the mechanism under test.
IMAGE_ENTRY = (
    "root:$6$bluefin123$o2pQjPN1n3ZCnYUROlA01xAdnGO7mhVRAVw98x4xc8LAUIJv7b44bBNoER6"
    "fM4P.rrj4ePYFfkx9WvZICU8nt/:19700:0:99999:7:::"
)
ROTATED_ENTRY = "root:$6$rotatedhash$6W8pQ1uZ/:19932:0:99999:7:::"
SYSTEM_ENTRY = "systemd-network:!:19000:0:99999:7:::"


def shadow_db(entry: str) -> str:
    """A shadow database holding the root entry plus a system account."""
    return f"{entry}\n{SYSTEM_ENTRY}\n"


def render(tmp_path: Path, entry: str) -> Path:
    shadow = tmp_path / "shadow"
    shadow.write_text(shadow_db(entry), encoding="utf-8")
    shadow.chmod(0o600)
    return shadow


def run(mode: str, shadow: Path, state: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(HELPER), mode, str(shadow), str(state)],
        capture_output=True,
        text=True,
    )


def root_entry(shadow: Path) -> str:
    for line in shadow.read_text(encoding="utf-8").splitlines():
        if line.startswith("root:"):
            return line
    raise AssertionError(f"{shadow} holds no root entry")


# ── The helper is shippable ────────────────────────────────────────────────


def test_helper_ships_as_an_executable_bash_script():
    assert HELPER.is_file(), f"{HELPER.relative_to(REPO_ROOT)} is missing"
    mode = HELPER.stat().st_mode
    assert mode & 0o111, "systemd cannot exec a helper without the execute bit"
    assert HELPER.read_text(encoding="utf-8").startswith("#!/bin/bash\n"), (
        "the helper must run under bash: the DDI runtime is runtime-minimal and "
        "does not guarantee /bin/sh"
    )


def test_helper_needs_no_tool_the_ddi_runtime_may_lack():
    """runtime-minimal ships no sed/awk/grep; the helper runs before login."""
    code = "\n".join(
        line
        for line in HELPER.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    )
    for tool in ("awk", "sed", "grep", "python"):
        assert not re.search(rf"(^|[|;&(`]\s*){tool}\b", code, re.MULTILINE), (
            f"the helper invokes {tool}, which the DDI runtime does not guarantee"
        )


# ── Packaging and enablement ───────────────────────────────────────────────


def test_persistence_element_is_part_of_the_ddi_stack():
    assert "bluefin-server/os-root-cred.bst" in STACK.read_text(encoding="utf-8")


def test_units_come_from_the_element_that_stages_the_systemd_tree():
    """The symlinks below only resolve while that element stages this tree."""
    units_element = UNITS_ELEMENT.read_text(encoding="utf-8")
    assert "path: files/os/systemd/system" in units_element
    assert "target: /usr/lib/systemd/system" in units_element
    for unit in (RESTORE_UNIT, PERSIST_PATH_UNIT, PERSIST_UNIT):
        assert unit.is_file(), f"{unit.name} is staged by no element"


def test_every_shipped_unit_is_enabled_by_an_explicit_symlink():
    """Presets are not applied in this image, so enablement must be explicit."""
    install_commands = "\n".join(
        yaml.safe_load(ELEMENT.read_text(encoding="utf-8"))["config"][
            "install-commands"
        ]
    )
    enabled = set(re.findall(r"ln -sf \.\./(\S+) ", install_commands))
    assert enabled == {
        RESTORE_UNIT.name,
        PERSIST_PATH_UNIT.name,
    }, f"unexpected enablement set: {sorted(enabled)}"
    for name in enabled:
        assert (SYSTEM_DIR / name).is_file(), (
            f"{name} is enabled but no such unit ships"
        )


def test_the_triggered_persist_half_is_not_enabled_at_boot():
    install_commands = yaml.safe_load(ELEMENT.read_text(encoding="utf-8"))["config"][
        "install-commands"
    ]
    element_text = "\n".join(install_commands)
    assert PERSIST_UNIT.name not in element_text, (
        "the persist service must stay untriggered at boot: running both halves "
        "concurrently could overwrite the operator's credential with the image's"
    )
    assert (
        "install -Dm755 libexec-src/bluefin-root-cred-sync "
        '"%{install-root}%{prefix}/libexec/bluefin-root-cred-sync"'
    ) in element_text


def test_helper_lands_on_the_path_the_units_exec():
    for unit in (RESTORE_UNIT, PERSIST_UNIT):
        assert (
            f"ExecStart=/usr/libexec/bluefin-root-cred-sync "
            f"{'boot' if unit is RESTORE_UNIT else 'persist'}"
        ) in unit.read_text(encoding="utf-8")


def test_boot_restore_runs_before_every_login_path():
    restore = RESTORE_UNIT.read_text(encoding="utf-8")
    assert "Type=oneshot" in restore
    assert "After=local-fs.target" in restore
    # getty, sshd, and the k0s console all start from multi-user.target.
    assert "Before=multi-user.target" in restore
    assert "ConditionPathExists=/etc/shadow" in restore


def test_both_halves_write_to_a_root_only_store_on_persistent_var():
    for unit in (RESTORE_UNIT, PERSIST_UNIT):
        text = unit.read_text(encoding="utf-8")
        assert "RequiresMountsFor=/var/lib/bluefin-server" in text, (
            f"{unit.name} could run against an unmounted /var and silently "
            "write the store to the replaceable root filesystem"
        )
        assert "StateDirectory=bluefin-server" in text
        assert "StateDirectoryMode=0700" in text


def test_persist_watcher_tracks_the_shadow_file_only():
    watcher = PERSIST_PATH_UNIT.read_text(encoding="utf-8")
    assert f"Unit={PERSIST_UNIT.name}" in watcher
    # The watcher must not be armed while the boot-time restore writes.
    assert f"After={RESTORE_UNIT.name}" in watcher
    watched = [
        line for line in watcher.splitlines() if line.startswith("PathChanged=")
    ]
    assert watched == [f"PathChanged={SHADOW_PATH}"], (
        "watch /etc/shadow alone: a directory watch would capture the file "
        "mid-write, and any other /etc path is not this unit's business"
    )


def test_image_still_bakes_the_bootstrap_credential():
    """This layer restores a rotated credential; removing the baked one is #80."""
    ddi = DDI_ELEMENT.read_text(encoding="utf-8")
    assert "> /layer/etc/shadow" in ddi, (
        "the DDI no longer seeds /etc/shadow — revisit whether the persistence "
        "layer still has a bootstrap credential to seed from (issue #80)"
    )


# ── Helper behaviour ───────────────────────────────────────────────────────


def test_first_boot_seeds_the_persisted_copy_from_the_image(tmp_path):
    shadow = render(tmp_path, IMAGE_ENTRY)
    state = tmp_path / "state" / "root-shadow"

    result = run("boot", shadow, state)

    assert result.returncode == 0, result.stderr
    assert state.read_text(encoding="utf-8") == f"{IMAGE_ENTRY}\n"
    assert state.stat().st_mode & 0o777 == 0o600
    assert shadow.read_text(encoding="utf-8") == shadow_db(IMAGE_ENTRY), (
        "seeding must not rewrite the image's own shadow database"
    )


def test_a_rotated_credential_survives_a_replaced_image_slot(tmp_path):
    """The regression from issue #244: the seeded hash must not come back."""
    shadow = render(tmp_path, IMAGE_ENTRY)
    state = tmp_path / "state" / "root-shadow"

    assert run("boot", shadow, state).returncode == 0
    # The operator rotates the root password at the console...
    shadow.write_text(shadow_db(ROTATED_ENTRY), encoding="utf-8")
    assert run("persist", shadow, state).returncode == 0
    # ...then systemd-sysupdate boots the other slot, whose /etc/shadow is the
    # one baked into the new DDI.
    shadow.write_text(shadow_db(IMAGE_ENTRY), encoding="utf-8")
    assert run("boot", shadow, state).returncode == 0

    assert root_entry(shadow) == ROTATED_ENTRY
    assert IMAGE_ENTRY.split(":")[1] not in shadow.read_text(encoding="utf-8")


def test_restore_replaces_only_the_root_entry(tmp_path):
    shadow = render(tmp_path, IMAGE_ENTRY)
    state = tmp_path / "state" / "root-shadow"
    state.parent.mkdir(parents=True)
    state.write_text(f"{ROTATED_ENTRY}\n", encoding="utf-8")

    assert run("boot", shadow, state).returncode == 0

    assert shadow.read_text(encoding="utf-8") == shadow_db(ROTATED_ENTRY)
    assert shadow.stat().st_mode & 0o777 == 0o600


def test_restore_is_idempotent(tmp_path):
    shadow = render(tmp_path, IMAGE_ENTRY)
    state = tmp_path / "state" / "root-shadow"
    state.parent.mkdir(parents=True)
    state.write_text(f"{ROTATED_ENTRY}\n", encoding="utf-8")

    assert run("boot", shadow, state).returncode == 0
    before = shadow.stat().st_mtime_ns
    result = run("boot", shadow, state)

    assert result.returncode == 0
    assert root_entry(shadow) == ROTATED_ENTRY
    assert shadow.stat().st_mtime_ns == before, (
        "a matching credential must not be rewritten on every boot"
    )


def test_persisted_copy_is_root_only(tmp_path):
    shadow = render(tmp_path, IMAGE_ENTRY)
    state = tmp_path / "state" / "root-shadow"

    assert run("persist", shadow, state).returncode == 0

    assert state.stat().st_mode & 0o777 == 0o600
    # The helper creates the store directory under umask 077, and the units
    # declare StateDirectoryMode=0700 for the systemd-created directory.
    assert state.parent.stat().st_mode & 0o077 == 0


def test_corrupt_persisted_copy_fails_loudly_and_leaves_shadow_alone(tmp_path):
    """No silent fallback to the baked-in credential when the store is broken."""
    shadow = render(tmp_path, IMAGE_ENTRY)
    before = shadow.read_text(encoding="utf-8")
    state = tmp_path / "state" / "root-shadow"
    state.parent.mkdir(parents=True)
    state.write_text("", encoding="utf-8")

    result = run("boot", shadow, state)

    assert result.returncode != 0
    assert shadow.read_text(encoding="utf-8") == before


def test_malformed_and_rootless_shadow_entries_are_refused(tmp_path):
    state = tmp_path / "state" / "root-shadow"

    truncated = render(tmp_path, "root:$6$broken")
    result = run("persist", truncated, state)
    assert result.returncode != 0
    assert not state.exists(), "a truncated entry must never be persisted"

    rootless = tmp_path / "rootless"
    rootless.write_text(f"{SYSTEM_ENTRY}\n", encoding="utf-8")
    result = run("persist", rootless, state)
    assert result.returncode != 0
    assert not state.exists()


def test_an_unusable_invocation_is_rejected(tmp_path):
    shadow = render(tmp_path, IMAGE_ENTRY)
    state = tmp_path / "state" / "root-shadow"

    assert run("restore", shadow, state).returncode != 0
    assert run("", shadow, state).returncode != 0
    assert not state.exists()