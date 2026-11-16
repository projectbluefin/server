"""A failed console install leaves the machine up with its error readable.

sysinstall erases the chosen disk before it writes, so a failed install leaves
the target blank (projectbluefin/server#308). Upstream's
systemd-sysinstall.service halts the machine when sysinstall fails
(FailureAction=halt), and the installer's journal, which lives only in RAM,
goes with it.

The console stays muted, so nothing pushes sysinstall's error off the monitor.
sysinstall runs with --mute-console=yes, as upstream's unit does, and
bluefin-installer-mute-console.service, pulled in by the installer's prompts,
keeps kernel messages, such as disk I/O errors, off the console until
shutdown, the only point at which it is un-muted; they still reach the
journal. When sysinstall exits, its own mute hands PID 1's status output back
to the installer command line's systemd.show_status=error, so failed units are
still reported. sysinstall's own output, its error included, goes to the
console either way.

That a successful install still reboots on its own, and the installer command
line's quiet settings, are pinned in test_usb_installer_prompts.py.
"""


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


def test_sysinstall_mutes_console_during_interactive_prompts():
    [argv] = SystemdFile(DROPIN).commands()
    assert argv[0] == "systemd-sysinstall"
    assert "--mute-console=yes" in argv


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
    assert "--definitions=/run/bluefin/installer/bluefin/repart.d" in words
