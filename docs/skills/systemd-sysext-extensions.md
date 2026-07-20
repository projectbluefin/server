---
name: systemd-sysext-extensions
version: "1.0"
last_updated: "2026-07-20"
tags: ['sysext', 'confext', 'extensions']
description: "Extensibility via systemd-sysext and systemd-confext for Bluefin Server. Use when adding, debugging, or documenting system extensions."
metadata:
  context7-sources:
    - /systemd/systemd
---

# Extensibility via systemd-sysext

Bluefin Server is distroless and read-only. For debugging, monitoring, or
runtime modifications, use systemd-sysext to overlay package bundles into
`/usr` and `/opt`, or systemd-confext to overlay files into `/etc`.

## Canonical scope

This file is the canonical home for extension-loading behavior, compatibility
checks, and runtime management. Draft roadmap items for deeper integration with
provisioning flow remain in [architecture-roadmap.md](architecture-roadmap.md).

## Where extensions live

System extensions are searched in:

- `/etc/extensions/`
- `/run/extensions/`
- `/var/lib/extensions/` (the primary location for persisted extension images)

Configuration extensions (confext) are searched in:

- `/run/confexts/`
- `/var/lib/confexts/`
- `/usr/lib/confexts/`
- `/usr/local/lib/confexts/`

Placing an empty directory named like the extension (without `.raw`) under
`/etc/extensions/` masks an extension of the same name in a lower-precedence
directory.

## Flatcar Bakery Compatibility

The base OS `/usr/lib/os-release` mimics Flatcar (`ID=flatcar` and a matching
`VERSION_ID`), which lets the host load pre-compiled extensions from the Flatcar
System Extension Bakery as long as the extension's `extension-release` metadata
matches the host `ID=` (or uses `ID=_any`).

If the extension enforces `VERSION_ID=` matching, the Flatcar major-version line
must match the value baked into `elements/bluefin-server/os-release-flatcar.bst`.

## Adding an extension from the Flatcar Bakery

The k3s sysext is the built-in example, but any Flatcar-compatible extension can
be layered the same way.

```bash
# Download an extension image to the persistence directory
wget https://bakery.flatcar-linux.org/extensions/htop/htop-latest.raw \
  -O /var/lib/extensions/htop.raw

# Merge it into the running system
systemd-sysext merge

# Verify it is active
systemd-sysext status
```

To pick up newly dropped extension images automatically, refresh instead of
manually merging:

```bash
systemd-sysext refresh
```

The `systemd-sysext.service` unit performs a refresh at boot, so extensions in
`/var/lib/extensions/` become available without manual intervention.

## Removing an extension

```bash
rm /var/lib/extensions/htop.raw
systemd-sysext refresh
```

## Key constraints

- Keep extensions as simple read-only bundles. Do not ship a `/usr/lib/os-release`
  file inside an extension; it would override the host OS version metadata.
- The extension image format is the same one `systemd-repart` and `systemd-sysext`
  accept: a GPT/EROFS/directory tree that contains `/usr/` and/or `/opt/`.
- For files that belong under `/etc/`, ship a **confext** and place it under
  `/var/lib/confexts/`, then use `systemd-confext merge`/`refresh`.

## Debugging

```bash
# List discovered extensions
systemd-sysext list

# Show merge state and any compatibility errors
systemd-sysext status

# Force a merge ignoring version mismatches (debugging only)
systemd-sysext merge --force
```

## See also

- `systemd-sysext(8)`, `systemd-confext(8)`
- `k3s-sysext.md` for the built-in Kubernetes extension
