"""Invariant tests for manual and script element sandbox runtimes.

In FSDK 26.08, runtime-minimal.bst no longer ships /bin/sh. Elements of
kind: manual or kind: script execute commands within their build-time
sandbox and must depend on base/base-stack.bst in build-depends to guarantee
a working shell environment.
"""

from __future__ import annotations

from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ELEMENTS_DIR = REPO_ROOT / "elements"


def test_manual_and_script_elements_depend_on_base_stack():
    """Ensure all manual/script elements have base/base-stack.bst in build-depends."""
    for bst_path in ELEMENTS_DIR.rglob("*.bst"):
        # Skip external junction declarations
        if bst_path.name in ("freedesktop-sdk.bst", "gnome-build-meta.bst"):
            continue

        content = bst_path.read_text(encoding="utf-8")
        # Quick check for kind
        if "kind: manual" not in content and "kind: script" not in content:
            continue

        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            continue

        kind = data.get("kind")
        if kind in ("manual", "script"):
            build_depends = data.get("build-depends", [])
            dep_names = []
            for dep in build_depends:
                if isinstance(dep, str):
                    dep_names.append(dep)
                elif isinstance(dep, dict) and "filename" in dep:
                    dep_names.append(dep["filename"])

            assert "base/base-stack.bst" in dep_names, (
                f"{bst_path.relative_to(REPO_ROOT)} is kind: {kind} but does not include "
                f"base/base-stack.bst in build-depends"
            )


def test_compose_elements_set_integrate_false():
    """Ensure compose elements set integrate: False to avoid invoking nonexistent /bin/sh.

    In FSDK 26.08, shell-less or minimal target images fail if BuildStream attempts
    to execute integration scripts in the composed sandbox.
    """
    for bst_path in ELEMENTS_DIR.rglob("*.bst"):
        if bst_path.name in ("freedesktop-sdk.bst", "gnome-build-meta.bst"):
            continue

        content = bst_path.read_text(encoding="utf-8")
        if "kind: compose" not in content:
            continue

        data = yaml.safe_load(content)
        if not isinstance(data, dict) or data.get("kind") != "compose":
            continue

        config = data.get("config", {})
        assert config.get("integrate") is False, (
            f"{bst_path.relative_to(REPO_ROOT)} is kind: compose but does not set "
            f"'integrate: False' in config"
        )


def test_os_stack_uses_flatcar_base():
    """Bluefin Server OS payload now lands on the Flatcar `/usr` base.

    projectbluefin/server#131 cut os-stack.bst over to flatcar/flatcar-usr.bst
    and deleted the displaced FSDK base-runtime components. The OS payload must
    depend on flatcar-usr.bst and must NOT pull the FSDK base userspace it
    replaced (the uutils-coreutils overlay, GNU runtime-minimal, etc.). The
    installer keeps its own FSDK userspace (see test_installer_stack_...).
    """
    os_stack = ELEMENTS_DIR / "bluefin-server" / "os-stack.bst"
    data = yaml.safe_load(os_stack.read_text(encoding="utf-8"))
    depends = data.get("depends", [])

    assert "flatcar/flatcar-usr.bst" in depends, (
        "os-stack.bst must depend on flatcar/flatcar-usr.bst (projectbluefin/server#131)"
    )
    assert "bluefin-server/uutils-coreutils.bst" not in depends, (
        "os-stack.bst must no longer ship the uutils-coreutils overlay; "
        "Flatcar `/usr` provides coreutils (projectbluefin/server#131)"
    )
    assert "freedesktop-sdk.bst:public-stacks/runtime-gnu.bst" not in depends, (
        "os-stack.bst must NOT depend on GNU userspace (runtime-gnu.bst)"
    )
    for displaced in (
        "freedesktop-sdk.bst:public-stacks/runtime-minimal.bst",
        "freedesktop-sdk.bst:components/systemd.bst",
        "freedesktop-sdk.bst:components/dbus.bst",
        "freedesktop-sdk.bst:components/dbus-broker.bst",
        "freedesktop-sdk.bst:components/kmod.bst",
        "freedesktop-sdk.bst:components/shadow.bst",
        "freedesktop-sdk.bst:bootstrap/bash.bst",
        "freedesktop-sdk.bst:components/openssh-systemd.bst",
        "freedesktop-sdk.bst:components/podman.bst",
        "freedesktop-sdk.bst:components/xfsprogs.bst",
        "freedesktop-sdk.bst:components/gnupg.bst",
        "freedesktop-sdk.bst:components/ca-certificates.bst",
        "freedesktop-sdk.bst:components/tzdata.bst",
        "bluefin-server/linux-firmware-split.bst",
    ):
        assert displaced not in depends, (
            f"os-stack.bst must no longer depend on {displaced} "
            "(projectbluefin/server#131)"
        )


