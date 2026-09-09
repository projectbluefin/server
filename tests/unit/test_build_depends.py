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


def test_os_stack_uses_uutils_not_gnu():
    """Bluefin Server OS must use uutils-coreutils, not GNU userspace."""
    os_stack = ELEMENTS_DIR / "bluefin-server" / "os-stack.bst"
    data = yaml.safe_load(os_stack.read_text(encoding="utf-8"))
    depends = data.get("depends", [])

    assert "bluefin-server/uutils-coreutils.bst" in depends, (
        "os-stack.bst must include bluefin-server/uutils-coreutils.bst"
    )
    assert "freedesktop-sdk.bst:public-stacks/runtime-gnu.bst" not in depends, (
        "os-stack.bst must NOT depend on GNU userspace (runtime-gnu.bst)"
    )


def test_os_stack_includes_dbus_broker():
    """Bluefin Server OS must include dbus and dbus-broker for system services."""
    os_stack = ELEMENTS_DIR / "bluefin-server" / "os-stack.bst"
    data = yaml.safe_load(os_stack.read_text(encoding="utf-8"))
    depends = data.get("depends", [])

    assert "freedesktop-sdk.bst:components/dbus.bst" in depends, (
        "os-stack.bst must include freedesktop-sdk.bst:components/dbus.bst for dbus.socket"
    )
    assert "freedesktop-sdk.bst:components/dbus-broker.bst" in depends, (
        "os-stack.bst must include freedesktop-sdk.bst:components/dbus-broker.bst"
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


def test_os_stack_includes_bash():
    """Bluefin Server OS must include bash for login and interactive access."""
    os_stack = ELEMENTS_DIR / "bluefin-server" / "os-stack.bst"
    data = yaml.safe_load(os_stack.read_text(encoding="utf-8"))
    depends = data.get("depends", [])

    assert "freedesktop-sdk.bst:bootstrap/bash.bst" in depends, (
        "os-stack.bst must include freedesktop-sdk.bst:bootstrap/bash.bst"
    )




