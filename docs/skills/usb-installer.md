---
name: usb-installer
description: The offline USB installer bluefin-server-installer_<ver>.raw. Load when working on the installer image, its systemd-sysinstall drop-in, unattended installs via systemd.unit-dropin credentials, or install-time provisioning from the ESP.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-16"
  context7-sources:
    - /systemd/systemd
    - /openssh/openssh-portable
---
# Offline USB Installer

`bluefin-server-installer_<ver>.raw` is the offline USB installer in the
release set: the same usr and usr-verity images as the OS DDI (labelled
`bluefin-installer-usr` / `bluefin-installer-usr-verity`) plus an ESP with
signed systemd-boot, the installer UKI, the Secure Boot key enrollment
payloads, and the disk UKI + install-time `repart.d` under `bluefin/`. Write
it to a USB stick to install without a network:

```bash
sudo dd if=bluefin-server-installer_<ver>.raw of=/dev/<usb> bs=4M conv=fsync status=progress
```

## Boot flow

```text
firmware -> systemd-boot -> bluefin-server-installer_<ver>.efi
  -> /usr from the stick's bluefin-installer-usr partition (dm-verity, usrhash=)
  -> tmpfs root, systemd.unit=system-install.target
  -> systemd-sysinstall.service on the monitor (/dev/console = tty0)
```

The installer UKI finds its /usr by partition label, not by the
usrhash-derived UUIDs. Those UUIDs belong to installed usr slots, so an
existing Bluefin install (including the disk being overwritten) is never
opened as the installer's /usr, and an installed node booted with the stick
still plugged in never opens the stick's usr. The installer is offline: its
kernel command line masks `systemd-networkd-wait-online` in both initrd and
userspace (`rd.systemd.mask=` and `systemd.mask=`), avoiding offline waits
or wait-online failure messages during interactive prompts.

