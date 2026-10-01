"""A failed console install leaves the machine up with its error readable.

sysinstall erases the chosen disk before it writes, so a failed install leaves
the target blank (projectbluefin/server#308). Upstream's
systemd-sysinstall.service halts the machine when sysinstall fails
(FailureAction=halt), and the installer's journal, which lives only in RAM,
goes with it. Upstream also passes --mute-console=yes, which keeps kernel and
service-manager messages, such as disk I/O errors, off the console while
sysinstall runs; sysinstall's own output goes to the console either way.

That a successful install still reboots on its own is pinned in
test_usb_installer_prompts.py.
"""

from __future__ import annotations
import re
import shlex

from pathlib import Path

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
DROPIN = (
    ROOT
    / "files"
    / "os"
    / "systemd"
    / "system"
    / "systemd-sysinstall.service.d"
    / "10-bluefin-installer.conf"
)


def test_a_failed_install_leaves_the_machine_up():
    # Every other action ends what the operator is looking at: halt*, poweroff*
    # and kexec* stop the machine, reboot* and soft-reboot* start the stick
    # over, and exit* ends PID 1.
    assert SystemdFile(DROPIN).value("Unit", "FailureAction") == "none"


def test_kernel_and_service_manager_messages_reach_the_console():
    [argv] = SystemdFile(DROPIN).commands()
    assert argv[0] == "systemd-sysinstall"
    assert not [word for word in argv if word.startswith("--mute-console")]


def test_the_dropin_replaces_upstreams_command(tmp_path):
    # Without the empty ExecStart= first, upstream's command would be kept too.
    upstream = tmp_path / "systemd-sysinstall.service"
    upstream.write_text(
        "[Service]\nExecStart=systemd-sysinstall --mute-console=yes\n", encoding="utf-8"
    )
    assert SystemdFile(upstream, DROPIN).commands() == SystemdFile(DROPIN).commands()


def test_the_disk_uki_and_layout_still_come_from_the_stick():
    [line] = SystemdFile(DROPIN).values("Service", "ExecStart")
    words = shlex.split(line)
    assert "--kernel=${BLUEFIN_INSTALL_KERNEL}" in words
    assert "--definitions=${BLUEFIN_INSTALL_REPART}" in words
    boot = (ROOT / "elements" / "oci" / "bluefin-server-boot.bst").read_text()
    assignments = re.findall(r"BLUEFIN_INSTALL_REPART=([^\s]+)", boot)
    assert assignments
    assert all(value.startswith("/run/bluefin/installer/") for value in assignments)
