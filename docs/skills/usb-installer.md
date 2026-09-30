---
name: usb-installer
description: The offline USB installer bluefin-server-installer_<ver>.raw. Load when working on the installer image, its systemd-sysinstall drop-in, unattended installs via systemd.unit-dropin credentials, or install-time provisioning from the ESP.
metadata:
  type: reference
  status: stable
  last_updated: "2026-09-29"
  context7-sources:
    - /systemd/systemd
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
initrd masks `systemd-networkd-wait-online`, as the disk UKI already does.

`run-bluefin-installer.mount` mounts the stick's ESP (`bluefin-installer`) at
`/run/bluefin/installer` (with `fmask=0133,dmask=0022`, so systemd-repart does
not warn about executable definition files). The
`systemd-sysinstall.service.d/10-bluefin-installer.conf` drop-in passes
`--definitions=/run/bluefin/installer/bluefin/repart.d` and
`--kernel=${BLUEFIN_INSTALL_KERNEL}` (the disk UKI, named by the installer
UKI's `systemd.setenv=`), `--erase=yes`, and `--reboot=no` with
`SuccessAction=reboot`. The disk UKI sits outside `EFI/Linux` on the stick
so systemd-boot never offers it there.

## Using the installer

This is stock `systemd-sysinstall` (systemd-sysinstall(8)); Bluefin adds no
installer UI of its own.

1. Boot the stick. The installer UKI sets the `firstboot.keymap` credential
   (`us`), so `systemd-firstboot` asks nothing, and the screen goes straight to
   **Operating System Installer**.
2. **Target disk.** sysinstall lists every disk it can install to as a
   numbered menu, labelled with its `/dev/disk/by-id/` name (model and serial,
   which is how you tell disks apart). The USB stick itself is never listed.
   The input line comes pre-filled (upstream v261 `prompt_loop` preselect):
   - **One disk:** its name is already filled in. Press **Enter**.
   - **Several disks:** the line holds the names' common prefix (for example
     `/dev/disk/by-id/nvme-`). Press **Ctrl-U** to clear it, type the
     **number** in front of the disk, and press Enter. Typing the number
     without clearing appends it to the prefix and is rejected as
     `Invalid input …`.
   Upstream v261 has no arrow-key menu; the number is the selector.
3. **Summary.** The chosen disk is always erased (`--erase=yes`), and the
   install is registered in the firmware boot menu (`--variables=yes`). Type
   `yes` to begin. This is the only confirmation.
4. sysinstall installs, and the machine **reboots by itself** when it
   succeeds. Remove the stick when the screen goes blank.
5. **First boot of the installed disk** asks, on the monitor (tty1), for a new
   **root password**, then asks again to confirm. It shows what you type unless
   you press **Tab** first. Do not leave it empty: an empty answer skips the
   prompt and root stays locked. Then log in as `root` with it.

Only two answers cancel: an empty answer at either prompt, and `no` at the
confirmation (`Installation not confirmed, cancelling.`). Anything else
upstream does not accept — a typo, an out-of-range number — is rejected with
`Invalid input …` and the same prompt is asked again, so a mistyped answer
never halts the machine. After a cancel or a real install failure, upstream's
`FailureAction=halt` halts the machine — it stops at `System halted` with the
message still on screen, but does not power off. Power-cycle and boot the stick
again to retry.

The installed disk is identical to one a diskless node installs: stock
`systemd-sysinstall` with the layout from `files/os/repart.d/` (see
[ddi-installer.md](ddi-installer.md), "Installing to disk").

## Unattended installs

`systemd-sysinstall` is interactive on `/dev/console`. To make an install
unattended, pass a `systemd.unit-dropin.systemd-sysinstall.service` system
credential (SMBIOS type 11 or QEMU fw_cfg). Plaintext `.cred` files in the
stick's `/loader/credentials/` are not applied: a KubeVirt run with one there
still stopped at the disk prompt. It lands as `50-credential.conf`,
after the image's `10-bluefin-installer.conf`, and re-runs that drop-in's
`ExecStart=` with the target disk and `--confirm=no` appended (the drop-in
already passes `--erase=yes --variables=yes`), plus `StandardInput=null` so any
leftover prompt fails instead of hanging. `scripts/dogfood-installer.sh` drives
exactly this path in QEMU and is the reference for the drop-in contents.

## First-boot prompts

Root ships locked as `!unprovisioned`, which `systemd-firstboot` reads as
"root not configured yet"; upstream's `--prompt-root-password` would block
every headless boot (netboot, Booty installs) and the installer's console on
a password prompt. The
`systemd-firstboot.service.d/10-bluefin-no-root-prompt.conf` drop-in removes
that prompt from `systemd-firstboot.service`.

