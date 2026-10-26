"""Exercise private owner-key provisioning with real unprivileged filesystem access."""
import importlib.machinery
import importlib.util
import os
import pwd
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "files/homebrew/bluefin-homebrew-prepare"
loader = importlib.machinery.SourceFileLoader("home_owner_keys_prepare", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
prepare = importlib.util.module_from_spec(spec)
loader.exec_module(prepare)
KEYS = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBqzDgD4BSxzGtXT+kRrjk9D5XR49PgBmYMzNRNPGBhX owner-test"
pytestmark = pytest.mark.root


@pytest.fixture
def owner_home():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        root.chmod(0o755)
        home = root / "home"
        home.mkdir(mode=0o700)
        account = pwd.getpwuid(65534)
        os.chown(home, account.pw_uid, account.pw_gid)
        owner = pwd.struct_passwd((account.pw_name, account.pw_passwd, account.pw_uid,
                                  account.pw_gid, account.pw_gecos, str(home), "/bin/bash"))
        yield root, home, owner


def provision(owner, keys=KEYS):
    with patch.object(prepare, "credential", side_effect=lambda name:
                      keys if name == f"ssh.authorized_keys.{owner.pw_name}" else ""):
        prepare.provision_owner_keys(owner)


def test_private_credential_creates_owner_readable_key_and_private_modes(owner_home):
    _, home, owner = owner_home
    provision(owner)
    ssh = home / ".ssh"
    authorized = ssh / "authorized_keys"
    assert ssh.stat().st_uid == owner.pw_uid
    assert ssh.stat().st_gid == owner.pw_gid
    assert ssh.stat().st_mode & 0o777 == 0o700
    assert authorized.stat().st_uid == owner.pw_uid
    assert authorized.stat().st_gid == owner.pw_gid
    assert authorized.stat().st_mode & 0o777 == 0o600
    result = subprocess.run(["cat", authorized], user=owner.pw_uid, group=owner.pw_gid,
                            extra_groups=[], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout == KEYS + "\n"


def test_selected_owner_receives_private_ssh_credential(owner_home):
    _, home, owner = owner_home
    # select_owner deliberately excludes nobody's sentinel UID; no real account
    # is created or changed to exercise credential delivery to a login identity.
    selected = pwd.struct_passwd((owner.pw_name, owner.pw_passwd, 65533,
                                  owner.pw_gid, owner.pw_gecos, str(home), "/bin/bash"))
    os.chown(home, selected.pw_uid, selected.pw_gid)
    with patch.object(prepare, "credential", side_effect=lambda name:
                      KEYS if name == f"ssh.authorized_keys.{selected.pw_name}" else ""), \
            patch.object(prepare, "login_users", return_value=[selected]), \
            patch.object(prepare.pwd, "getpwnam", return_value=selected):
        prepare.select_owner({"OWNER": selected.pw_name})
    authorized = home / ".ssh/authorized_keys"
    assert authorized.is_file(), "the selected owner must receive its private SSH credential"
    assert authorized.read_text() == KEYS + "\n"
    assert authorized.stat().st_uid == selected.pw_uid


def test_absent_private_key_credential_preserves_existing_authorized_keys(owner_home):
    _, home, owner = owner_home
    provision(owner)
    authorized = home / ".ssh/authorized_keys"
    original = authorized.read_bytes()
    provision(owner, "")
    assert authorized.read_bytes() == original
    assert authorized.stat().st_uid == owner.pw_uid


@pytest.mark.parametrize("redirect", ["ssh-directory", "authorized-keys"])
def test_owner_symlinks_cannot_overwrite_or_take_ownership_of_root_files(owner_home, redirect):
    root, home, owner = owner_home
    victim = root / "root-private"
    victim.mkdir(mode=0o700)
    keyfile = victim / "authorized_keys"
    keyfile.write_text("root-protected-key\n")
    keyfile.chmod(0o600)
    if redirect == "ssh-directory":
        (home / ".ssh").symlink_to(victim, target_is_directory=True)
    else:
        ssh = home / ".ssh"
        ssh.mkdir(mode=0o700)
        os.chown(ssh, owner.pw_uid, owner.pw_gid)
        (ssh / "authorized_keys").symlink_to(keyfile)
    try:
        provision(owner)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
        # Rejecting a hostile link or atomically replacing the key link are both
        # safe; neither may follow it with root's authority.
        pass
    assert keyfile.read_text() == "root-protected-key\n"
    assert victim.stat().st_uid == 0
    assert keyfile.stat().st_uid == 0
    assert victim.stat().st_mode & 0o777 == 0o700
    assert keyfile.stat().st_mode & 0o777 == 0o600
