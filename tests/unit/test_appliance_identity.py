"""Appliance identity in the base OS: a unique default hostname, mDNS on the
wired links, and the interactive bash prompt (#82, #83)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from _systemd import SystemdFile, preset, tmpfiles

ROOT = Path(__file__).resolve().parents[2]
OS = ROOT / "files" / "os"
ELEMENTS = ROOT / "elements" / "bluefin-server"
HOSTNAME_UNIT = OS / "creds" / "systemd" / "system" / "bluefin-hostname.service"
HOSTNAME_HELPER = OS / "libexec" / "bluefin-hostname"
NETWORK = OS / "systemd" / "network" / "20-wired.network"
RESOLVED = OS / "resolved.conf.d" / "50-bluefin-mdns.conf"
PROMPT = OS / "profile.d" / "90-bluefin-prompt.sh"
PROMPT_LINK = OS / "tmpfiles.d" / "50-bluefin-prompt.conf"
PRESETS = sorted((OS / "systemd" / "system-preset").glob("*.preset"))
FSDK_PROMPT = r"[\u@\h \W]\$ "
BLUE_PROMPT = r"\u\[\e[34m\]@\[\e[0m\]\h:\w\$ "
PLAIN_PROMPT = r"\u@\h:\w\$ "


def element(name: str) -> dict:
    return yaml.safe_load((ELEMENTS / name).read_text(encoding="utf-8"))


def stack() -> list[str]:
    return element("os-stack.bst")["depends"]



def test_hostname_unit_names_the_node_on_first_boot_before_the_network() -> None:
    unit = SystemdFile(HOSTNAME_UNIT)
    assert unit.value("Unit", "ConditionFirstBoot") == "yes"
    assert unit.commands() == [["/usr/libexec/bluefin-hostname"]]
    assert unit.value("Service", "Type") == "oneshot"
    # A provisioned name is written first and then kept.
    assert {"systemd-firstboot.service", "bluefin-firstboot-credentials.service"} <= set(unit.words("Unit", "After"))
    assert set(unit.values("Service", "ImportCredential")) == {"firstboot.hostname", "system.hostname"}
    # Named before the first DHCP request and the first mDNS announcement.
    assert {"systemd-networkd.service", "systemd-resolved.service", "sysinit.target"} <= set(unit.words("Unit", "Before"))
    assert unit.words("Install", "WantedBy") == ["sysinit.target"]
    assert preset("bluefin-hostname.service", PRESETS) == "enable"


def test_hostname_helper_ships_in_usr_libexec() -> None:
    commands = "\n".join(element("os-creds-prov.bst")["config"]["install-commands"])
    assert "install -Dm0755 libexec-src/bluefin-hostname" in commands
    assert '"%{install-root}/usr/libexec/bluefin-hostname"' in commands
    assert HOSTNAME_HELPER.stat().st_mode & 0o111
    assert "bluefin-${id:0:8}" in HOSTNAME_HELPER.read_text(encoding="utf-8")



def test_wired_links_use_mdns_and_not_llmnr() -> None:
    network = SystemdFile(NETWORK)
    assert network.value("Match", "Name") == "e*"
    assert network.value("Network", "DHCP") == "ipv4", "DHCP-provided DNS stays"
    assert network.value("Network", "MulticastDNS") == "yes"
    assert network.value("Network", "LLMNR") == "no"


def test_resolved_answers_mdns_and_not_llmnr() -> None:
    resolved = SystemdFile(RESOLVED)
    assert resolved.value("Resolve", "MulticastDNS") == "yes"
    assert resolved.value("Resolve", "LLMNR") == "no"
    data = element("os-resolved.bst")
    assert data["config"]["target"] == "/usr/lib/systemd/resolved.conf.d"
    assert [s["path"] for s in data["sources"]] == ["files/os/resolved.conf.d"]
    assert "bluefin-server/os-resolved.bst" in stack()


def test_mdns_needs_no_other_daemon() -> None:
    stack_text = (ELEMENTS / "os-stack.bst").read_text(encoding="utf-8")
    base_text = (ELEMENTS / "os-base.bst").read_text(encoding="utf-8")
    assert "avahi" not in stack_text + base_text



def test_banner_shows_the_mdns_name() -> None:
    lines = (OS / "issue.d" / "30-bluefin.issue").read_text(encoding="utf-8").splitlines()
    # agetty's \n is the hostname; resolved announces it as <hostname>.local.
    assert r"mDNS: \n.local" in lines
    assert ":8080" not in "\n".join(lines)



def test_prompt_is_linked_into_etc_profile_d_from_usr() -> None:
    (rule,) = tmpfiles(PROMPT_LINK)
    assert rule.type == "L"
    assert rule.path == "/etc/profile.d/90-bluefin-prompt.sh"
    assert os.path.normpath(os.path.join("/etc/profile.d", rule.argument)) == "/usr/lib/bluefin/profile.d/90-bluefin-prompt.sh"
    data = element("os-prompt.bst")
    assert data["config"]["target"] == "/usr/lib/bluefin/profile.d"
    assert [s["path"] for s in data["sources"]] == ["files/os/profile.d"]
    assert "bluefin-server/os-prompt.bst" in stack()
    assert "files/os/tmpfiles.d" in [s["path"] for s in element("os-resolv-conf.bst")["sources"]]


def bash(script: str, *, interactive: bool = True, **env: str) -> str:
    """Run *script* after sourcing the prompt fragment the way FSDK's
    /etc/profile does (profile.d first, then its own PS1)."""
    shell = shutil.which("bash")
    assert shell
    body = f"""