def test_os_stack_userspace_comes_from_flatcar():
    """dbus, dbus-broker, and bash now come from Flatcar `/usr`, not FSDK components.

    projectbluefin/server#131 removed the FSDK dbus, dbus-broker, and
    bootstrap/bash entries from os-stack.bst; flatcar/flatcar-usr.bst provides
    them as part of the single-ABI Flatcar userspace. This test pins that the
    old FSDK base-runtime entries are gone so a stray re-add is caught.
    """
    os_stack = ELEMENTS_DIR / "bluefin-server" / "os-stack.bst"
    data = yaml.safe_load(os_stack.read_text(encoding="utf-8"))
    depends = data.get("depends", [])

    for removed in (
        "freedesktop-sdk.bst:components/dbus.bst",
        "freedesktop-sdk.bst:components/dbus-broker.bst",
        "freedesktop-sdk.bst:bootstrap/bash.bst",
    ):
        assert removed not in depends, (
            f"os-stack.bst must no longer depend on {removed}; "
            "Flatcar `/usr` provides it (projectbluefin/server#131)"
        )


def test_installer_stack_includes_uutils_and_dbus():
    """Installer stack must include uutils-coreutils, dbus, and dbus-broker."""
    installer_stack = ELEMENTS_DIR / "installer" / "installer-stack.bst"
    data = yaml.safe_load(installer_stack.read_text(encoding="utf-8"))
    depends = data.get("depends", [])

    assert "bluefin-server/uutils-coreutils.bst" in depends, (
        "installer-stack.bst must include bluefin-server/uutils-coreutils.bst"
    )
    assert "freedesktop-sdk.bst:components/dbus.bst" in depends, (
        "installer-stack.bst must include freedesktop-sdk.bst:components/dbus.bst for dbus.socket"
    )
    assert "freedesktop-sdk.bst:components/dbus-broker.bst" in depends, (
        "installer-stack.bst must include freedesktop-sdk.bst:components/dbus-broker.bst"
    )


def test_installer_linker_paths_split_host_and_target():
    """Target-root ld.so.conf write and read must resolve to the same file.

    projectbluefin/server#132 (hanthor review): `ldconfig -r /target-root` chroots
    into /target-root, so the `-f /tmp/ld.so.conf` path is resolved *post-chroot* to
    /target-root/tmp/ld.so.conf. The conf is therefore written to /target-root/tmp/
    and read back via `-f /tmp/ld.so.conf`; the two must agree, not live on different
    roots. The target cache indexes Flatcar's /usr/lib64 (the FSDK libs ship there,
    not the Debian multiarch path).
    """
    installer = ELEMENTS_DIR / "oci" / "bluefin-server-installer.bst"
    text = installer.read_text(encoding="utf-8")

    # Target linker search path (what the target-root cache indexes).
    assert "/usr/lib64\\n/usr/lib64/systemd\\n" in text, (
        "installer must index Flatcar /usr/lib64 for the target-root cache "
        "(projectbluefin/server#132)"
    )
    # Conf written to /target-root/tmp and read via `-f /tmp/ld.so.conf` under
    # `-r /target-root` (which resolves to /target-root/tmp/ld.so.conf post-chroot).
    assert "> /target-root/tmp/ld.so.conf" in text, (
        "installer must write the target ld.so.conf to /target-root/tmp, matching "
        "the `ldconfig -r /target-root -f /tmp/ld.so.conf` read "
        "(projectbluefin/server#132)"
    )
    assert "ldconfig -r /target-root -f /tmp/ld.so.conf" in text, (
        "installer must read the target conf from /tmp with `-r /target-root "
        "(projectbluefin/server#132)"
    )
    # Cleanup removes the same post-chroot path it wrote.
    assert "rm -f /target-root/tmp/ld.so.conf" in text, (
        "installer must clean up /target-root/tmp/ld.so.conf "
        "(projectbluefin/server#132)"
    )




