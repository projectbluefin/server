"""Contracts for root's shipped credential and the SSH login policy.

The public DDI must not carry a usable password: root ships locked as
``!unprovisioned`` and access is provisioned per node (Ignition, or the
``passwd.*.root`` / ``ssh.authorized_keys.root`` system credentials). This
file pins that contract:

- the /usr image seeds root as ``!unprovisioned``, the only locked value
  systemd-firstboot still provisions from a password credential;
- no crypt(5) hash is baked into any element or image payload file;
- systemd-firstboot cannot block a headless boot on a root password prompt;
- the console banner advertises no credentials; and
- the effective SSH policy never allows a password over the network.
"""


import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
USR_ELEMENT = REPO_ROOT / "elements" / "oci" / "bluefin-server-usr.bst"
CREDS_ELEMENT = REPO_ROOT / "elements" / "bluefin-server" / "os-creds-prov.bst"
FIRSTBOOT_DROPIN = (
    REPO_ROOT
    / "files"
    / "os"
    / "creds"
    / "systemd"
    / "system"
    / "systemd-firstboot.service.d"
    / "10-bluefin-no-root-prompt.conf"
)
SSHD_DROPIN = REPO_ROOT / "files" / "os" / "ssh" / "sshd_config.d" / "bluefin-server.conf"
GENERATED_SSHD_DROPIN = (
    REPO_ROOT
    / "files"
    / "os"
    / "systemd"
    / "system"
    / "sshd-generated@.service.d"
    / "10-host-keygen.conf"
)
ISSUE_FILE = REPO_ROOT / "files" / "os" / "issue.d" / "30-bluefin.issue"
ACCESS_SKILL = REPO_ROOT / "docs" / "skills" / "tpm2-credential-sealing.md"

# crypt(5) hash strings: MD5, bcrypt, SHA-256/512, scrypt, yescrypt,
# gost-yescrypt and sunmd5 prefixes followed by a salt/parameter field.
CRYPT_HASH_RE = re.compile(r"\$(?:1|2[abxy]|5|6|7|y|gy|md5)\$[./0-9A-Za-z,=]+\$")
# Signing material is gitignored and generated per checkout; it is not image
# payload text.
SCANNED_TREES = ("elements", "files", "include")
SKIPPED_TREES = ("files/boot-keys",)


def _seeded_root_shadow_line(element: str) -> str:
    match = re.search(r"printf '(root:[^']*)'", element)
    assert match, "/usr image element must seed root's /etc/shadow entry"
    return match.group(1).split("\\n")[0]


def test_root_ships_unprovisioned_and_locked() -> None:
    fields = _seeded_root_shadow_line(USR_ELEMENT.read_text(encoding="utf-8")).split(":")

    assert len(fields) == 9, "seeded shadow line must have all 9 shadow fields"
    assert fields[0] == "root"
    # "!unprovisioned" is locked for login/su/sulogin (leading "!") and is the
    # value systemd-firstboot treats as "root not configured", so a
    # passwd.hashed-password.root credential can still set it. "!*" or "*"
    # would lock root with no credential path at all.
    assert fields[1] == "!unprovisioned"


def test_no_password_hash_is_baked_into_the_image() -> None:
    offenders = []
    for tree in SCANNED_TREES:
        for path in sorted((REPO_ROOT / tree).rglob("*")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if not path.is_file() or rel.startswith(SKIPPED_TREES):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if CRYPT_HASH_RE.search(text):
                offenders.append(rel)

    assert not offenders, f"crypt(5) password hashes baked into image sources: {offenders}"


def test_crypt_hash_pattern_catches_known_formats() -> None:
    for sample in (
        "$6$saltsalt$Mbb3dJ5M1XbRhW0XgW7hJvB0kxc",
        "$y$j9T$F5Jx5fExrKuPp53xLKQ..1$X3DX6M94c7o.9agCG9G317fhZg9SqC.5i5rd.RhAtQ7",
        "$5$rounds=5000$salt$hash",
        "$2b$12$abcdefghijklmnopqrstuu",
    ):
        assert CRYPT_HASH_RE.search(sample), sample
    assert not CRYPT_HASH_RE.search('printf "%s" "$6"')


def test_firstboot_never_prompts_for_a_root_password() -> None:
    dropin = FIRSTBOOT_DROPIN.read_text(encoding="utf-8")
    exec_lines = re.findall(r"^ExecStart=(.*)$", dropin, re.MULTILINE)

    # An empty ExecStart= resets upstream's command, which carries
    # --prompt-root-password and would wait on the console of every
    # headless boot (and the USB installer) now that root is unprovisioned.
    assert exec_lines[0] == ""
    assert len(exec_lines) == 2
    assert exec_lines[1].startswith("systemd-firstboot ")
    assert "--prompt-root-password" not in exec_lines[1]
    assert "--prompt-root-shell" not in exec_lines[1]
    assert "--prompt " not in f"{exec_lines[1]} "


def test_firstboot_dropin_is_installed() -> None:
    element = CREDS_ELEMENT.read_text(encoding="utf-8")

    assert "path: files/os/creds/systemd/system" in element
    assert 'cp -a systemd-src/. "%{install-root}/usr/lib/systemd/system/"' in element


def test_sshd_dropin_never_permits_password_authentication() -> None:
    sshd = SSHD_DROPIN.read_text(encoding="utf-8")

    assert re.search(r"^PermitRootLogin\s+prohibit-password$", sshd, re.MULTILINE)
    assert re.search(r"^PasswordAuthentication\s+no$", sshd, re.MULTILINE)
    assert re.search(r"^KbdInteractiveAuthentication\s+no$", sshd, re.MULTILINE)
    assert not re.search(r"^PermitRootLogin\s+yes$", sshd, re.MULTILINE)
    assert not re.search(r"^PasswordAuthentication\s+yes$", sshd, re.MULTILINE)


def test_generated_sshd_gets_per_device_host_keys() -> None:
    dropin = GENERATED_SSHD_DROPIN.read_text(encoding="utf-8")

    # The ssh.listen credential is the credential-only way to open SSH; its
    # systemd-ssh-generator sshd exits without host keys.
    assert re.search(r"^Wants=ssh-host-keygen\.service$", dropin, re.MULTILINE)
    assert re.search(r"^After=ssh-host-keygen\.service$", dropin, re.MULTILINE)


def test_console_banner_advertises_no_credentials() -> None:
    banner = ISSUE_FILE.read_text(encoding="utf-8")

    assert not re.search(r"password", banner, re.IGNORECASE)
    assert not re.search(r"\blogin\s*:", banner, re.IGNORECASE)
    assert "bluefin123" not in banner
    assert not re.search(r"root\s*/\s*\S", banner)
    assert "root is locked" in banner


def test_console_banner_points_at_the_access_skill() -> None:
    banner = ISSUE_FILE.read_text(encoding="utf-8")
    match = re.search(r"https://github\.com/projectbluefin/server/blob/main/(\S+?)#(\S+)", banner)

    assert match, "banner must link the canonical node access docs"
    target = REPO_ROOT / match.group(1)
    assert target == ACCESS_SKILL
    assert f"## {match.group(2).replace('-', ' ').capitalize()}" in target.read_text(encoding="utf-8")
