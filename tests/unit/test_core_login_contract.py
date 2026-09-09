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


SSH_CONFIG = ROOT / "files/os/ssh/sshd_config.d/bluefin-server.conf"
HOST_KEYS_SERVICE = ROOT / "files/os/systemd/system/bluefin-ssh-host-keys.service"
CORE_ACCESS_SERVICE = ROOT / "files/os/systemd/system/bluefin-core-access.service"
SSHD_DROP_IN = ROOT / "files/os/systemd/system/sshd.service.d/10-bluefin-access.conf"


def test_ssh_is_key_only_and_never_accepts_root() -> None:
    assert SSH_CONFIG.read_text(encoding="utf-8") == (
        "PermitRootLogin no\n"
        "PubkeyAuthentication yes\n"
        "PasswordAuthentication no\n"
        "KbdInteractiveAuthentication no\n"
        "HostKey /var/lib/ssh/ssh_host_ed25519_key\n"
        "HostKey /var/lib/ssh/ssh_host_rsa_key\n"
    )


def test_sshd_requires_persistent_host_keys_and_core_authorization() -> None:
    host_keys = HOST_KEYS_SERVICE.read_text(encoding="utf-8")
    access = CORE_ACCESS_SERVICE.read_text(encoding="utf-8")
    drop_in = SSHD_DROP_IN.read_text(encoding="utf-8")

    assert "StateDirectory=ssh" in host_keys
    assert "After=var.mount" in host_keys
    assert "Before=sshd.service" in host_keys
    assert "/var/lib/ssh/ssh_host_ed25519_key" in host_keys
    assert "/var/lib/ssh/ssh_host_rsa_key" in host_keys
    assert "After=var.mount systemd-tmpfiles-setup.service" in access
    assert "ExecStart=/usr/bin/test -s /var/home/core/.ssh/authorized_keys" in access
    assert "Requires=bluefin-ssh-host-keys.service bluefin-core-access.service" in drop_in
    assert "ExecStartPre=" in drop_in
    assert "ExecStartPre=/usr/bin/test -s /var/lib/ssh/ssh_host_ed25519_key" in drop_in


DDI = ROOT / "elements/oci/bluefin-server-ddi.bst"
ISSUE = ROOT / "files/os/issue.d/40-kubestellar.issue"
SSHD_PRESET = ROOT / "files/os/systemd/system-preset/zz-enable-sshd.preset"


def test_ddi_contains_no_root_credential_or_shared_host_key() -> None:
    ddi = DDI.read_text(encoding="utf-8")
    assert "bluefin123" not in ddi
    assert "Default login: root / bluefin" not in ISSUE.read_text(encoding="utf-8")
    assert "/layer/etc/securetty" not in ddi
    assert "ssh-keygen -q -N" not in ddi
    assert "root:!:" in ddi
    assert "ln -sfn /var/home /layer/home" in ddi
    assert "multi-user.target.wants/sshd.service" in ddi
    assert not SSHD_PRESET.exists()
