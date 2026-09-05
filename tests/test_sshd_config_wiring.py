"""Static contracts for the FSDK OpenSSH configuration shim."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ELEMENT = ROOT / "elements/bluefin-server/os-sshd-config.bst"
STACK = ROOT / "elements/bluefin-server/os-stack.bst"
DROPIN = ROOT / "files/os/ssh/sshd_config.d/bluefin-server.conf"

COMPILED_CONFIG = "%{sysconfdir}/ssh/sshd_config"
VENDOR_CONFIG = "%{install-root}%{prefix}/etc/ssh/sshd_config"
VENDOR_DROPIN_DIR = "%{install-root}%{prefix}/etc/ssh/sshd_config.d"
OPERATOR_INCLUDE = "Include /etc/ssh/sshd_config.d/*.conf"
VENDOR_INCLUDE = "Include /usr/etc/ssh/sshd_config.d/*.conf"
SHIM_LINK = "%{install-root}%{sysconfdir}/ssh/sshd_config"
SHIM_TARGET = "../../usr/etc/ssh/sshd_config"
EXPECTED_POLICY = {
    "permitrootlogin": "prohibit-password",
    "pubkeyauthentication": "yes",
    "passwordauthentication": "no",
    "kbdinteractiveauthentication": "no",
}


def directives(text: str) -> dict[str, str]:
    return {
        parts[0].lower(): parts[1].lower()
        for line in text.splitlines()
        if (parts := line.split(None, 1)) and not line.lstrip().startswith("#")
    }


def effective_config(text: str, include_files: dict[str, str]) -> dict[str, str]:
    effective: dict[str, str] = {}

    def visit(config: str) -> None:
        for line in config.splitlines():
            parts = line.split(None, 1)
            if not parts or line.lstrip().startswith("#"):
                continue
            key = parts[0].lower()
            value = parts[1] if len(parts) == 2 else ""
            if key == "include":
                for path in sorted(include_files):
                    if Path(path).match(value):
                        visit(include_files[path])
            elif key not in effective:
                effective[key] = value.lower()

    visit(text)
    return effective


def test_policy_is_fail_closed():
    assert directives(DROPIN.read_text()) == EXPECTED_POLICY


def test_element_uses_vanilla_fsdk_openssh_layout():
    element = ELEMENT.read_text()
    assert f'src="{COMPILED_CONFIG}"' in element
    assert f'dest="{VENDOR_CONFIG}"' in element
    assert f'"{VENDOR_DROPIN_DIR}"' in element
    assert "public-stacks/runtime-gnu.bst" in element
    assert re.search(r"build-depends:[\s\S]*components/openssh-systemd\.bst", element)
    assert re.search(
        r"\ndepends:\s*\n\s*- freedesktop-sdk\.bst:components/openssh-systemd\.bst",
        element,
    )


def test_vendor_paths_and_shim_are_minimal():
    element = ELEMENT.read_text()
    assert OPERATOR_INCLUDE in element
    assert VENDOR_INCLUDE in element
    assert element.index(OPERATOR_INCLUDE) < element.index(VENDOR_INCLUDE)
    assert element.index(VENDOR_INCLUDE) < element.index('        } > "${dest}"')
    assert f'ln -sfn {SHIM_TARGET} "{SHIM_LINK}"' in element
    assert re.search(
        r"overlap-whitelist:\s*\n\s*- "
        + re.escape(f'"{COMPILED_CONFIG}"'),
        element,
    )
    assert "Include /etc/sshd_config.d/*.conf" not in element
    assert "/usr/etc/sshd_config" not in element


def test_relative_shim_resolves_to_vendor_config():
    path = Path("/etc/ssh")
    for part in Path(SHIM_TARGET).parts:
        path = path.parent if part == ".." else path / part
    assert path == Path("/usr/etc/ssh/sshd_config")


def test_operator_and_vendor_dropins_have_correct_precedence():
    rendered = f"{OPERATOR_INCLUDE}\n{VENDOR_INCLUDE}\n\nPasswordAuthentication yes\n"
    effective = effective_config(
        rendered,
        {
            "/etc/ssh/sshd_config.d/20-systemd-userdb.conf": (
                "AuthorizedKeysCommand /usr/bin/userdbctl ssh-authorized-keys %u\n"
            ),
            "/etc/ssh/sshd_config.d/30-operator.conf": "PasswordAuthentication yes\n",
            "/usr/etc/ssh/sshd_config.d/bluefin-server.conf": DROPIN.read_text(),
        },
    )
    assert effective["authorizedkeyscommand"] == "/usr/bin/userdbctl ssh-authorized-keys %u"
    assert effective["passwordauthentication"] == "yes"
    assert effective["permitrootlogin"] == "prohibit-password"


def test_stack_keeps_openssh_policy_and_no_enable_preset():
    stack = STACK.read_text()
    assert "freedesktop-sdk.bst:components/openssh-systemd.bst" in stack
    assert "bluefin-server/os-sshd-config.bst" in stack
    assert not (ROOT / "elements/bluefin-server/os-sshd-preset.bst").exists()