`90-bluefin-installer-forget-partitions.rules` (udev, only when the kernel
command line has `systemd.unit=system-install.target`) runs
`partx --delete` on every partition device except the stick's
(`bluefin-installer*`) until sysinstall starts: its drop-in runs
`udevadm settle`, then touches `/run/bluefin-sysinstall/started`, which the
rule skips on. Nothing on any disk changes;
the kernel just forgets the partitions until the next boot. systemd-repart
v261 needs that to erase a disk that is not empty: it keeps the kernel's
partition devices of what the disk held, and adding the new ESP's partition
device, or rereading the new table, fails with `Device or resource busy` after
the disk was already wiped (#359). Drop the rule once FSDK's systemd-repart
removes them itself.

`run-bluefin-installer.mount` mounts the stick's ESP (`bluefin-installer`) at
`/run/bluefin/installer` (with `fmask=0133,dmask=0022`, so systemd-repart does
not warn about executable definition files). The
`systemd-sysinstall.service.d/10-bluefin-installer.conf` drop-in passes
`--definitions=/run/bluefin/installer/bluefin/repart.d` and
`--kernel=${BLUEFIN_INSTALL_KERNEL}` (the disk UKI, named by the installer
UKI's `systemd.setenv=`), `--erase=yes`, and `--reboot=no` with
`OnSuccess=bluefin-installer-done.service` (the "installed" screen, which
restarts the machine: its `SuccessAction=reboot` and `FailureAction=reboot`),
plus `RemainAfterExit=no` so that still fires once
upstream's unit is `Type=oneshot` with `RemainAfterExit=yes` (systemd v262).
It also sets `FailureAction=none` and retains upstream's
`--mute-console=yes`; what that changes is described after the install steps
below. The disk UKI sits outside `EFI/Linux` on the stick so systemd-boot
never offers it there.

## Using the installer

This is stock `systemd-sysinstall` (systemd-sysinstall(8)); Bluefin adds no
installer UI of its own beyond small console questions ordered around it:
Secure Boot, Home Server owner/options (or the preserved Homelab node join
question), the target disk, and the installed screen.

1. Boot the stick. **Bluefin Server <ver>** (minimal) is first and selected after 3 seconds.
   **Bluefin Home Server** is an explicit opt-in; both Homelab entries remain.
   All are profiles of one signed UKI; only Home adds `bluefin.install-home-server=1`.
   Home's `.osrel` sets `PRETTY_NAME`; `.profile` uses `ID=home-server` without `TITLE`.
   `firstboot.keymap=us` avoids a keymap prompt. Secure Boot is checked first.
2. **Owner/options.** Choose a nonroot owner; Enter defers creation to first boot.
   Accounts/keys are private, never baked in. Homebrew is included; Podman defaults
   **on**, Docker and Homelab/KubeStellar **off**. Docker clients use Podman's API
   unless Docker is selected. Federation stays off. `q`/EOF cancels; minimal skips this.
3. **Target disk.** `bluefin-installer-disk.service` lists every disk
   sysinstall can install to, numbered, with its size, model and
   `/dev/disk/by-id/` name (model and serial), for example:

   ```text
   Install Bluefin Server 26.10.1 to which disk?
   The installer erases the chosen disk completely; it asks once more before it starts.

     1) 931.5G   Samsung SSD 980 PRO 1TB        nvme-Samsung_SSD_980_PRO_1TB_S5GXNX0R123456
     2) 3.6T     WDC WD40EFRX-68N32N0           ata-WDC_WD40EFRX-68N32N0_WD-WCC7K0ABCDEF

   Disk number (1-2), or q to cancel:
   ```

   Type the number and press Enter; with one disk, Enter alone takes it.
   The USB stick itself is never listed: the list is systemd-repart's
   `io.systemd.Repart.ListCandidateDevices` with `ignoreRoot`, the call
   sysinstall makes for its own menu. Sizes are 1024-based, as systemd
   prints them. The chosen disk becomes sysinstall's device argument
   (`BLUEFIN_INSTALL_TARGET`, in
   `/run/bluefin-installer-disk/sysinstall.env`), so sysinstall does not ask
   for it again; it still checks that the install fits. Upstream v261's own
   question shows one by-id name per disk and no size, and pre-fills the
   names' common prefix, so picking one of several disks needed Ctrl-U first.
4. **Summary.** The chosen disk is always erased (`--erase=yes`), whatever
   it holds (an earlier install, another OS), and the
   install is registered in the firmware boot menu (`--variables=yes`). Type
   `yes` to begin. This is the only confirmation.
5. sysinstall installs. When it succeeds, `bluefin-installer-done.service`
   shows:

   ```text
   Bluefin Home Server is installed.

   The machine restarts into it in 15 seconds (Enter: now).
   Remove the USB stick when the screen goes blank.

   On first boot, create the nonroot owner unless it was privately provisioned.
   Log in as that owner; Homebrew is ready in its system container.
   SSH accepts public keys only. The root account stays locked.
   ```

   and the machine **restarts by itself**. The stick stays in until the
   screen is blank: the installer's /usr is on it until then. Left in, the
   firmware normally starts the new install anyway, which sysinstall put
   first in its boot order.
6. **First boot of Home Server** creates the private or console owner, seeds the
   writable prefix and starts nspawn before login. Brew tools run inside it.
   SSH is key-only; `sshd`'s `SetEnv PATH` exposes root-owned shims even to non-login
   remote commands. Root stays locked. **Advanced minimal and Homelab** preserve
   the tty1 root-password prompt, answered by a `passwd.*.root` credential when supplied.
7. **The login banner** shows the hostname, addresses and update status
   (see [Console banner](#console-banner)).

Home Server owner/options accept `q` to cancel; the disk question also
accepts `q`, and sysinstall's confirmation cancels on empty or `no`.
A wrong disk number is asked again, and anything else upstream does not accept
is rejected with `Invalid input …` and the same prompt asked again, so a
mistyped answer never ends the install. A cancelled disk question fails its
unit, so sysinstall never starts and no disk is touched.

After cancellation or failure, `FailureAction=none` keeps the machine up and
sysinstall's own error on the monitor. The RAM journal survives until power-off:
`journalctl -b -k` and `journalctl -u systemd-sysinstall` (over SSH with the developer-mode credentials from
[usb-installer-provisioning.md](usb-installer-provisioning.md)). The long-lived mute starts after sysctl and
firstboot, so neither restores printk under a prompt. Together with
`--mute-console=yes` and `quiet loglevel=4 systemd.show_status=error`, it keeps kernel and PID 1 noise off the prompts.
The Secure Boot warning, disk chooser and Homelab join prompt clear earlier
output and scrollback before drawing, never on exit, preserving cancellation
reasons. A failure after erasure leaves the disk blank
([#308](https://github.com/projectbluefin/server/issues/308)); boot the stick again to retry.

The `DOGFOOD_CONSOLE_*` runs in [ddi-installer-dogfood.md](ddi-installer-dogfood.md) check this in QEMU.

All profiles use stock `systemd-sysinstall` and the same discoverable
partition layout from `files/os/repart.d/` ([ddi-installer.md](ddi-installer.md)).
Home Server and Homelab share `bluefin/extensions/` on the stick. Both ESP sizes
are payload-bounded (25% slack plus reserve); `check-image` rejects installers ≥4 GiB.
First boot imports selected features; `/var/lib/machines` receives the Brew image.
Installed nodes update from official releases; the login banner shows version and
update health ([systemd-sysupdate-verification.md](systemd-sysupdate-verification.md)).

## Console banner

The console's login banner (`/usr/lib/issue.d/30-bluefin.issue`, shown by
agetty on tty1 and the serial console) uses agetty's escapes (util-linux
2.42):

```text
Bluefin Server node1 (tty1)
enp1s0: 192.0.2.10 2001:db8::10
mDNS: node1.local
SSH, when enabled (keys only): ssh root@192.0.2.10
Console: log in as root once root is set, at the first boot after a USB install or by credential; until then root is locked.
Node access: https://github.com/projectbluefin/server/blob/main/docs/skills/tpm2-credential-sealing.md#node-access
```

`\n` is the hostname (announced as `\n.local`; see "Node name, mDNS and
prompt" in [tpm2-credential-sealing.md](tpm2-credential-sealing.md)),
`\a` the usable addresses of every interface, `\4`
the best IPv4 address; agetty reprints the banner when an address changes,
so a DHCP lease that arrives after the prompt still shows. The update lines
follow ([sysupdate-operations.md](sysupdate-operations.md)),
and on a Homelab control plane the join passphrase and the KubeStellar
Console's address and login ([homelab-profile.md](homelab-profile.md)).

## Homelab entries and provisioning

The Homelab entries, Home Server profile credentials, unattended installs,
first-boot prompts, ESP credential files and developer mode live in
[usb-installer-provisioning.md](usb-installer-provisioning.md).

## Secure Boot

Secure Boot is required. The stick's systemd-boot and UKIs, and every disk it
installs, are signed with the project DB key; without Secure Boot nothing
checks them, nor the `usrhash=` in the UKI that pins the verified /usr.

### Firmware steps

1. In the firmware setup (usually F2, Del, F10 or Esc at power-on), under
   Secure Boot, put the firmware into **Setup Mode** ("Reset to Setup Mode",
   "Clear Secure Boot keys" or "Delete all keys"; some firmware also wants
   Secure Boot set to Enabled or to "Custom" mode). Save and exit.
2. Boot the stick (pick it in the firmware's boot menu if needed).
3. The installer finds the firmware in Setup Mode and offers **2) Enroll the
   Bluefin Server keys and restart**. systemd-boot writes the stick's
   `loader/keys/auto/` keys (PK, KEK, db) and restarts; on bare metal it
   first counts down 15 seconds ("press any key to abort": let it run). The
   machine comes back with Secure Boot on; boot the stick again if the
   firmware does not, and install. Instead of the installer's choice, the
   systemd-boot menu entry **Enroll Secure Boot keys: auto** does the same.

The firmware then trusts only the Bluefin Server keys. Add-in cards whose
firmware (option ROM) is signed by Microsoft, such as some graphics cards,
may then not initialise at boot; on such machines keep a way back (another
graphics output, or the firmware's "restore factory keys").
`secure-boot-enroll if-safe` enrolls by itself only in VMs.

### The installer's check

`bluefin-installer-secure-boot.service` runs before `systemd-sysinstall`
and before the Homelab entries' prompt; both `Requires=` it, so when it
fails neither starts and no disk is touched. It pulls in
`bluefin-installer-mute-console.service` (`systemd-mute-console(1)`) so
kernel and service-manager log messages do not land over its menus and push
them off the screen. It reads `SecureBoot`,
`SetupMode` and `AuditMode` from efivarfs and decides that Secure Boot is
on **with our keys** when the firmware's `db` variable holds, byte for byte,
an X.509 certificate from the stick's `loader/keys/auto/db.auth`:

| Firmware | The installer |
|---|---|
| Secure Boot on, our certificate in `db` | Continues without a word. |
| Setup Mode | Explains, then offers Cancel (default), **Enroll the Bluefin Server keys and restart** (`bootctl set-oneshot secure-boot-keys-auto`, the systemd-boot entry above, then a restart) or Continue without Secure Boot. |
| Secure Boot off, our keys enrolled | Warns: set Secure Boot to Enabled in the firmware. |
| Other keys (for example Microsoft's only), Secure Boot on or off | Warns: put the firmware into Setup Mode and boot the stick again to enroll. |
| No Secure Boot variables, or no `db.auth` on the stick | Warns that the state cannot be checked. |

The warning says what is wrong, why it matters (without Secure Boot anyone
who can write to the disk can change what boots, and TPM-sealed secrets lose
their protection) and what to change in the firmware. It then offers
**1) Cancel** (the default: Enter, anything not listed, or no answer within
10 minutes) or **Continue without Secure Boot**, which also needs `yes`
typed. Cancelling leaves the installer up with the reason on the monitor
(and in the journal); change the firmware and boot the stick again.
Unattended installs never ask: see "Unattended installs" in
[usb-installer-provisioning.md](usb-installer-provisioning.md).

## See also

- [usb-installer-provisioning.md](usb-installer-provisioning.md) — Homelab entries, unattended installs, ESP credentials, developer mode.
- [ddi-installer.md](ddi-installer.md) — boot, install, and update architecture.
- [ddi-installer-dogfood.md](ddi-installer-dogfood.md) — dogfood procedure for the installer.
- [tpm2-credential-sealing.md](tpm2-credential-sealing.md) — first-boot
  credentials and ESP credential files.
- [secure-boot-keys.md](secure-boot-keys.md) — the keys that sign the stick.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (Installer).
