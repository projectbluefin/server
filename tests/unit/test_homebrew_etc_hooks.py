"""The homebrew-integration sysext's /etc hooks once the sysext is unmerged.

Its tmpfiles.d fragment (files/homebrew/bluefin-homebrew.tmpfiles) writes into
/etc, which persists on installed nodes, and nothing removes those entries
when the sysext goes away. A link into the sysext then dangles: sudo and the
shell profile skip such entries, but sshd exits when a file its Include glob
matches cannot be opened. So the sshd drop-in is a real file that includes the
sysext's settings by a path that matches nothing once the sysext is gone.
"""


import shutil
import subprocess
from pathlib import Path

import pytest

from _systemd import tmpfiles

ROOT = Path(__file__).resolve().parents[2]
RULES = tmpfiles(ROOT / "files" / "homebrew" / "bluefin-homebrew.tmpfiles")
SYSEXT = "/usr/lib/bluefin-homebrew"
SSHD_D = "/etc/ssh/sshd_config.d"


def test_only_consumers_that_skip_dangling_entries_link_into_the_sysext() -> None:
    links = {rule.path: rule.argument for rule in RULES if rule.type.startswith("L")}
    assert links == {
        "/etc/profile.d/90-bluefin-homebrew.sh": f"{SYSEXT}/90-bluefin-homebrew.sh",
        "/etc/sudoers.d/bluefin-homebrew": f"{SYSEXT}/bluefin-homebrew.sudoers",
    }


def test_sshd_drop_in_is_a_real_file_that_includes_the_sysext_settings() -> None:
    sshd = [(rule.type, rule.path, rule.argument) for rule in RULES if rule.path.startswith(f"{SSHD_D}/")]
    assert sshd == [
        # Removes the link earlier images created.
        ("r", f"{SSHD_D}/90-bluefin-homebrew.conf", "-"),
        ("f+", f"{SSHD_D}/90-bluefin-homebrew-sysext.conf", f"Include {SYSEXT}/sshd.conf"),
    ]
    dispatch = (ROOT / "elements" / "homebrew" / "dispatch.bst").read_text(encoding="utf-8")
    assert f'sshd.conf -t "%{{install-root}}{SYSEXT}/"' in dispatch


def test_sshd_starts_with_what_an_unmerged_sysext_leaves_behind(tmp_path: Path) -> None:
    sshd = shutil.which("sshd") or shutil.which("sshd", path="/usr/sbin")
    if not sshd or not shutil.which("ssh-keygen"):
        pytest.skip("needs OpenSSH")
    if Path(SYSEXT).exists():
        pytest.skip(f"{SYSEXT} exists on this host")
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "key")], check=True)
    dropins = tmp_path / "sshd_config.d"
    dropins.mkdir()
    config = tmp_path / "sshd_config"
    config.write_text(f"Include {dropins}/*.conf\nHostKey {tmp_path / 'key'}\n", encoding="utf-8")
    argv = [sshd, "-t", "-f", str(config)]
    if subprocess.run(argv, capture_output=True).returncode:
        pytest.skip("sshd -t does not run unprivileged here")

    # What the rules leave in sshd_config.d once the sysext is gone: links
    # into it dangle (it does not exist here), files keep their content.
    for rule in RULES:
        entry = dropins / Path(rule.path).name
        if rule.path.startswith(f"{SSHD_D}/") and rule.type.startswith("L"):
            entry.symlink_to(rule.argument)
        elif rule.path.startswith(f"{SSHD_D}/") and rule.type.startswith("f"):
            entry.write_text(rule.argument, encoding="utf-8")
    result = subprocess.run(argv, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    # A link into the sysext, as earlier images created, stops sshd.
    (dropins / "90-bluefin-homebrew.conf").symlink_to(f"{SYSEXT}/sshd.conf")
    result = subprocess.run(argv, capture_output=True, text=True)
    assert result.returncode != 0
    assert "90-bluefin-homebrew.conf: No such file or directory" in result.stderr