A disk installed from the stick needs a way in, so the installer's drop-in
passes `--set-credential=bluefin.prompt-root-password:1` to sysinstall, which
stores it next to the installed UKI. On that disk's first boot
`bluefin-root-password-prompt.service` (`ConditionCredential=` on it, and
`ConditionFirstBoot=yes`) runs stock `systemd-firstboot --prompt-root-password`
on tty1, the monitor (the disk UKI's `/dev/console` is the serial port).
Nodes installed any other way never get the credential and never prompt. A
`passwd.hashed-password.root` / `passwd.plaintext-password.root` credential
sets the password instead of the prompt, as `scripts/dogfood-installer.sh`
does for the unattended test. See
[tpm2-credential-sealing.md](tpm2-credential-sealing.md).

## Credentials and the ESP

The installer needs no login: `systemd-sysinstall` runs on the console.
sysinstall stores a few system credentials next to the installed UKI (`extra`
lines in the boot entry): `firstboot.locale`, `firstboot.keymap`,
`firstboot.timezone`, and `bluefin.prompt-root-password`.

Anything else (users, SSH keys, sudoers, hostname, network) goes in the
stick's own `/loader/credentials/`: the stick's ESP definition copies that
directory onto the installed disk's ESP (`CopyFiles=`), and systemd-stub hands
it to **every** boot of the installed system. The installer's own boot sees
the same credentials. Credentials from an ESP land in
`/run/credentials/@encrypted` and must be encrypted (`import-creds.c`);
plaintext files are ignored. `systemd-creds encrypt --with-key=null` works
with Secure Boot off; with Secure Boot on, null-key credentials are refused.
See [tpm2-credential-sealing.md](tpm2-credential-sealing.md) for the
credential names.

### Developer mode: an admin user with SSH and passwordless sudo

For a node that agents manage over SSH, after writing the stick (Secure Boot
off on the target):

```bash
user=jorge; uid=1000; key="$(cat ~/.ssh/*.pub)"
# encrypting goes through io.systemd.Credentials, which needs privileges
enc() { sudo systemd-creds encrypt --with-key=null --name="$1" - "$2"; }
# an explicit UID: systemd-sysusers allocates from the system range (<1000)
# for "-", which would make the admin user a system account
printf 'u %s %s "%s" /home/%s /bin/bash\nm %s wheel\n' "$user" "$uid" "$user" "$user" "$user" \
  | enc sysusers.extra sysusers.extra.cred
printf 'd /home/%s 0700 %s %s -\nd /home/%s/.ssh 0700 %s %s -\nf+~ /home/%s/.ssh/authorized_keys 0600 %s %s - %s\nf+~ /etc/sudoers.d/50-%s 0440 root root - %s\n' \
  "$user" "$user" "$user" "$user" "$user" "$user" "$user" "$user" "$user" "$(printf '%s\n' "$key" | base64 -w0)" \
  "$user" "$(printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "$user" | base64 -w0)" \
  | enc tmpfiles.extra tmpfiles.extra.cred
# ssh.listen is read by systemd-ssh-generator, which only takes the binary
# form (v261 read_credential_with_decryption() does not unbase64); services
# only take the base64 form that systemd-creds writes.
printf 22 | enc ssh.listen - | base64 -d > ssh.listen.cred
# "*": no password login, but not locked like sysusers' default "!*", which
# sshd (UsePAM no) refuses even for keys
printf '*' | enc "passwd.hashed-password.$user" "passwd.hashed-password.$user.cred"
printf '!*' | enc passwd.hashed-password.root passwd.hashed-password.root.cred
# copy the five .cred files into /loader/credentials/ on the stick's
# "bluefin-installer" partition
```

`passwd.hashed-password.root` answers the first-boot root password prompt
(root stays locked; the admin user has sudo), so the node boots straight to
SSH on port 22 with no one at the console. `passwd.hashed-password.<user>`
reaches systemd-sysusers through the image's
`systemd-sysusers.service.d/10-bluefin-user-credentials.conf` (upstream imports
root's only).

`--with-key=null` is obfuscation, not encryption: the key is public, and the
stick's `/loader/credentials/` is copied onto every disk it installs, on an
unencrypted vfat ESP. The recipe above is safe because nothing in it is a
secret — `*` and `!*` are password *fields*, not passwords. Do not add a
`passwd.plaintext-password.<user>` credential (or a crackable `crypt(5)`
hash) this way; seal those with `--with-key=tpm2` per node instead, which
also means Secure Boot can stay on. See
[tpm2-credential-sealing.md](tpm2-credential-sealing.md).

## Secure Boot

The stick's systemd-boot and UKIs are signed with the project DB key. On bare
metal put the firmware into Setup Mode and pick the enrollment entry in the
systemd-boot menu (`secure-boot-enroll if-safe` only auto-enrolls in VMs), or
turn Secure Boot off.

## See also

- [ddi-installer.md](ddi-installer.md) — boot, install, and update architecture.
- [ddi-installer-build.md](ddi-installer-build.md) — build and dogfood
  (`just dogfood-installer`).
- [tpm2-credential-sealing.md](tpm2-credential-sealing.md) — first-boot
  credentials and ESP credential files.
- [secure-boot-keys.md](secure-boot-keys.md) — the keys that sign the stick.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (Installer).
