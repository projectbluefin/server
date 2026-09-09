from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SYSUSERS = ROOT / "files/os/sysusers.d/10-core-user.conf"
TMPFILES = ROOT / "files/os/tmpfiles.d/10-core-home.conf"
SUDOERS = ROOT / "files/os/sudoers.d/10-wheel-nopasswd"
STACK = ROOT / "elements/bluefin-server/os-stack.bst"


def test_core_operator_is_stable_key_only_and_persistent() -> None:
    assert SYSUSERS.read_text(encoding="utf-8") == (
        'u root 0 "root" /root /bin/bash\n'
        'u core 1000 "Bluefin Server Operator" /var/home/core /bin/bash\n'
        "m core wheel\n"
    )
    assert TMPFILES.read_text(encoding="utf-8") == (
        "d /var/home 0755 root root -\n"
        "d /var/home/core 0700 core core -\n"
        "d /var/home/core/.ssh 0700 core core -\n"
    )
    assert SUDOERS.read_text(encoding="utf-8") == "%wheel ALL=(ALL) NOPASSWD: ALL\n"


def test_core_login_elements_are_composed() -> None:
    depends = yaml.safe_load(STACK.read_text(encoding="utf-8"))["depends"]
    assert "freedesktop-sdk.bst:components/sudo.bst" in depends
    assert "bluefin-server/os-tmpfiles.bst" in depends
    assert "bluefin-server/os-sudo.bst" in depends
