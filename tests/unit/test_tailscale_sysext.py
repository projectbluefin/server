"""Contract for the Tailscale sysext's unit rewrite in elements/runtimes/tailscale-bin.bst."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ELEMENT = ROOT / "elements" / "runtimes" / "tailscale-bin.bst"

IMAGE_DEFAULTS = "/usr/share/bluefin/tailscale/tailscaled.defaults"
OPERATOR_FILE = "/etc/default/tailscaled"


def install_commands() -> str:
    return "\n".join(yaml.safe_load(ELEMENT.read_text(encoding="utf-8"))["config"]["install-commands"])


def test_operator_environment_file_is_read_after_the_image_defaults():
    # systemd.exec(5): when several EnvironmentFile= lines set the same variable,
    # the later file wins. The image's defaults set PORT and FLAGS, so they must
    # come first or /etc/default/tailscaled could never override them.
    text = install_commands()
    replacement = re.search(r"EnvironmentFile=/etc/default/tailscaled\|(?P<new>[^|]*)\|", text)
    assert replacement, "the unit's EnvironmentFile= line is rewritten"
    lines = replacement["new"].split("\\n")
    assert lines == [f"EnvironmentFile=-{IMAGE_DEFAULTS}", f"EnvironmentFile=-{OPERATOR_FILE}"]


def test_both_environment_files_are_optional():
    text = install_commands()
    for path in (IMAGE_DEFAULTS, OPERATOR_FILE):
        assert f"EnvironmentFile=-{path}" in text, f"{path} must not fail the unit when absent"


def test_image_defaults_are_installed_where_the_unit_reads_them():
    text = install_commands()
    assert re.search(r'install -m 0644 dist/systemd/tailscaled\.defaults "\$\{defaultdir\}/tailscaled\.defaults"', text)
    assert 'defaultdir="%{install-root}%{datadir}/bluefin/tailscale"' in text
