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
kernel command line masks `systemd-networkd-wait-online` in initrd and
userspace (`rd.systemd.mask=` and `systemd.mask=`).

`90-bluefin-installer-forget-partitions.rules` (udev, only when the kernel
command line has `systemd.unit=system-install.target`) runs `partx --delete`
on every partition device except the stick's (`bluefin-installer*`) until
sysinstall starts: its drop-in runs `udevadm settle`, then touches
`/run/bluefin-sysinstall/started`, which the rule skips on. Nothing on any
disk changes; the kernel just forgets the partitions until the next boot.
systemd-repart v261 needs that to erase a non-empty disk: it keeps the
kernel's partition devices of what the disk held, so adding the new ESP's
partition device or rereading the new table fails with `Device or resource
busy` after the disk was already wiped (#359). Drop the rule once FSDK's
systemd-repart removes them itself.

`run-bluefin-installer.mount` mounts the stick's ESP (`bluefin-installer`)
at `/run/bluefin/installer` (with `fmask=0133,dmask=0022`, so systemd-repart
does not warn about executable definition files). The
`systemd-sysinstall.service.d/10-bluefin-installer.conf` drop-in passes
`--definitions=/run/bluefin/installer/bluefin/repart.d` and
`--kernel=${BLUEFIN_INSTALL_KERNEL}` (the disk UKI, named by the installer
UKI's `systemd.setenv=`), `--erase=yes`, and `--reboot=no` with
`OnSuccess=bluefin-installer-done.service` (the "installed" screen, which
restarts the machine: its `SuccessAction=reboot` and `FailureAction=reboot`),
plus `RemainAfterExit=no` so that still fires once upstream's unit is
`Type=oneshot` with `RemainAfterExit=yes` (systemd v262). It also sets
`FailureAction=none` and retains upstream's `--mute-console=yes`; what that
changes is described after the install steps below. The disk UKI sits outside
`EFI/Linux` on the stick so systemd-boot never offers it there.

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
   Accounts/keys are private, never baked in. Homebrew is included; Podman
   defaults **on**, Docker and Homelab/KubeStellar **off**. Docker clients use
   Podman's API unless Docker is selected. Federation stays off. `q`/EOF
   cancels; minimal skips this.
3. **Target disk.** `bluefin-installer-disk.service` lists every disk
   sysinstall can install to, numbered, with its size, model and
   `/dev/disk/by-id/` name (model and serial):
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
   sysinstall makes for its own menu. Sizes are 1024-based, as systemd prints
   them. The chosen disk becomes sysinstall's device argument
   (`BLUEFIN_INSTALL_TARGET`, in `/run/bluefin-installer-disk/sysinstall.env`),
   so sysinstall does not ask for it again.
4. **Summary.** The chosen disk is always erased (`--erase=yes`), whatever it
   holds (an earlier install, another OS), and the install is registered in
   the firmware boot menu (`--variables=yes`). Type `yes` to begin — the only
   confirmation.
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
   screen is blank: the installer's /usr is on it until then.
6. **First boot of Home Server** creates the private or console owner, seeds
   the writable prefix and starts nspawn before login. Brew tools run inside
   it. SSH is key-only; `sshd`'s `SetEnv PATH` exposes root-owned shims even
   to non-login remote commands. Root stays locked. **Advanced minimal and
   Homelab** preserve the tty1 root-password prompt, answered by a
   `passwd.*.root` credential when supplied.
7. **The login banner** shows hostname, addresses and update status (see [Console banner](#console-banner)).

Home Server owner/options accept `q` to cancel; the disk question also
accepts `q`, and sysinstall's confirmation cancels on empty or `no`. A wrong
disk number is asked again, and anything else upstream does not accept is
rejected with `Invalid input …` and re-asked, so a mistyped answer never
ends the install. A cancelled disk question fails its unit, so sysinstall
never starts and no disk is touched.

After cancellation or failure, `FailureAction=none` keeps the machine up and
sysinstall's own error on the monitor. The RAM journal survives until
power-off: `journalctl -b -k` and `journalctl -u systemd-sysinstall` (over
SSH with the developer-mode credentials below). Together with
`--mute-console=yes` and `quiet loglevel=4 systemd.show_status=error`, the
mute keeps kernel and PID 1 noise off the prompts; it starts after sysctl and
firstboot, so neither restores printk under a prompt. The Secure Boot
warning, disk chooser and Homelab join prompt clear earlier output and
scrollback before drawing, never on exit, preserving cancellation reasons. A
failure after erasure leaves the disk blank
([#308](https://github.com/projectbluefin/server/issues/308)); boot the stick
again to retry; the `DOGFOOD_CONSOLE_*` runs in [ddi-installer-build.md](ddi-installer-build.md)
check this in QEMU.

All profiles use stock `systemd-sysinstall` and the same discoverable
partition layout from `files/os/repart.d/` ([ddi-installer.md](ddi-installer.md)).
Home Server and Homelab share `bluefin/extensions/` on the stick. Both ESP
sizes are payload-bounded (25% slack plus reserve); `check-image` rejects
installers ≥4 GiB. Installed nodes update from official releases; the login
banner shows version and update health ([systemd-sysupdate-verification.md](systemd-sysupdate-verification.md)).

## Console banner

The console's login banner (`/usr/lib/issue.d/30-bluefin.issue`, shown by
agetty on tty1 and the serial console) uses agetty's escapes (util-linux 2.42):

```text
Bluefin Server node1 (tty1)
enp1s0: 192.0.2.10 2001:db8::10
mDNS: node1.local
SSH, when enabled (keys only): ssh root@192.0.2.10
Console: log in as root once root is set, at the first boot after a USB install or by credential; until then root is locked.
Node access: https://github.com/projectbluefin/server/blob/main/docs/skills/tpm2-credential-sealing.md#node-access
```

`\n` is the hostname (announced as `\n.local`; see "Node name, mDNS and
prompt" in [tpm2-credential-sealing.md](tpm2-credential-sealing.md)), `\a`
the usable addresses of every interface, `\4` the best IPv4 address; agetty
reprints the banner when an address changes, so a DHCP lease that arrives
after the prompt still shows. The update lines follow ([systemd-sysupdate-verification.md](systemd-sysupdate-verification.md)),
and on a Homelab control plane the join passphrase and the KubeStellar
Console's address and login ([homelab-profile.md](homelab-profile.md)).

## Homelab entries

The preserved Homelab entries install the same OS onto the chosen disk, with
the same disk/confirmation prompts, and make it a homelab control plane or
node ([homelab-profile.md](homelab-profile.md)) without a network during the
install; they do not select Homebrew implicitly.

- They are profiles of the one signed installer UKI. Each adds
  `systemd.set_credential=bluefin.install-homelab:control-plane` (or `:node`)
  to the default entry's kernel command line, and nothing else; no secret is
  on a command line or in a UKI.
- `bluefin-homelab-install.service` (pulled in by the sysinstall drop-in,
  `ConditionCredential=bluefin.install-homelab`, so Home Server and advanced
  minimal skip it) writes `BLUEFIN_INSTALL_ARGS` into
  `/run/bluefin-homelab-install/sysinstall.env`. The sysinstall drop-in
  appends this independently from Home Server's
  `BLUEFIN_HOME_SERVER_INSTALL_ARGS`; empty variables add no arguments.
  - `--definitions=/run/bluefin/installer/bluefin/homelab/repart.d`, whose
    `10-esp.conf.d/50-bluefin-homelab.conf` adds a `CopyFiles=` of the stick's
    shared `bluefin/extensions/` and its `SHA256SUMS` to the installed ESP's
    `/bluefin/extensions/`. On first boot `bluefin-sysext-fetch.service`
    installs them from there and deletes the copy.
  - `--load-credential=ignition.config:/run/bluefin/installer/bluefin/homelab/homelab-<role>.bu`:
    the role's template, stored with the installed UKI like the other
    sysinstall credentials. To customise the install (SSH key, MetalLB pool,
    ...), edit `bluefin/homelab/homelab-<role>.bu` on the stick's
    `bluefin-installer` partition before booting it.
  - Node only: `--load-credential=bluefin-cluster.passphrase:...`. Before
    sysinstall starts, the node entry asks on the monitor for the join
    passphrase the control plane shows on its console; Enter alone leaves it
    to the stick's template. A `bluefin-cluster.passphrase` credential
    (SMBIOS) answers it unattended.
- systemd-sysinstall encrypts the credentials it stores with the TPM2 when
  there is one (else the null key), so the initrd carries libtss2 to unseal
  `ignition.config`. They stay with the installed UKI until the first OS
  update installs a new one; Ignition applies the template on every boot
  until then.

k0s is not offered here; use its templates ([homelab-profile.md](homelab-profile.md)).
`scripts/dogfood-homelab-installer.sh` (`just dogfood-homelab-installer`)
installs a control plane (with a TPM2) and then a node from the stick, with
the network off, and checks that they form a cluster.

## Home Server profile credentials

`bluefin-home-server-install.service` handles `bluefin.install-home-server=1`, writing private `BLUEFIN_HOME_SERVER_INSTALL_ARGS` separately from Homelab.

| Credential | Value / default |
|---|---|
| `bluefin.homebrew.profile` | `home-server` |
| `bluefin.homebrew.owner` | Nonroot name; absent interactively means first-boot creation |
| `bluefin.homebrew.podman` | Boolean, true by default |
| `bluefin.homebrew.docker` | Boolean, false by default |
| `bluefin.homebrew.cluster` | Boolean, false; canonical Homelab/KubeStellar, federation off |

Unattended USB installs require private owner and `passwd.hashed-password.<owner>` (`*` permits key-only accounts). Supply public keys through `ssh.authorized_keys.<owner>`: both preparation units import them and write the owner's `.ssh` (0700) and `authorized_keys` (0600) after dropping filesystem authority to that UID/GID. No key credential preserves existing keys. Snapshot sysusers/tmpfiles/password/key credentials privately: mounts are unit-private; sysinstall seals them to TPM when available. Never use public null-key credentials for secrets. Invalid owner/booleans fail before erasure.

The published profile also works outside USB. Its bootstrap, paired machine/integration assets, owner persistence and dispatch trust boundaries are documented in [system-containers.md](system-containers.md); runtime activation remains opt-in as described there.

Optional cluster composition retains canonical Homelab/add-on/Gateway configuration, removes only its sample OS-root account/key, and keeps Home root locked. The SSH owner and Console administrator are separate identities: no general sudo or admin kubeconfig copy. The local/serial banner provides `https://kubestellar.<HOMELAB_DOMAIN>` and the generated-once dedicated `admin` password from `kubestellar-console-login`, written only to private `/run/issue.d/51-kubestellar-console.issue` (0600), not the journal. HTTPS/DNS requirements and shared-admin limits remain in [homelab-profile.md](homelab-profile.md); per-owner enrollment/recovery is not implemented by this option.

## Unattended installs

`systemd-sysinstall` is interactive on `/dev/console`. To make an install
unattended, pass a `systemd.unit-dropin.systemd-sysinstall.service` system
credential (SMBIOS type 11 or QEMU fw_cfg). Plaintext `.cred` files in the
stick's `/loader/credentials/` are not applied: a KubeVirt run with one there
still stopped at the disk prompt. It lands as `50-credential.conf`, after the
image's `10-bluefin-installer.conf`, and re-runs that drop-in's `ExecStart=`
with the target disk and `--confirm=no` appended (the drop-in already passes
`--erase=yes --variables=yes`), plus `StandardInput=null` so any leftover
prompt fails instead of hanging. `scripts/dogfood-installer.sh` drives exactly
this path in QEMU and is the reference for the drop-in contents.

That credential is also what marks an install as unattended for the
[Secure Boot](#secure-boot) check, which then never asks: unless Secure Boot
is on with the Bluefin Server keys, it cancels (the reason is in the journal,
and no disk is touched) unless a `bluefin.install-allow-insecure-boot`
credential says `1`. `DOGFOOD_SECURE_BOOT=off scripts/dogfood-installer.sh`
checks both on firmware without Secure Boot.

## First-boot prompts

Root ships locked as `!unprovisioned`, which `systemd-firstboot` reads as
"root not configured yet"; upstream's `--prompt-root-password` would block
every headless boot (netboot, Booty installs) and the installer's console on
a password prompt. The
`systemd-firstboot.service.d/10-bluefin-no-root-prompt.conf` drop-in removes
that prompt from `systemd-firstboot.service`.

A disk installed using advanced minimal or Homelab needs a way in, so the
installer's drop-in passes `--set-credential=bluefin.prompt-root-password:1`
to sysinstall, which stores it next to the installed UKI. Home Server's
Ignition template masks that root prompt in favor of nonroot owner setup.
`bluefin-root-password-prompt.service` (`ConditionCredential=` on it, and
`ConditionFirstBoot=yes`) runs stock `systemd-firstboot --prompt-root-password`
on tty1, the monitor (the disk UKI's `/dev/console` is the serial port),
through `/usr/libexec/bluefin-root-password-prompt`, which asks again while
root has no password. It runs before `sysinit.target`, so the boot waits for
the answer. Nodes installed any other way never get the credential and never
prompt. A `passwd.hashed-password.root` / `passwd.plaintext-password.root`
credential sets the password instead of the prompt, applied as given (also
`!*`), as `scripts/dogfood-installer.sh` does for the unattended test. See
[tpm2-credential-sealing.md](tpm2-credential-sealing.md).


## Credentials and the ESP

The installer needs no login: `systemd-sysinstall` runs on the console.
sysinstall stores a few system credentials next to the installed UKI (`extra`
lines in the boot entry): `firstboot.locale`, `firstboot.keymap`,
`firstboot.timezone`, and `bluefin.prompt-root-password`.

Anything else (users, SSH keys, sudoers, hostname, network) goes in the
stick's own `/loader/credentials/`: the stick's ESP definition copies that
directory onto the installed disk's ESP (`CopyFiles=`), and systemd-stub hands
it to **every** boot of the installed system. ESP credentials land in
`/run/credentials/@encrypted`
and must be encrypted (`import-creds.c`); plaintext files are ignored.
`systemd-creds encrypt --with-key=null` works with Secure Boot off; with
Secure Boot on, null-key credentials are refused. See
[tpm2-credential-sealing.md](tpm2-credential-sealing.md) for the credential
names.

## Trust model: the stick's unsigned `bluefin/extensions/SHA256SUMS`

The stick's `bluefin/extensions/` directory (Homelab/Home sysexts copied onto
the installed ESP, then installed by `bluefin-sysext-fetch.service` on first
boot) carries its own `SHA256SUMS`, and that manifest is deliberately
**unsigned**: a signature would make the stick differ on every build. The
top-level signed `SHA256SUMS` covers the installer image as one file, not its
inner partitions, so on a written stick nothing authenticates those sysexts
beyond that checksum file. Whoever can write the stick, or the ESP's
`/bluefin/extensions/` it installs, can swap a sysext or edit the manifest,
and first boot installs the result: the same trust level as the stick and
disk themselves (maintainer-accepted; see the element comment in
`elements/oci/bluefin-server-image.bst`). Treat the stick like the disk: burn
it from a verified download, keep it in your hands, re-flash one that left them.

Related: attach **one** installer stick at a time. The installer UKI finds its
/usr by the partlabels `bluefin-installer-usr{,-verity}`; with two sticks
attached it can pick the other one, and a different version's `usrhash=` pin
then mismatches the verity partition and the installer reboot-loops. An
availability footgun, not a compromise: both partitions are dm-verity-sealed,
so nothing unsigned runs.

### Developer mode: an admin user with SSH and passwordless sudo

For a node that agents manage over SSH, after writing the stick (Secure Boot
off on the target, so the installer warns first: choose **Continue without
Secure Boot**):

```bash
user=jorge; uid=1000; key="$(cat ~/.ssh/*.pub)"
# encrypting goes through io.systemd.Credentials, which needs privileges
enc() { sudo systemd-creds encrypt --with-key=null --name="$1" - "$2"; }
# explicit UID: "-" would allocate from the system range (<1000)
printf 'u %s %s "%s" /home/%s /bin/bash\nm %s wheel\n' "$user" "$uid" "$user" "$user" "$user" \
  | enc sysusers.extra sysusers.extra.cred
printf 'd /home/%s 0700 %s %s -\nd /home/%s/.ssh 0700 %s %s -\nf+~ /home/%s/.ssh/authorized_keys 0600 %s %s - %s\nf+~ /etc/sudoers.d/50-%s 0440 root root - %s\n' \
  "$user" "$user" "$user" "$user" "$user" "$user" "$user" "$user" "$user" "$(printf '%s\n' "$key" | base64 -w0)" \
  "$user" "$(printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "$user" | base64 -w0)" \
  | enc tmpfiles.extra tmpfiles.extra.cred
# ssh.listen: systemd-ssh-generator takes the binary form only (v261 does
# not unbase64); services take the base64 form systemd-creds writes
printf 22 | enc ssh.listen - | base64 -d > ssh.listen.cred
# "*": no password login, but not locked like sysusers' default "!*", which
# sshd (UsePAM no) refuses even for keys
printf '*' | enc "passwd.hashed-password.$user" "passwd.hashed-password.$user.cred"
printf '!*' | enc passwd.hashed-password.root passwd.hashed-password.root.cred
# copy the five .cred files into /loader/credentials/ on the stick's ESP
```

`passwd.hashed-password.root` answers the first-boot root password prompt
(root stays locked; the admin user has sudo), so the node boots straight to
SSH on port 22 with no one at the console. Leave that file out to also get a
console login: the first boot then asks on the monitor for a root password,
as without developer mode, and waits for it before anything else (SSH
included) starts. `passwd.hashed-password.<user>` reaches systemd-sysusers
through the image's `systemd-sysusers.service.d/10-bluefin-user-credentials.conf`
(upstream imports root's only).

`--with-key=null` is obfuscation, not encryption: the key is public, and the
stick's `/loader/credentials/` is copied onto every disk it installs, on an
unencrypted vfat ESP. The recipe above is safe because nothing in it is a
secret: `*` and `!*` are password *fields*, not passwords. Do not add a
`passwd.plaintext-password.<user>` credential (or a crackable `crypt(5)` hash)
this way; seal those with `--with-key=tpm2` per node instead, which also means
Secure Boot can stay on. See [tpm2-credential-sealing.md](tpm2-credential-sealing.md).

### Burning a developer stick end to end

The homelab developer-stick sequence: newest release, verified, the recipe
above with a GitHub user's public keys, checked on the stick itself.

1. Fetch the newest release and verify it (the keyring is the one the image
   ships for sysupdate):

   ```bash
   tag=$(gh release view --repo projectbluefin/server --json tagName --jq .tagName)
   ver=${tag#v}; dir=/var/tmp/usbstick/$tag; mkdir -p "$dir" && cd "$dir"
   gh release download "$tag" --repo projectbluefin/server \
     --pattern "bluefin-server-installer_${ver}.raw" --pattern 'SHA256SUMS*'
   gh api repos/projectbluefin/server/contents/files/os/sysupdate-keys/import-pubring.gpg \
     --jq .content | base64 -d > pubring.gpg
   gpgv --keyring ./pubring.gpg SHA256SUMS.gpg SHA256SUMS
   sha256sum --check --ignore-missing SHA256SUMS
   ```

2. Take the keys from GitHub instead of `~/.ssh/*.pub`, check every line
   parses, and run the recipe above in a `creds/` directory with
   `key="$(cat ../keys)"`, then return to `$dir`. All keys go into one
   `authorized_keys`:

   ```bash
   curl -fsSL https://github.com/<github-user>.keys > keys
   ssh-keygen -lf keys
   mkdir -p creds && cd creds
   # run the recipe above here, with key="$(cat ../keys)"
   cd "$dir"
   ```

3. Write the stick by its `/dev/disk/by-id/usb-*` name, not `/dev/sdX`
   (`lsblk -o NAME,TRAN,RM,SIZE,MODEL` to find it; unmount it first), then
   copy the credentials onto its ESP. Mount the ESP through `$stick`, not
   `/dev/disk/by-partlabel/bluefin-installer`: every burned stick carries that
   label, so with another one plugged in it may resolve wrongly:

   ```bash
   stick=/dev/disk/by-id/usb-<vendor>_<model>_<serial>-0:0
   sudo dd if="bluefin-server-installer_${ver}.raw" of="$stick" bs=4M conv=fsync status=progress
   sudo partx -u "$stick"; udevadm settle
   mkdir -p mnt && sudo mount "${stick}-part3" mnt
   sudo mkdir -p mnt/loader/credentials && sudo cp creds/*.cred mnt/loader/credentials/
   sync && sudo umount mnt
   ```

4. Verify before unplugging. The usr and usr-verity partitions must match the
   image byte for byte (the ESP will not; it now holds the credentials), and
   the credentials must decrypt to the expected users, keys, and sudoers:

   ```bash
   l=$(sudo losetup -fPr --show "bluefin-server-installer_${ver}.raw")
   for p in 1 2; do sudo cmp "${l}p$p" "${stick}-part$p" && echo "part$p ok"; done
   sudo losetup -d "$l"
   sudo mount -o ro "${stick}-part3" mnt
   dec() { sudo systemd-creds decrypt --with-key=null --name="$1" "mnt/loader/credentials/$1.cred"; }
   dec sysusers.extra
   dec tmpfiles.extra | awk '/authorized_keys/{print $NF}' | base64 -d | diff - keys && echo "keys ok"
   dec tmpfiles.extra | awk '/sudoers/{print $NF}' | base64 -d   # <user> ALL=(ALL:ALL) NOPASSWD: ALL
   base64 -w0 mnt/loader/credentials/ssh.listen.cred \
     | sudo systemd-creds decrypt --with-key=null --name=ssh.listen - -   # 22
   sudo umount mnt && sudo udisksctl power-off -b "$stick"
   ```

Boot the target with Secure Boot off; after the install, `ssh <user>@<node>` works with any of the keys and `sudo` asks for no password.

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
   firmware does not, and install. The systemd-boot menu entry **Enroll
   Secure Boot keys: auto** does the same.

The firmware then trusts only the Bluefin Server keys, so add-in cards with
Microsoft-signed option ROMs (some graphics cards) may not initialise at
boot; keep a way back (another graphics output, or "restore factory keys").
`secure-boot-enroll if-safe` enrolls by itself only in VMs.

### The installer's check

`bluefin-installer-secure-boot.service` runs before `systemd-sysinstall`
and before the Homelab entries' prompt; both `Requires=` it, so when it
fails neither starts and no disk is touched. It reads `SecureBoot`,
`SetupMode` and `AuditMode` from efivarfs and decides that Secure Boot is on
**with our keys** when the firmware's `db` variable holds, byte for byte, an
X.509 certificate from the stick's `loader/keys/auto/db.auth`:

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
typed. Cancelling leaves the installer up with the reason on the monitor (and
in the journal); change the firmware and boot the stick again. Unattended
installs never ask: see [Unattended installs](#unattended-installs).

## See also

- [ddi-installer.md](ddi-installer.md) — boot, install, and update architecture.
- [ddi-installer-build.md](ddi-installer-build.md) — image build and dogfood procedure.
- [tpm2-credential-sealing.md](tpm2-credential-sealing.md) — first-boot
  credentials and ESP credential files.
- [secure-boot-keys.md](secure-boot-keys.md) — the keys that sign the stick.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (Installer).
