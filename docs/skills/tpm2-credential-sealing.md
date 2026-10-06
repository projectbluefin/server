---
name: tpm2-credential-sealing
description: Securing provisioning credentials (such as hashed root passwords or SSH keys) with TPM2 sealing via systemd-creds.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-10-05"
  context7-sources:
    - /systemd/systemd
---
# TPM2 Credential Sealing

To secure sensitive provisioning credentials (such as hashed root passwords or
SSH keys) against physical tampering or unauthorized extraction, bind them to
the TPM2 and the UKI boot state using `systemd-creds`.

## Supported provisioning credentials

Bluefin Server consumes the same system credential names that systemd already
decrypts and routes at boot:

| Credential | Consumer | Purpose |
|---|---|---|
| `passwd.hashed-password.root`, `passwd.plaintext-password.root` | `systemd-firstboot` | Optional console root password; see [Node access](#node-access). |
| `ssh.authorized_keys.root` | `systemd-tmpfiles` (stock `provision.conf`) | Root's SSH `authorized_keys`; see [Node access](#node-access). |
| `ssh.listen` | `systemd-ssh-generator` | Socket-activated sshd on the given address or port; see [Node access](#node-access). |
| `tmpfiles.extra` | `systemd-tmpfiles` | Extra tmpfiles rules, such as files for other accounts. |
| `network.network.*`, `network.netdev.*`, `network.link.*`, `network.conf.*` | `systemd-network-generator` | Static network, routes, virtual devices, and networkd config. |
| `network.dns`, `network.search_domains` | `systemd-resolved` | DNS resolver defaults. |
| `firstboot.locale`, `firstboot.locale-messages`, `firstboot.keymap`, `firstboot.timezone`, `firstboot.hostname` | `bluefin-firstboot-credentials.service` | Non-interactive locale, keymap, timezone, and hostname setup. |
| `system.hostname` | PID 1 (transient), `bluefin-hostname.service` (static) | Hostname; see [Node name, mDNS and prompt](#node-name-mdns-and-prompt). |

The stock DHCP network remains installed in `/usr/lib/systemd/network/20-wired.network`.
Credential-generated network files are emitted under `/run/systemd/network/` and
can use lower numeric prefixes such as `10-static.network` to override DHCP.

## Node access

The image ships no password. Root's `/etc/shadow` entry is `!unprovisioned`
(`elements/oci/bluefin-server-usr.bst`), systemd's marker for a root account
nobody has configured: `passwd -S root` reports `L`, console login, `su` and
`sulogin` refuse it, and sshd accepts keys only
(`files/os/ssh/sshd_config.d/bluefin-server.conf`). Access is provisioned per
node:

- **SSH key:** Ignition `passwd.users` with `name: root` and
  `sshAuthorizedKeys` (the path Booty's `bluefin-node.ign` uses; see
  Ignition in [ddi-installer.md](ddi-installer.md)), or the
  `ssh.authorized_keys.root` credential, whose content is the
  `authorized_keys` file. Both write `/root/.ssh/authorized_keys`.
  `sshd.service` is disabled by preset; enable it per node in the same
  Ignition config (`systemd.units`: `name: sshd.service`, `enabled: true`),
  or pass the `ssh.listen` credential (e.g. `22`), for which
  `systemd-ssh-generator` socket-activates a per-connection sshd with the
  same key-only policy.
- **Console password:** `passwd.hashed-password.root` (a `crypt(5)` hash with
  no trailing newline, e.g. `mkpasswd --method=yescrypt | tr -d '\n'`) or
  `passwd.plaintext-password.root`.
  `systemd-sysusers` cannot apply these, because it only sets passwords for
  accounts it creates and root already exists in the factory `/etc/shadow`.
  `systemd-firstboot.service` applies them instead: it treats `!unprovisioned`
  as unconfigured. Its interactive root password prompt is removed
  (`files/os/creds/systemd/system/systemd-firstboot.service.d/`) so a node
  without the credential boots unattended and stays locked. One path is
  deliberately exempt: a disk installed from the USB stick carries the
  `bluefin.prompt-root-password` credential the installer sets on it, and
  `bluefin-root-password-prompt.service` asks for a root password on tty1 on
  that disk's first boot, because the person who ran the installer is at the
  console (see [usb-installer.md](usb-installer.md)). Either credential above
  answers that prompt unattended, as given; without one it asks again until
  root has a password.

`systemd-firstboot` runs on first boot only. A diskless node rebuilds `/etc`
from `/usr/share/factory/etc` and is on its first boot every time, so the
credential applies on every boot. An installed node applies it on the first
boot of the installed disk and keeps the result in `/etc/shadow` on the
persistent xfs root; A/B updates replace only the usr, usr-verity and UKI
slots (`files/os/sysupdate.d/`), so the password survives them. A credential
added to an installed node after its first boot is ignored; change the
password with `passwd` instead.

Deliver the credentials like any other: SMBIOS type 11 or QEMU fw_cfg on VMs,
an Ignition-capable boot server, or encrypted `.cred` files in
`/loader/credentials/` on the ESP (see below). The USB installer needs no
login: `systemd-sysinstall` runs on the console. Credentials placed in
`/loader/credentials/` on the stick are copied onto the installed disk's ESP
(`CopyFiles=` in the stick's ESP definition), so the installer's own boot and
every boot of the installed node see the same set; see
[usb-installer.md](usb-installer.md). Credentials can also be added to an
installed disk's ESP directly, before its first boot.

With root locked, `emergency.target` and `rescue.target` on the booted system
get no shell: `sulogin` reports the locked account and boot continues. Do not
set `SYSTEMD_SULOGIN_FORCE`, which opens a passwordless root shell on the
console; the kernel command line is sealed in the signed UKI, so it cannot be
added at boot either. For break-glass console access, provision a password
credential and `sulogin` asks for it. The initrd never offers a shell; it
prints the errors and reboots.

## Node name, mDNS and prompt

Every node has a unique static hostname, announces it on its wired links as
`<hostname>.local` over multicast DNS, and gives interactive bash a
`user@host:cwd$` prompt (`#` for root).

**Hostname.** `bluefin-hostname.service` (`/usr/libexec/bluefin-hostname`)
runs on first boot, before networkd's first DHCP request. A static hostname
already set (`/etc/hostname` from Ignition, `systemd-firstboot` or the
`firstboot.hostname` credential) is kept. A node whose static hostname is
unset or `localhost` gets, in this order, the `firstboot.hostname`
credential, the `system.hostname` credential (which PID 1 alone only applies
as the transient hostname), or `bluefin-<first 8 hex digits of the machine
ID>`, so appliances on one LAN do not collide. An invalid name (anything but
dot-separated letters, digits and inner hyphens, 63 characters per label, 64
in all), in `/etc/hostname` or a credential, fails
`bluefin-firstboot-credentials.service` or `bluefin-hostname.service` and is
not replaced by another name: `systemctl --failed` shows it and the hostname
stays `localhost`. A DHCP-provided hostname does not override the static one.
The homelab's `bluefin-cluster` runs the same helper before a node registers
with Kubernetes.

An installed node keeps `/etc/hostname` on its persistent root, so the name
survives reboots and A/B updates (which replace only the usr, usr-verity and
UKI slots). Rename it with `hostnamectl set-hostname <name>`; the unit runs
on first boot only and never renames a named node. A node installed before
this unit existed keeps its old name, `localhost` included, because a
Kubernetes node may already be registered under it; rename it with
`hostnamectl`. A diskless node rebuilds `/etc` on every boot: it is named
from Ignition or a credential on each boot, else from its machine ID, which is
random per boot unless the `system.machine_id` credential pins it (a 32-hex ID,
or `firmware` for the SMBIOS UUID; see
[diskless-troubleshooting.md](diskless-troubleshooting.md)), and a
`hostnamectl` rename lasts until the next reboot.

**mDNS.** `20-wired.network` sets `MulticastDNS=yes` and `LLMNR=no` on every
wired (`e*`) link, and `/usr/lib/systemd/resolved.conf.d/50-bluefin-mdns.conf`
turns multicast DNS on and LLMNR off in systemd-resolved; there is no avahi.
resolved answers for the hostname's first label as `<label>.local` and
resolves other `.local` names; DHCP-provided DNS servers serve everything
else as before. Programs that resolve through NSS (`nss-resolve` in
`/etc/nsswitch.conf`: `ssh`, `curl`, `getent`) and `resolvectl query` see
`.local` names; programs that read `/etc/resolv.conf` themselves (statically
linked Go such as `kubectl`, `dig`) do not, since it lists the uplink
servers. A `network.network.*` credential replaces `20-wired.network` on the
links it matches, so add `MulticastDNS=yes` to it to keep the name there. The
image ships no host firewall; one added later must allow UDP 5353 to
224.0.0.251 and ff02::fb. Two nodes with one name are an operator error:
nothing renames a node. The resolved that detects the clash logs
`Hostname conflict, changing published hostname` and announces a numbered
variant (the system hostname stays as it is) until one node is renamed with
`hostnamectl`. The console banner shows the name as
`mDNS: <hostname>.local` (see "Console banner" in
[usb-installer.md](usb-installer.md)).

**Prompt.** `/usr/lib/bluefin/profile.d/90-bluefin-prompt.sh`, linked into
`/etc/profile.d` by tmpfiles (`50-bluefin-prompt.conf`, so installed nodes
get changes with updates), sets `\u@\h:\w\$ ` for interactive bash with
only the `@` in blue (ANSI 34), and the same without colour when `NO_COLOR`
is set or `TERM` is `dumb` or unset. Non-interactive shells and other shells
are untouched. FSDK's `/etc/profile` sets its own prompt after reading
`/etc/profile.d`, so the fragment applies from `PROMPT_COMMAND`, and only
over the stock prompts: a `PS1` from `~/.bashrc` or the command line wins. To
opt out node-wide, replace the `/etc/profile.d/90-bluefin-prompt.sh` link
with an empty file.

## Verify TPM2 device availability

```bash
systemd-creds list
```

`systemd-creds` defaults to the TPM2 key when a TPM2 device is available and
not running in a container.

## Encrypt and seal a credential

Seal the credential against PCR 7 (Secure Boot state) and PCR 11 (Unified Kernel
Image state) on the TPM2 chip:

```bash
systemd-creds encrypt \
  --name=passwd.hashed-password.root \
  --with-key=tpm2 \
  --tpm2-pcrs=7+11 \
  /path/to/plaintext_password_hash.txt \
  /path/to/secured_credential.cred
```

- `--name=` must match the credential name the consumer expects. Examples:
  `passwd.hashed-password.root`, `tmpfiles.extra`,
  `network.network.10-static`, or `firstboot.hostname`.
- `--with-key=tpm2` forces a TPM2-bound credential. The default `auto` also uses
  the host key if `/var/lib/systemd/` is on persistent media; omit the switch
  if you want both bindings.
- `--tpm2-pcrs=7+11` means the credential can only be decrypted when the same
  Secure Boot and UKI measurements are present.

## Provide the encrypted credential to the host

Place the output `.cred` file in the ESP credential directory or pass it via a
container/hypervisor mechanism:

```bash
# ESP delivery (bare metal or virtual machines)
# Mount the target host's EFI System Partition (ESP) and place credentials in /loader/credentials/
mkdir -p /loader/credentials/
cp /path/to/secured_credential.cred \
  /loader/credentials/passwd.hashed-password.root.cred

# Or via a container/hypervisor argument
--set-credential=passwd.hashed-password.root:/path/to/secured_credential.cred
```

On bare metal, an operator mounts the ESP partition (e.g. filesystem label
`EFI-SYSTEM` or partition type `C12A7328-F81F-11D2-BA4B-00A0C93EC93B`) and
places encrypted credential files into `/loader/credentials/`. During boot,
`systemd-creds` decrypts them and passes them to matching system consumers.
ESP credentials are untrusted, so systemd only accepts them encrypted; a
`--with-key=null` credential is refused on a machine with a TPM2 and Secure
Boot on. PCR 11 changes with every UKI, so a diskless node that boots each new
release needs its `--tpm2-pcrs=7+11` credentials re-sealed per release.

A `--with-key=null` credential is encrypted with a fixed, public key: it is
obfuscated, not secret. Anyone who can read the unencrypted vfat ESP — of the
installer stick, or of any disk the stick installed, since the stick's
`/loader/credentials/` is copied onto each — can recover the plaintext. Never
put a real secret (`passwd.plaintext-password.*`, a `crypt(5)` hash worth
cracking, a private key) in a null-key credential. Use `--with-key=tpm2` for
those, and reserve null-key credentials for non-secret payloads such as the
`*` / `!*` password fields and `ssh.listen` in the installer recipe.

### SSH key provisioning

Deliver root's `authorized_keys` as the `ssh.authorized_keys.root` credential
(for example `/loader/credentials/ssh.authorized_keys.root.cred`); systemd's
stock `provision.conf` tmpfiles rule writes it to `/root/.ssh/authorized_keys`.
For other accounts, use a `tmpfiles.extra` credential; the payload must create
parent directories before writing the file:

```text
d /var/home/alice 0700 alice alice -
d /var/home/alice/.ssh 0700 alice alice -
f~ /var/home/alice/.ssh/authorized_keys 0600 alice alice - c3NoLWVkMjU1MTkgQUFBQUMzTnphQzFsWkRJMU5URTEAAAA...
```

Example static network credential name: `network.network.10-static`.

```ini
[Match]
Name=en*

[Network]
Address=192.0.2.10/24
Gateway=192.0.2.1
DNS=192.0.2.53
```

## See also

- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
- `systemd-creds(1)`
- `systemd.system-credentials(7)`
