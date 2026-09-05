---
name: systemd-sysext-extensions
description: Extensibility via systemd-sysext and systemd-confext for Bluefin Server. Use when adding, debugging, or documenting system extensions.
metadata:
  type: reference
  status: stable
  last_updated: 2026-09-04
  context7-sources:
    - /systemd/systemd
---
# Extensibility via systemd-sysext

Bluefin Server is distroless and read-only. For debugging, monitoring, or
runtime modifications, use systemd-sysext to overlay package bundles into
`/usr` and `/opt`, or systemd-confext to overlay files into `/etc`.

## When to Use

- Adding, removing, or debugging a sysext/confext extension on a host.
- Loading a pre-built extension from the Flatcar System Extension Bakery.
- Deciding whether configuration belongs in `/usr/etc`, `/etc`, or a confext.

## When NOT to Use

- Building or shipping the k3s extension — see [k3s-sysext.md](k3s-sysext.md).
- Workload containers — those are podman or `machinectl` system containers
  (see [system-containers.md](system-containers.md)).

## Canonical scope

This file is the canonical home for extension-loading behavior, compatibility
checks, and runtime management. It is also the canonical home for the
repository-wide configuration placement policy (`/usr/etc` vs `/etc`). Future
roadmap items for deeper integration with the provisioning flow remain in
[architecture-roadmap.md](architecture-roadmap.md).

## Configuration placement: `/usr/etc` vs `/etc`

- **Vendor-authored configuration** — defaults this repo ships in an image —
  belongs under `/usr/etc`. This is Bluefin policy, not automatic systemd
  behavior: daemons read their compiled-in config paths, and most do not
  search `/usr/etc` on their own. The policy holds because each shipped
  vendor default either targets a daemon with vendor-path support or is
  bridged by a documented compatibility mechanism (see the exceptions
  below).
- **`/etc` is mutable operator/runtime state**: local overrides, first-boot
  provisioning output, and anything written after the image is built.
- **Durability across updates:** `/etc` ships inside the root image, so
  plain `/etc` edits are mutable but boot-local — a root-image OTA
  replacement swaps in a fresh image and hand edits do not carry over.
  Durable operator overrides belong in a `systemd-confext` placed under
  `/var/lib/confexts/` (`/var` persists across image replacement; see
  "Where extensions live").
- A file may ship under `/etc` only in these cases, and each exception must
  be documented here with its compatibility mechanism:
  1. **Upstream daemon hardcodes the path.** Example: OpenSSH compiles in
     `/etc/ssh/sshd_config` (no `/usr/etc` support, no `-f` in FSDK's unit);
     the compatibility mechanism is a relative symlink
     `/etc/ssh/sshd_config → ../../usr/etc/ssh/sshd_config` installed by
     `elements/bluefin-server/os-sshd-config.bst`. The merged vendor
     config (`/usr/etc/ssh/sshd_config`) and the policy drop-in
     (`/usr/etc/ssh/sshd_config.d/bluefin-server.conf`) stay under `/usr/etc`;
     the symlink is the only `/etc` artifact of this repo's SSH policy —
     "single artifact" scopes to the sshd wiring, not to all package
     content shipped in the image. The vendor config's `Include` lines
     put the operator and systemd userdb drop-ins in
     `/etc/ssh/sshd_config.d/*.conf` first, then vendor ones
     (first-match-wins), so operators override policy via mutable `/etc` —
     or durably via a confext — and the userdb wiring stays effective.
  2. **Generated/local state.** Files a daemon or the installer writes at
     runtime (e.g. k3s writing `/etc/rancher/`, installer initrd state) are
     runtime state, not shipped configuration; they need no exception entry
     and must not be vendored into the image.
  3. **Operator-facing entrypoint with no vendor lookup.** The system-wide
     justfile (`/etc/justfile`, shipped by
     `elements/bluefin-server/os-justfile.bst` from `files/os/justfile`)
     is vendor content under `/etc` because `just(1)` has no
     `/usr/etc`-style vendor search path for justfiles and the file is the
     documented interactive entrypoint (`just k8s server|agent`). Like any
     plain `/etc` file it is boot-local across root-image replacement;
     treat local customizations as candidate confext content rather than
     edits to the shipped file.

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

## Core Process

1. Decide the extension type: content for `/usr` or `/opt` → sysext; operator
   `/etc` overrides → confext.
2. Place the image in the persistence directory (`/var/lib/extensions/` or
   `/var/lib/confexts/`).
3. Run `systemd-sysext merge` (or `refresh` to pick up newly dropped images);
   `systemd-confext` works the same way for confexts.
4. Confirm with `systemd-sysext status`; remove by deleting the image and
   refreshing.

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
  `/var/lib/confexts/`, then use `systemd-confext merge`/`refresh`. A confext
  is for operator-managed layering and — because `/var` persists — is the
  durable way to carry operator `/etc` overrides across root-image OTA
  replacement; vendor defaults still follow the
  `/usr/etc` vs `/etc` policy above.

## Debugging

```bash
# List discovered extensions
systemd-sysext list

# Show merge state and any compatibility errors
systemd-sysext status

# Force a merge ignoring version mismatches (debugging only)
systemd-sysext merge --force
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Ship an `os-release` in the extension so it looks complete." | It would override the host OS version metadata. Never ship one. |
| "Edit `/etc` directly; it persists." | `/etc` ships in the root image — hand edits are boot-local across OTA replacement. Durable overrides go in a confext under `/var/lib/confexts/`. |
| "Vendor defaults can just live in `/etc`." | Vendor-authored config belongs under `/usr/etc`; `/etc` exceptions need a documented compatibility mechanism (see the policy above). |

## Red Flags

- An extension image containing `/usr/lib/os-release`.
- Runtime-generated state vendored into the image as configuration.
- `systemd-sysext merge --force` used outside debugging.
- A `/etc` exception not documented in the policy section above.

## Verification

- [ ] `systemd-sysext status` shows the extension merged without compatibility
      errors.
- [ ] No extension ships an `os-release` file.
- [ ] Every `/etc` exception is documented here with its compatibility
      mechanism.
- [ ] Durable operator `/etc` overrides are delivered as a confext in
      `/var/lib/confexts/`, not as hand edits.

## See also

- `systemd-sysext(8)`, `systemd-confext(8)`
- `k3s-sysext.md` for the built-in Kubernetes extension
