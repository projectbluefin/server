"""Every tracked shell script is shellcheck clean, at one severity.

The scripts are the files `git ls-files` lists under scripts/, files/,
.github/scripts/, tests/ and the repository root that end .sh or .bash, or
whose first line is a sh, bash or dash shebang; vendored trees and bats files
are left out. ShellCheck takes each script's dialect from its shebang or a
`# shellcheck shell=` directive, and fails a script with neither (SC2148).
An intentional finding is silenced on the line above it, with a reason:
`# shellcheck disable=SCxxxx # reason`.
"""


import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIRS = ("scripts/", "files/", ".github/scripts/", "tests/")
# Vendored code is linted upstream.
VENDORED = ("files/homelab/cluster/vendor/",)
SHEBANG = re.compile(rb"#!\s*/(?:usr/)?bin/(?:env\s+(?:-S\s*)?)?(?:sh|bash|dash)(?:\s|$)")


def is_shell_script(name: str) -> bool:
    if not name or ("/" in name and not name.startswith(DIRS)) or name.startswith(VENDORED):
        return False
    path = ROOT / name
    if name.endswith(".bats") or path.is_symlink() or not path.is_file():
        return False
    if name.endswith((".sh", ".bash")):
        return True
    with path.open("rb") as f:
        return SHEBANG.match(f.readline()) is not None


def shell_scripts() -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=False)
    names = listed.stdout.decode().split("\0") if listed.returncode == 0 else []
    return sorted(name for name in names if is_shell_script(name))


SCRIPTS = shell_scripts()


def test_the_scripts_are_found() -> None:
    # A discovery that finds nothing would pass every script vacuously.
    assert len(SCRIPTS) >= 40, SCRIPTS
    assert {
        "scripts/dogfood-install.sh",  # by extension
        "scripts/dogfood-lan.sh",  # sourced, no shebang
        "files/os/libexec/bluefin-installer-disk",  # by its bash shebang
        "files/kubeadm/sysext/bluefin-kubeadm-init",  # by its sh shebang
        ".github/scripts/propose-pr.sh",
    } <= set(SCRIPTS)


@pytest.mark.parametrize("script", SCRIPTS)
def test_the_script_is_shellcheck_clean(shellcheck: str, script: str) -> None:
    # Run from the root, where `# shellcheck source=scripts/...` paths start;
    # SCRIPTDIR follows a file sourced from the script's own directory.
    # --norc: no .shellcheckrc, in the tree or in $HOME, changes the verdict.
    result = subprocess.run(
        [shellcheck, "--norc", "-x", "-P", "SCRIPTDIR", "-S", "style", script],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
