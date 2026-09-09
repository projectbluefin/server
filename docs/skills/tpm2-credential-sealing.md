---
name: tpm2-credential-sealing
description: Securing provisioning credentials (such as operator SSH keys via tmpfiles.extra) with TPM2 sealing via systemd-creds.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-09-09"
  context7-sources:
    - /systemd/systemd
---
# TPM2 Credential Sealing

To secure sensitive provisioning credentials (such as operator SSH keys via
`tmpfiles.extra`) against offline tampering, bind them to the TPM2 and the UKI
boot state using `systemd-creds`.

## Current scope

This skill is the canonical home for sealed credentials, specifically the
`tmpfiles.extra` credential used to provision SSH access for the `core` operator
account. Broader `systemd-creds` integration for network configuration is a
future roadmap item in [architecture-roadmap.md](architecture-roadmap.md).

## Verify TPM2 device availability

```bash
systemd-creds list
```

`systemd-creds` defaults to the TPM2 key when a TPM2 device is available and
not running in a container.

## Encrypt and seal a credential

The `tmpfiles.extra` credential payload establishes directory ownership and
writes the authorized SSH keys for the `core` operator account:

```text
d /var/home/core 0700 core core -
d /var/home/core/.ssh 0700 core core -
f~ /var/home/core/.ssh/authorized_keys 0600 core core - c3NoLWVkMjU1MTkgQUFBQUMzTnphQzFsWkRJMU5UR...
```

The base64 data in the `f~` line is an SSH public key, not a secret. Sealing
the credential ensures that unauthorized keys cannot be injected into the
machine offline when TPM2 protection is active.

Seal the credential against PCR 7 (Secure Boot state) and PCR 11 (Unified Kernel
Image state) on the TPM2 chip:

```bash
systemd-creds encrypt \
  --name=tmpfiles.extra \
  --with-key=tpm2 \
  --tpm2-pcrs=7+11 \
  /path/to/plaintext_tmpfiles_extra.txt \
  /path/to/secured_credential.cred
```

- `--name=` must match the credential name the consumer expects (for example,
  `tmpfiles.extra` is read by `systemd-tmpfiles`).
- `--with-key=tpm2` forces a TPM2-bound credential. The default `auto` also uses
  the host key if `/var/lib/systemd/` is on persistent media; omit the switch
  if you want both bindings.
- `--tpm2-pcrs=7+11` means the credential can only be decrypted when the same
  Secure Boot and UKI measurements are present.

## Provide the encrypted credential to the host

Place the output `.cred` file in the ESP credential directory or pass it via a
container/hypervisor mechanism. The credential file is
`/loader/credentials/tmpfiles.extra.cred` on the target ESP:

```bash
# ESP delivery
mkdir -p /loader/credentials/
cp /path/to/secured_credential.cred /loader/credentials/tmpfiles.extra.cred

# Or via a container/hypervisor argument
--set-credential=tmpfiles.extra:/path/to/secured_credential.cred
```

## Offline recovery sequence

There is no fallback password or root SSH bypass. If the `core` key is lost or
unusable, SSH fails closed. The supported offline recovery sequence requires
physical access or equivalent hypervisor access:

1. Shut down the target host.
2. Mount the target ESP from a trusted machine.
3. Replace `/loader/credentials/tmpfiles.extra.cred` on the ESP with a
   credential that writes the replacement `core` public key.
4. Boot the host. `systemd-tmpfiles` applies the credential, `bluefin-core-access`
   verifies key readiness, and `sshd` starts.
5. Authenticate as `core` (`ssh core@server.example`) and elevate using `sudo -i`.

## See also

- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
- [factory-integration.md](factory-integration.md) — operator login and remote diagnostics.
- `systemd-creds(1)`
- `systemd.system-credentials(7)`
