---
name: tpm2-credential-sealing
description: Securing provisioning credentials (such as hashed root passwords or SSH keys) with TPM2 sealing via systemd-creds.
metadata:
  type: how-to
  status: stable
  last_updated: 2026-09-04
  context7-sources:
    - /systemd/systemd
---
# TPM2 Credential Sealing

To secure sensitive provisioning credentials (such as hashed root passwords or
SSH keys) against physical tampering or unauthorized extraction, bind them to
the TPM2 and the UKI boot state using `systemd-creds`.

## When to Use

- Sealing a provisioning credential (hashed root password, SSH key material)
  for delivery to a host.
- Choosing PCR bindings for a `systemd-creds` credential.
- Debugging credential delivery via the ESP or a hypervisor mechanism.

## When NOT to Use

- The OTA update trust chain (`SHA256SUMS.gpg`) — see
  [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md).
- Broader `systemd-creds` integration planning — that is roadmap work in
  [architecture-roadmap.md](architecture-roadmap.md).

## Current scope

This skill is the canonical home for sealed credentials such as hashed root
passwords and similar provisioning secrets. Broader `systemd-creds` integration
for SSH keys and network configuration is a future roadmap item in
[architecture-roadmap.md](architecture-roadmap.md).

## Core Process

### Verify TPM2 device availability

```bash
systemd-creds list
```

`systemd-creds` defaults to the TPM2 key when a TPM2 device is available and
not running in a container.

### Encrypt and seal a credential

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

- `--name=` must match the credential name the consumer expects (for example,
  `passwd.hashed-password.root` is read by `systemd-sysusers`).
- `--with-key=tpm2` forces a TPM2-bound credential. The default `auto` also uses
  the host key if `/var/lib/systemd/` is on persistent media; omit the switch
  if you want both bindings.
- `--tpm2-pcrs=7+11` means the credential can only be decrypted when the same
  Secure Boot and UKI measurements are present.

### Provide the encrypted credential to the host

Place the output `.cred` file in the ESP credential directory or pass it via a
container/hypervisor mechanism:

```bash
# ESP delivery
mkdir -p /loader/credentials/
cp /path/to/secured_credential.cred /loader/credentials/passwd.hashed-password.root.cred

# Or via a container/hypervisor argument
--set-credential=passwd.hashed-password.root:/path/to/secured_credential.cred
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The default `auto` key binding is good enough." | `auto` also binds the host key when `/var/lib/systemd/` is persistent; use `--with-key=tpm2` when the credential must be TPM-only. |
| "PCR 7 alone is sufficient." | PCR 7 covers Secure Boot state only; add PCR 11 so the credential also dies with a changed UKI. |
| "A plaintext credential in the ESP is fine for bring-up." | The ESP is unencrypted and readable; seal before shipping anything sensitive. |

## Red Flags

- `--name=` not matching the name the consumer expects.
- Plaintext credential files placed in the ESP or embedded in the image.
- Omitting `--with-key=tpm2` when a TPM-only binding is required.

## Verification

- [ ] `systemd-creds list` shows a TPM2 device on the target host.
- [ ] The sealed credential decrypts only on the host and boot state it was
      sealed against.
- [ ] The consumer (for example, `systemd-sysusers` reading
      `passwd.hashed-password.root`) picks up the credential at boot.

## See also

- `systemd-creds(1)`
- `systemd.system-credentials(7)`
