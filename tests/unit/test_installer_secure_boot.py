"""The USB installer checks Secure Boot before it erases anything (#309).

bluefin-installer-secure-boot.service decides whether systemd-sysinstall may
run; its decision logic is tested in bluefin-installer-secure-boot_test.bats.
This pins how it is wired: sysinstall and the Homelab entries' prompt cannot
start without it, and it sees the credentials that mark an unattended install
or allow one without Secure Boot. That it asks on the monitor is pinned with
the installer's other screens in test_installer_console_path.py.
"""


from pathlib import Path

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "files" / "os" / "creds" / "systemd" / "system"
UNIT = UNITS / "bluefin-installer-secure-boot.service"
HOMELAB = UNITS / "bluefin-homelab-install.service"
SCRIPT = ROOT / "files" / "os" / "libexec" / "bluefin-installer-secure-boot"
DROPIN = ROOT / "files" / "os" / "systemd" / "system" / "systemd-sysinstall.service.d" / "10-bluefin-installer.conf"
CREDS_ELEMENT = ROOT / "elements" / "bluefin-server" / "os-creds-prov.bst"
IMAGE = ROOT / "elements" / "oci" / "bluefin-server-image.bst"
NAME = "bluefin-installer-secure-boot.service"


def test_sysinstall_cannot_start_without_the_check():
    dropin = SystemdFile(DROPIN)
    # Requires= + After=: a failed or cancelled check fails sysinstall's start
    # job, so it never runs; Wants= would start it anyway.
    assert NAME in dropin.words("Unit", "Requires")
    assert NAME in dropin.words("Unit", "After")


def test_homelab_entries_go_through_the_same_check_before_their_prompt():
    homelab = SystemdFile(HOMELAB)
    assert NAME in homelab.words("Unit", "After")
    # Skipped, not failed, when the check did not pass: no prompt, and no
    # "Dependency failed" line for it on the default entry.
    assert homelab.commands("ExecCondition") == [["/usr/bin/systemctl", "is-active", "--quiet", NAME]]
    assert NAME not in homelab.words("Unit", "Requires")
    assert "bluefin-homelab-install.service" in SystemdFile(UNIT).words("Unit", "Before")


def test_the_check_runs_once_before_sysinstall():
    unit = SystemdFile(UNIT)
    assert "systemd-sysinstall.service" in unit.words("Unit", "Before")
    assert unit.value("Service", "Type") == "oneshot"
    assert unit.value("Service", "RemainAfterExit") == "yes"
    assert unit.value("Service", "ExecStart") == "/usr/libexec/bluefin-installer-secure-boot"
    assert "/run/bluefin/installer" in unit.words("Unit", "RequiresMountsFor")


def test_the_check_sees_the_unattended_and_the_allow_credentials():
    imported = SystemdFile(UNIT).values("Service", "ImportCredential")
    assert "bluefin.install-allow-insecure-boot" in imported
    # The unattended path's drop-in credential, with or without a ~suffix.
    assert "systemd.unit-dropin.systemd-sysinstall.service*" in imported


def test_the_helper_is_installed():
    text = CREDS_ELEMENT.read_text(encoding="utf-8")
    assert "libexec-src/bluefin-installer-secure-boot" in text
    assert '"%{install-root}/usr/libexec/bluefin-installer-secure-boot"' in text


def test_the_stick_carries_what_the_enrollment_choice_relies_on():
    # systemd-boot names the entry for loader/keys/<dir> secure-boot-keys-<dir>
    # (v261 secure_boot_discover_keys()); the helper sets it as the one-shot
    # entry. "if-safe" enrolls by itself in VMs only, so on bare metal the
    # entry, and with it the helper's choice, is how keys get enrolled.
    image = IMAGE.read_text(encoding="utf-8")
    assert 'install -Dm644 -t "${esp}/loader/keys/auto" /boot-out/efi-keys/*.auth' in image
    assert "secure-boot-enroll if-safe" in image
    script = SCRIPT.read_text(encoding="utf-8")
    assert "ENROLL_ENTRY=secure-boot-keys-auto" in script
    assert ':-/run/bluefin/installer/loader/keys/auto}' in script


def test_the_check_mutes_noisy_console_messages():
    unit = SystemdFile(UNIT)
    assert "bluefin-installer-mute-console.service" in unit.words("Unit", "Wants")
    assert "bluefin-installer-mute-console.service" in unit.words("Unit", "After")
    mute = SystemdFile(UNITS / "bluefin-installer-mute-console.service")
    assert mute.value("Service", "Type") == "notify"
    assert mute.value("Service", "ExecStart") == "/usr/bin/systemd-mute-console"
    assert "shutdown.target" in mute.words("Unit", "Conflicts")
    assert "shutdown.target" in mute.words("Unit", "Before")
