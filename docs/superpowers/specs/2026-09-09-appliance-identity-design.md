# Appliance Identity, mDNS, and Bash Prompt Design

**Status:** Approved design

## Goal

Give each Bluefin Server appliance a stable, human-readable network identity
and a clear interactive prompt. A newly provisioned appliance without an
operator-selected hostname is `blueserver-0`, reachable as
`blueserver-0.local`.

## Scope

- Persist a selected hostname across OS DDI updates.
- Default an unselected appliance to `blueserver-0`.
- Resolve and announce appliance names through mDNS on the wired appliance
  network.
- Display `username@hostname` with a blue `@` in interactive Bash sessions.
- Direct console users to the hostname-based KubeStellar URL.

This design does not add an authoritative DNS server, DHCP server, Avahi, or
automatic hostname allocation.

## Naming Policy

The recommended fleet sequence is `blueserver-0`, `blueserver-1`,
`blueserver-2`, and so on. The default is always `blueserver-0`; later
appliances receive an explicitly selected hostname through provisioning.

An operator may select another valid lower-case static hostname, but
documentation recommends the numbered pattern and requires checking
`<hostname>.local` before selecting a name. The system does not probe mDNS and
choose a number automatically: two simultaneous installations can otherwise
choose the same name. A collision is an operator-visible configuration error,
not a reason to silently rename an appliance.

`blueserver.local` is intentionally not an alias. The canonical address is
always the selected hostname followed by `.local`, so each device has exactly
one predictable appliance name.

## Persistent Hostname State

`/var/lib/bluefin-server/hostname` is the canonical hostname source. It lives
on the persistent `/var` partition, outside the replaceable OS DDI.

The image creates `/etc/hostname` as a symlink to that file. A static tmpfiles
rule creates the persistent source with `blueserver-0` only if it does not
exist. An operator-provided `tmpfiles.extra` credential can replace it before
first boot with a selected hostname:

```text
f+~ /var/lib/bluefin-server/hostname 0644 root root - Ymx1ZXNlcnZlci0xCg==
```

The base64 payload in this example is `blueserver-1\n`. The hostname
application service validates the stored value as a lower-case hostname before
calling `hostnamectl set-hostname --static`. It runs after `/var` and tmpfiles
setup, and before the network and resolver services. If validation fails, the
service fails visibly and leaves networking available for local diagnosis; it
does not substitute or silently generate a different hostname.

Because `/etc/hostname` points at the persistent source, an authenticated
operator may use `sudo hostnamectl set-hostname --static blueserver-1` to
rename an appliance. The change survives reboot and OS DDI replacement.

## DNS and Discovery Plan

Bluefin uses `systemd-resolved` and standards-based multicast DNS, not a local
DNS authority:

1. Enable `systemd-resolved.service` in the installed OS and make
   `/etc/resolv.conf` point at its local stub resolver.
2. Set `MulticastDNS=yes` and `LLMNR=no` on the existing wired
   `systemd-networkd` profile. mDNS is required for `.local`; LLMNR is neither
   needed nor desirable on an appliance network.
3. Set `MulticastDNS=yes` in resolved configuration as the explicit global
   policy.
4. Announce and resolve the static hostname as `<hostname>.local`; no search
   domain or unicast DNS zone is configured.

This works without router configuration on clients whose system resolver
supports mDNS. The appliance documentation will identify
`https://blueserver-0.local:8080/` as the first-appliance URL. The existing
local TLS wildcard certificate coverage remains compatible with named
`.local` access.

## Bash Prompt

Add FSDK's `bash-config` component so `/etc/bashrc` loads
`/etc/profile.d/*.sh` for interactive Bash sessions. A small profile hook sets
the following prompt only when `PS1` is present:

```bash
PS1='\u\[\e[1;34m\]@\[\e[0m\]\h:\w\$ '
```

It renders, for example:

```text
core@blueserver-0:~$
```

Only the `@` is bright blue. `\h` tracks the live system hostname, `\w`
retains working-directory context, and `\$` renders `$` for `core` and `#`
after `sudo -i`.

## Console Experience

The installed OS console issue banner uses systemd's hostname escape rather
than the address-derived IP escape. It directs an operator to:

```text
KubeStellar Console: https://<hostname>.local:8080/
```

At runtime, a device named `blueserver-0` therefore displays
`https://blueserver-0.local:8080/`.

## Failure Handling

- An invalid supplied hostname fails the hostname service visibly; networking
  is not blocked.
- A duplicate hostname is not renamed automatically. mDNS collision symptoms
  require the operator to select a different persistent hostname.
- If `systemd-resolved` is unavailable, normal DNS resolution must fail
  visibly through the service dependency rather than falling back to a
  hand-written resolver file.
- The hostname and mDNS controls apply only to the installed OS, not the
  Installer environment.

## Verification

Focused tests will assert the default and credential hostname rules, hostname
validation and service ordering, resolver enablement and mDNS/LLMNR policy,
the `/etc/resolv.conf` and `/etc/hostname` links, the console `.local` URL,
and the exact color-safe prompt definition. A QEMU smoke test will confirm
that a default installation announces and resolves `blueserver-0.local` after
DHCP is ready.

## References

- `systemd.network(5)`:
  <https://www.freedesktop.org/software/systemd/man/latest/systemd.network.html>
- `systemd-resolved.service(8)`:
  <https://www.freedesktop.org/software/systemd/man/latest/systemd-resolved.service.html>
- `tmpfiles.d(5)`:
  <https://www.freedesktop.org/software/systemd/man/latest/tmpfiles.d.html>
