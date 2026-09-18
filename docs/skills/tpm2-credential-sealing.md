---
name: tpm2-credential-sealing
description: Securing provisioning credentials (such as hashed root passwords or SSH keys) with TPM2 sealing via systemd-creds.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-09-07"
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
| `passwd.hashed-password.root` | `systemd-sysusers` / `systemd-firstboot` | Optional root password hash for break-glass provisioning. |
| `tmpfiles.extra` | `systemd-tmpfiles` | Extra tmpfiles rules, such as writing an operator's SSH `authorized_keys`. |
| `network.network.*`, `network.netdev.*`, `network.link.*`, `network.conf.*` | `systemd-network-generator` | Static network, routes, virtual devices, and networkd config. |
| `network.dns`, `network.search_domains` | `systemd-resolved` | DNS resolver defaults. |
| `firstboot.locale`, `firstboot.locale-messages`, `firstboot.keymap`, `firstboot.timezone`, `firstboot.hostname` | `bluefin-firstboot-credentials.service` | Non-interactive locale, keymap, timezone, and hostname setup. |

The stock DHCP network remains installed in `/usr/lib/systemd/network/20-wired.network`.
Credential-generated network files are emitted under `/run/systemd/network/` and
can use lower numeric prefixes such as `10-static.network` to override DHCP.

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
# ESP delivery
mkdir -p /loader/credentials/
cp /path/to/secured_credential.cred \
  /loader/credentials/passwd.hashed-password.root.cred

# Or via a container/hypervisor argument
--set-credential=passwd.hashed-password.root:/path/to/secured_credential.cred
```

Example `tmpfiles.extra` payload writing SSH `authorized_keys` for an operator
account (the account itself must already be defined by `systemd-sysusers`):

```text
f~ /var/home/core/.ssh/authorized_keys 0600 core core - c3NoLWVkMjU1MTkgQUFBQUMzTnphQzFsWkRJMU5URTEAAAA...
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
