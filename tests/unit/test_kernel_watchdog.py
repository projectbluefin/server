"""Contracts for the kernel watchdog patch (issue #377).

FSDK's stock kernel config has no watchdog options at all (grep -i watchdog
files/linux/fdsdk-config.sh returns nothing), so even with systemd's
RuntimeWatchdogSec= enabled `/dev/watchdog` does not exist and any hardware
watchdog driver is missing.  The fix is a new FSDK patch that enables the
watchdog core and the common x86 server / BMC watchdog drivers as modules
so an operator can `modprobe` the one that matches the platform without
rebuilding the kernel.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KERNEL_PATCH = ROOT / "patches" / "freedesktop-sdk" / "0007-linux-watchdog.patch"
KUBENET_PATCH = ROOT / "patches" / "freedesktop-sdk" / "0006-linux-kubernetes-cilium-networking.patch"
BUILD_MODES_TEST = ROOT / "tests" / "unit" / "test_build_modes.py"


def _added_lines() -> list[str]:
    """Return the lines this patch inserts, with the leading '+' stripped
    but original indentation preserved.  Callers should use
    `_line_begins_with` for substring matching — `module XYZ` may sit
    inside a `case` block with leading whitespace and a trailing comment.
    """
    return [
        line[1:]
        for line in KERNEL_PATCH.read_text().splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def _line_begins_with(token: str) -> bool:
    """True iff any inserted line starts with `token` (ignoring leading
    whitespace).  Used so `module XYZ` matches both top-level inserts and
    the same driver nested inside an `arch == x86_64` case block.
    """
    return any(line.lstrip().startswith(token) for line in _added_lines())


def test_patch_targets_fsdk_linux_config_script() -> None:
    text = KERNEL_PATCH.read_text()
    assert "diff --git a/files/linux/fdsdk-config.sh b/files/linux/fdsdk-config.sh" in text
    assert "+++ b/files/linux/fdsdk-config.sh" in text


def test_patch_appends_after_the_existing_tail() -> None:
    """0006 owns the last line of fdsdk-config.sh after it lands
    (`module NETFILTER_XT_TARGET_NOTRACK`); 0007 reproduces it as hunk
    context and adds the watchdog block below.
    """
    text = KERNEL_PATCH.read_text()
    assert " module NETFILTER_XT_TARGET_NOTRACK" in text
    assert " enable INET_DIAG_DESTROY" in text


def test_patch_applies_after_0006() -> None:
    """0007's hunk context must reproduce 0006's tail so patch_queue can
    stack them in lexical order without the second hunk failing with
    "corrupt patch", and without relying on git apply's offset tolerance.
    """
    import subprocess
    import tempfile

    # Build a synthetic fdsdk-config.sh: 2809 filler lines + the original
    # 3-line EOF block (matching 0006's pre-context).  Apply 0006, then
    # `git apply --check` 0007 against the modified tree — exactly what
    # bst-plugins-community's `patch_queue.stage` does.
    body = "\n".join(f"line {i}" for i in range(1, 2810)) + (
        "\nif has HAVE_ARCH_TRANSPARENT_HUGEPAGE; then\n"
        "    enable TRANSPARENT_HUGEPAGE\n"
        "fi\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "fsdk"
        tree.mkdir()
        (tree / "files" / "linux").mkdir(parents=True)
        (tree / "files" / "linux" / "fdsdk-config.sh").write_text(body)
        subprocess.run(["git", "init", "-q"], cwd=tree, check=True)
        subprocess.run(["git", "add", "-A"], cwd=tree, check=True)
        subprocess.run(
            ["git", "-c", "user.email=test@example.com",
             "-c", "user.name=test", "commit", "-q", "-m", "base"],
            cwd=tree, check=True,
        )
        patch6 = ROOT / "patches" / "freedesktop-sdk" / (
            "0006-linux-kubernetes-cilium-networking.patch"
        )
        patch7 = ROOT / "patches" / "freedesktop-sdk" / (
            "0007-linux-watchdog.patch"
        )
        result = subprocess.run(
            ["git", "apply", str(patch6)],
            cwd=tree, capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"0006 does not apply on the synthetic tree:\n{result.stderr}"
        )
        result = subprocess.run(
            ["git", "apply", "--check", str(patch7)],
            cwd=tree, capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            "0007 does not apply on top of 0006 — the second hunk in the\n"
            "patch_queue stack fails, which makes the entire kernel build\n"
            f"fail at source staging.  stderr:\n{result.stderr}"
        )


@pytest.mark.parametrize(
    "option",
    [
        # Watchdog core is built in.  /dev/watchdog only appears once a
        # driver registers the first watchdog device; systemd's
        # RuntimeWatchdogSec= is a no-op until then.
        "WATCHDOG",
        "WATCHDOG_CORE",
        # Common x86 server watchdog drivers, as modules (guarded by `case "$arch"
        # in x86_64)` because the Kconfig symbols are x86-only and FSDK's
        # `module()` script appends them to expected-configs; an aarch64
        # kernel build would otherwise fail "Missing XYZ" at olddefconfig).
        "I6300ESB_WDT",     # Intel 6300ESB PCI watchdog (older servers).
        "ITCO_WDT",         # Intel ICH/PCH TCO watchdog (most x86 boards).
        "SP5100_TCO",       # AMD SP5100/AM79C974 TCO watchdog (AMD servers).
        "IT87_WDT",         # IT87xx Super-I/O watchdog (older motherboards).
        "W83627HF_WDT",     # W83627HF + NCT6775/6776/6779/6791/6792 Super-I/O watchdog.
        "SOFT_WATCHDOG",    # Software watchdog: opt-in fallback (no modalias, not autoloaded).
        "IPMI_WATCHDOG",    # BMC watchdog (Intel/AMI IPMI 2.0 compliant BMCs).
    ],
)
def test_watchdog_options_are_added(option: str) -> None:
    assert _line_begins_with(f"module {option}") or _line_begins_with(
        f"enable {option}"
    ), option


def test_core_options_are_built_in_not_modules() -> None:
    """WATCHDOG and WATCHDOG_CORE must be `enable`d (built-in), not modules.

    Built in, the core needs no module load before a driver can register.
    /dev/watchdog itself only appears once a driver registers the first
    watchdog device: i6300esb / iTCO_wdt / sp5100_tco autoload via
    modalias, while it87_wdt / w83627hf_wdt / ipmi_watchdog / softdog must
    be loaded explicitly.
    """
    assert _line_begins_with("enable WATCHDOG")
    assert _line_begins_with("enable WATCHDOG_CORE")
    # And conversely, the specific drivers are modules, not built-in: a node
    # that lacks the hardware does not carry the driver in the kernel image.
    assert _line_begins_with("module I6300ESB_WDT")
    assert _line_begins_with("module ITCO_WDT")
    assert _line_begins_with("module SP5100_TCO")


def test_x86_only_drivers_are_arch_guarded() -> None:
    """I6300ESB_WDT / ITCO_WDT / SP5100_TCO / IT87_WDT / W83627HF_WDT are
    x86-only Kconfig symbols.  FSDK's `module()` appends them to
    expected-configs for every arch, so without an `arch == x86_64` guard
    an aarch64 kernel build would fail "Missing XYZ" at olddefconfig time.
    """
    text = KERNEL_PATCH.read_text()
    assert 'case "$arch" in' in text
    assert "x86_64)" in text
    # Arch-agnostic drivers stay outside the case.
    assert _line_begins_with("module SOFT_WATCHDOG")
    assert _line_begins_with("module IPMI_WATCHDOG")


def test_patch_number_is_one_above_0006() -> None:
    """0007 is the next entry after 0006 in the patch_queue (lexical order)."""
    assert KERNEL_PATCH.name == "0007-linux-watchdog.patch"
    assert int(KERNEL_PATCH.name.split("-", 1)[0]) == int(
        KUBENET_PATCH.name.split("-", 1)[0]
    ) + 1


def test_patches_readme_documents_the_watchdog_patch() -> None:
    """patches/README.md must explain why 0007 exists and when to drop it."""
    readme = (ROOT / "patches" / "README.md").read_text()
    assert "0007-linux-watchdog.patch" in readme


def test_build_modes_recognises_0007_as_full_build_trigger() -> None:
    """A PR that changes patches/freedesktop-sdk/0007-*.patch must trigger a
    full kernel build (image=true), not just `validate`; the 0006 entry in
    test_build_modes.py shows the pattern, and the 0007 entry mirrors it."""
    assert "0007-x.patch" in BUILD_MODES_TEST.read_text()
