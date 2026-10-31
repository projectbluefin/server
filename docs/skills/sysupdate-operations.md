---
name: sysupdate-operations
description: Operate Bluefin Server's sysupdate trust in the field. Load when reading a node's update-health banner, checking update status by hand, or rotating the release signing key.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-10-30"
  context7-sources:
    - /systemd/systemd
---
# sysupdate operations: update health and key rotation

The trust model, transfer files and in-build signing live in
[systemd-sysupdate-verification.md](systemd-sysupdate-verification.md). This
file is the operator side.

## Update health on the node

An installed node (from the USB stick or from diskless) shows its update
health at the console login prompt and after every console or SSH login:

```text
Bluefin Server 26.10.871, automatic updates on
Last update check: 2026-10-03 18:02 UTC; 26.10.880 staged, it boots at the next reboot
Last update check FAILED 2026-10-03 20:04 UTC: signature verification failed (Signature verification failed.)
  journalctl -u systemd-sysupdate.service
```

- Line 1: the running `IMAGE_VERSION`, and whether `systemd-sysupdate.timer`
  is enabled (`automatic updates off (systemd-sysupdate.timer is disabled)`
  otherwise).
- Line 2: the last successful `systemd-sysupdate.service` run (`never` until
  the timer's first run, 15 minutes to a few hours after boot), then a staged
  update (a UKI newer than the booted one), an update that used up its boot
  tries, or `up to date`.
- Lines 3-4, only while no check has succeeded since the newest failed one:
  when it failed and why. A `Signature verification failed.` (a set signed by
  a key the node does not trust, as in
  [#307](https://github.com/projectbluefin/server/issues/307)) reads
  `signature verification failed`; a transfer or HTTP error reads
  `update source unreachable`; the first error the run logged follows in
  parentheses.

`bluefin-update-status.service` (enabled by `80-bluefin-updates.preset`,
installed nodes only) writes it at boot, and
`systemd-sysupdate.service.d/30-update-status.conf` starts it after every run
(`OnSuccess=`/`OnFailure=`). `/usr/libexec/bluefin-update-status` keeps the
last success, the last error and the run it last recorded in
`/var/lib/bluefin-update-status/state`, so they survive reboots and updates,
and writes `/run/issue.d/40-bluefin-update.issue` (agetty, next to
`/usr/lib/issue.d/30-bluefin.issue`) and `/run/motd`. login (`MOTD_FILE` in
`login.defs`) and sshd (`UsePAM no`) only print `/etc/motd`, so
`tmpfiles.d/40-bluefin-motd.conf` links it to `/run/motd` unless the operator
has an `/etc/motd` of their own. It only reads local state and contacts
nothing. A failed check also stays a failed unit, `systemd-sysupdate.service`,
until a later run succeeds.

To check update health by hand:

```bash
systemctl status systemd-sysupdate.service systemd-sysupdate.timer
journalctl -u systemd-sysupdate.service     # every check, with gpg's verdict
systemd-sysupdate list                      # installed and available versions
systemd-sysupdate check-new                 # prints a newer version, if any
systemctl start systemd-sysupdate.service   # check (and stage) now
```

`scripts/dogfood-installer.sh <dir> <next-dir>` (`just dogfood-installer
NEXT=<next-dir>`, and CI's boot test outside releases) holds this contract
for a stick install: the timers are on, the keyring is the image's, an
unreachable source and a foreign-signed set each fail the unit and show on the
banner, `<next-dir>` (signed with the same key) is staged and booted and
blessed, and the banner shows both versions. These runs use dev keys.
`NEXT=release` keeps the image's own source instead, so an official stick is
checked against the official releases, as on a real PC.

## Rotating the Signing Key

1. Generate a new RSA sign-only key:
   ```bash
   export GNUPGHOME=$(mktemp -d)
   cat > "$GNUPGHOME/keygen" <<'EOF'
   %echo Generating new sysupdate signing key
   Key-Type: RSA
   Key-Length: 4096
   Key-Usage: sign
   Name-Real: Bluefin Server Release Signing
   Name-Email: releases@projectbluefin.io
   Expire-Date: 0
   %no-protection
   %commit
   %echo done
   EOF
   gpg --batch --gen-key "$GNUPGHOME/keygen"
   KEYID=$(gpg --list-keys --with-colons 'releases@projectbluefin.io' | awk -F: '/^pub:/ {print $5; exit}')
   gpg --export --output /secure/offline/new-public.pgp "$KEYID"
   gpg --export-secret-keys --armor "$KEYID" > /secure/offline/backup.asc
   rm -rf "$GNUPGHOME"
   ```
2. Combine the existing release public keys with `/secure/offline/new-public.pgp`
   in `files/os/sysupdate-keys/import-pubring.gpg`. Before switching signers,
   ship a bridge release carrying this combined vendor keyring, signed by the
   **old** private key. Keep `SYSUPDATE_SIGNING_KEY` unchanged for that release. Ensure nodes
   have booted it and any legacy `/etc` factory copies have been migrated as
   described in
   [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md)
   before proceeding. Nodes that skip the bridge need their trust provisioned
   through a trusted administrative channel.
3. Update the `release` environment secret `SYSUPDATE_SIGNING_KEY` with the
   new ASCII-armored private key (see "Environments and secrets" in
   [ci-tooling.md](ci-tooling.md)).
4. Rebuild and publish a release under a new `image-version` (a key rotation
   is never a rebuild of an existing version; see
   "Keys" in [ddi-installer-build.md](ddi-installer-build.md)). Existing hosts only
   trust updates signed by the key in their keyring, so plan the rotation
   around a release boundary. Retire the old public key in a later image
   only after the transition is complete.

For a throwaway local signing key, `just gen-dev-keys` writes the pair on its
own; see [secure-boot-keys.md](secure-boot-keys.md).

## See also

- [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md) —
  trust model, transfers, in-build signing.
- [secure-boot-keys.md](secure-boot-keys.md) — key inventory and CI secrets.
