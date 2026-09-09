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


ELEMENTS = ROOT / "elements"
FILES_OS = ROOT / "files/os"
PRESET_DIR = FILES_OS / "systemd/system-preset"


def _os_stack_import_sources() -> dict[str, dict[str, str | None]]:
    """Map every local source path packaged by the OS stack to its import element."""
    depends = yaml.safe_load(STACK.read_text(encoding="utf-8"))["depends"]
    packaged: dict[str, dict[str, str | None]] = {}
    for dep in depends:
        if not isinstance(dep, str) or not dep.startswith("bluefin-server/"):
            continue
        data = yaml.safe_load((ELEMENTS / dep).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("kind") != "import":
            continue
        target = (data.get("config") or {}).get("target")
        for source in data.get("sources") or []:
            if isinstance(source, dict) and source.get("kind") == "local":
                packaged[source["path"]] = {"element": dep, "target": target}
    return packaged


def test_systemd_presets_are_packaged_by_the_os_stack() -> None:
    packaged = _os_stack_import_sources()
    entry = packaged.get("files/os/systemd/system-preset")
    assert entry is not None, (
        "files/os/systemd/system-preset is not imported by any element in os-stack.bst"
    )
    assert entry["target"] == "/usr/lib/systemd/system-preset"
    assert {path.name for path in PRESET_DIR.iterdir()} == {
        "zz-enable-networkd.preset",
        "zz-enable-k0s-first-boot.preset",
        "zz-enable-var-mount.preset",
    }


def test_no_os_payload_file_is_orphaned_from_the_os_stack() -> None:
    packaged = set(_os_stack_import_sources())
    orphans = []
    for path in sorted(FILES_OS.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        covered = str(rel) in packaged or any(str(p) in packaged for p in rel.parents)
        if not covered:
            orphans.append(str(rel))
    assert orphans == [], f"OS payload files are not imported by any os-stack element: {orphans}"


DDI = ROOT / "elements/oci/bluefin-server-ddi.bst"
ISSUE = ROOT / "files/os/issue.d/40-kubestellar.issue"
SSHD_PRESET = ROOT / "files/os/systemd/system-preset/zz-enable-sshd.preset"


def test_ddi_restores_setuid_root_on_sudo() -> None:
    ddi = DDI.read_text(encoding="utf-8")
    assert "chmod 4755 /layer/usr/bin/sudo" in ddi, (
        "BuildStream strips setuid bits; the DDI must restore mode 4755 on /usr/bin/sudo "
        "so the key-only core operator can elevate through wheel"
    )


def test_ddi_contains_no_root_credential_or_shared_host_key() -> None:
    ddi = DDI.read_text(encoding="utf-8")
    assert 'u root 0 "root" /root /bin/bash' in SYSUSERS.read_text(encoding="utf-8").splitlines()
    assert "/etc/shadow" not in ddi
    assert "bluefin123" not in ddi
    assert "$6$" not in ddi
    assert "root:!:" not in ddi
    assert "Default login: root / bluefin" not in ISSUE.read_text(encoding="utf-8")
    assert "/layer/etc/securetty" not in ddi
    assert "ssh-keygen -q -N" not in ddi
    assert "ln -sfn /var/home /layer/home" in ddi
    assert "multi-user.target.wants/sshd.service" in ddi
    assert not SSHD_PRESET.exists()


ROADMAP = ROOT / "docs/skills/architecture-roadmap.md"


def test_roadmap_scopes_the_open_credential_gap_to_network_configuration() -> None:
    roadmap = ROADMAP.read_text(encoding="utf-8")
    assert "root` password credential" not in roadmap
    assert "root password" not in roadmap
    assert "tmpfiles.extra" in roadmap, (
        "the roadmap must recognize that core SSH keys are already provisioned "
        "through the tmpfiles.extra credential"
    )
    assert "static network configuration" in roadmap