PS1='\\s-\\v\\$ '
. {PROMPT}
PS1='{FSDK_PROMPT}'
{script}
"""
    argv = [shell, "--norc", "--noprofile"] + (["-i"] if interactive else []) + ["-c", body]
    result = subprocess.run(argv, env={"HOME": "/nonexistent", **env}, capture_output=True, text=True, check=True)
    return result.stdout


RUN_PROMPT_COMMAND = 'for c in "${PROMPT_COMMAND[@]}"; do eval "$c"; done; printf "%s" "$PS1"'


def test_prompt_is_user_at_host_cwd_with_a_blue_at() -> None:
    assert bash(RUN_PROMPT_COMMAND, TERM="xterm-256color") == BLUE_PROMPT
    rendered = bash(RUN_PROMPT_COMMAND.replace('"$PS1"', '"${PS1@P}"'), TERM="xterm", USER="root")
    user, _, rest = rendered.partition("\x01\x1b[34m\x02@\x01\x1b[0m\x02")
    assert user and rest, rendered
    host, _, cwd = rest.partition(":")
    assert "\x1b" not in user + host + cwd, "only the @ is coloured"
    # \$ renders as # for UID 0 and $ otherwise.
    assert cwd.endswith("$ ") or cwd.endswith("# ")


@pytest.mark.parametrize("env", [{"TERM": "xterm", "NO_COLOR": "1"}, {"TERM": "dumb"}, {}])
def test_prompt_is_plain_with_no_color_or_a_dumb_terminal(env: dict[str, str]) -> None:
    assert bash(RUN_PROMPT_COMMAND, **env) == PLAIN_PROMPT


def test_prompt_leaves_a_users_own_ps1_alone() -> None:
    out = bash("PS1='mine> '; " + RUN_PROMPT_COMMAND, TERM="xterm")
    assert out == "mine> "


def test_prompt_does_nothing_in_non_interactive_shells() -> None:
    out = bash('printf "%s|%s" "$PS1" "$(declare -p PROMPT_COMMAND 2>&1)"', interactive=False, TERM="xterm")
    ps1, _, prompt_command = out.partition("|")
    assert ps1 == FSDK_PROMPT
    assert "__bluefin_prompt" not in prompt_command


def test_prompt_keeps_an_existing_prompt_command() -> None:
    shell = shutil.which("bash")
    assert shell
    result = subprocess.run(
        [shell, "--norc", "--noprofile", "-i", "-c", f"PROMPT_COMMAND=earlier; . {PROMPT}; declare -p PROMPT_COMMAND"],
        env={"TERM": "xterm"}, capture_output=True, text=True, check=True,
    )
    assert '[0]="earlier"' in result.stdout and '"__bluefin_prompt"' in result.stdout
