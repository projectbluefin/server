---
name: usb-installer-provisioning
description: Provision nodes from the offline USB installer. Load when working on the installer's Homelab entries, Home Server profile credentials, unattended installs via unit-dropin credentials, first-boot prompts, ESP credential files, or developer-mode sticks.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-30"
  context7-sources:
    - /systemd/systemd
    - /openssh/openssh-portable
---
# USB installer provisioning

The installer image, its boot flow, the sysinstall drop-in and the Secure
Boot check live in [usb-installer.md](usb-installer.md). This file covers
what the install writes into the node: profiles, credentials, and developer
mode.

## Homelab entries

The preserved Homelab entries install the same OS onto the chosen disk,
with the same disk/confirmation prompts, and make it a homelab control
plane or node ([homelab-profile.md](homelab-profile.md)) without a network
during the install; they do not select Homebrew implicitly.

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
    `10-esp.conf.d/50-bluefin-homelab.conf` adds a `CopyFiles=` of the
    stick's shared `bluefin/extensions/` and its `SHA256SUMS` to the installed ESP's
    `/bluefin/extensions/`. On the first boot `bluefin-sysext-fetch.service`
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

Optional cluster composition retains canonical Homelab/add-on/Gateway configuration, removes only its sample OS-root account/key, and keeps Home root locked. The SSH owner and Console administrator are separate identities: no general sudo or admin kubeconfig copy. The local/serial banner provides `https://kubestellar.<HOMELAB_DOMAIN>` and the generated-once dedicated `admin` password from `kubestellar-console-login`, written only to private `/run/issue.d/51-kubestellar-console.issue` (0600), not the journal. Read it at the physical console and log in from the LAN; headless use requires private console/management access. HTTPS/DNS requirements and shared-admin limits remain in [homelab-profile.md](homelab-profile.md); per-owner enrollment/recovery is not implemented by this option.

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

That credential is also what marks an install as unattended for the
[Secure Boot](usb-installer.md) check, which then never asks: unless Secure Boot
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
the answer.
Nodes installed any other way never get the credential and never prompt. A
`passwd.hashed-password.root` / `passwd.plaintext-password.root` credential
sets the password instead of the prompt, applied as given (also `!*`), as
`scripts/dogfood-installer.sh` does for the unattended test. See
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
off on the target, so the installer warns first: choose **Continue without
Secure Boot**):

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
SSH on port 22 with no one at the console. Leave that file out to also get a
console login: the first boot then asks on the monitor for a root password,
as without developer mode, and waits for it before anything else (SSH
included) starts. `passwd.hashed-password.<user>`
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

### Burning a developer stick end to end

The sequence used to burn developer sticks for the homelab: newest release,
verified, the recipe above with a GitHub user's public keys, then checked on
the stick itself.

1. Fetch the newest release and verify it. The keyring is the one the image
   ships for sysupdate:

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
   label, so with another one plugged in it may resolve to the wrong device:

   ```bash
   stick=/dev/disk/by-id/usb-<vendor>_<model>_<serial>-0:0
   sudo dd if="bluefin-server-installer_${ver}.raw" of="$stick" bs=4M conv=fsync status=progress
   sudo partx -u "$stick"; udevadm settle
   mkdir -p mnt && sudo mount "${stick}-part3" mnt
   sudo mkdir -p mnt/loader/credentials && sudo cp creds/*.cred mnt/loader/credentials/
   sync && sudo umount mnt
   ```

4. Verify before unplugging. The usr and usr-verity partitions must match the
   image byte for byte (the ESP will not, since it now holds the credentials),
   and the credentials must decrypt to the expected users, keys, and sudoers:

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

Boot the target with Secure Boot off. After the install, `ssh <user>@<node>`
works with any of the keys, and `sudo` asks for no password.

## See also

- [usb-installer.md](usb-installer.md) — the installer image, boot flow, Secure Boot check.
- [tpm2-credential-sealing.md](tpm2-credential-sealing.md) — sealing credentials with TPM2.
- [homelab-profile.md](homelab-profile.md) — the Homelab templates and cluster profile.
