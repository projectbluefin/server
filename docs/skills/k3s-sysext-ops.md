---
name: k3s-sysext-ops
description: Enable, test, and troubleshoot the k3s systemd-sysext after it is built and published.
metadata:
  type: how-to
  status: stable
  last_updated: 2026-07-20
  context7-sources:
    - /systemd/systemd
---
# k3s sysext Operations

Use this skill when you need to enable the k3s sysext on a host, troubleshoot
runtime issues, or validate the sysext and OTA delivery path.

## Enabling k3s on a host

Because the OS image has no shell and `/usr` is read-only, role selection is
performed with systemd unit enablement and a drop-in config file rather than by
running the upstream installer script.

### Server

1. Write the server token and any role-specific settings to
   `/etc/rancher/k3s/config.yaml`.
2. Enable the server unit:
   ```bash
   systemctl enable k3s.service
   ```
3. Reboot or start `k3s.service`.

### Agent

1. Write the agent config to `/etc/rancher/k3s/config.yaml`, including at least
   `server:` and `token:`.
2. Enable the agent unit:
   ```bash
   systemctl enable k3s-agent.service
   ```
3. Reboot or start `k3s-agent.service`.

The tuning defaults from `50-bluefin-tuning.yaml` are copied into
`/etc/rancher/k3s/config.yaml.d/` on first boot by the tmpfiles rule. They are
not merged by k3s; they are plain YAML files in the config directory.

## Common gotchas

- **Neither unit is enabled by default.** Both services are shipped in `/usr`
  inside the sysext but no symlink is created in the default target's `wants.d`.
- **No shell in the OS image.** `k3s.service` no longer runs a `/bin/sh`
  `ExecStartPre` check.
- **No shell means no `curl | sh`.** Do not try to use the upstream k3s install
  script. Use unit enablement and `/etc/rancher/k3s/config.yaml` instead.
- **Tuning defaults live in `/usr` and are copied, not merged.** The tmpfiles
  rule creates an `/etc` copy only if one does not already exist.
- **Role-specific environment files are optional.** Both units may source
  `/etc/default/%N`, `/etc/sysconfig/%N`, and `/etc/systemd/system/%N.env`.
- **`ID=_any` in `extension-release.k3s`.** The sysext merges on any host image.
  If you scope it to a specific OS version, update both the metadata and the base
  OS `os-release`.
- **The base DDI does not include k3s.** k3s is delivered OTA or dropped into
  `/var/lib/extensions/` by provisioning.

## Runtime testing without a lab VM

### OTA discovery and download (systemd-sysupdate)

Copy `files/os/sysupdate.d/70-k3s.transfer` into a scratch `sysupdate.d/`,
rewrite only the `[Target] Path=` to a scratch directory, then run inside a
Fedora container:

```bash
podman run --rm -v "$SCRATCH:/scratch:z" quay.io/fedora/fedora:latest bash -c '
  dnf -yq install systemd-udev systemd-container >/dev/null
  /usr/lib/systemd/systemd-sysupdate --definitions=/scratch/sysupdate.d list
  /usr/lib/systemd/systemd-sysupdate --definitions=/scratch/sysupdate.d update'
```

- `systemd-sysupdate` is in `systemd-udev`; the `systemd-pull` helper needed for
  `url-file` sources is in `systemd-container`.
- For the full trust chain, copy `files/os/sysupdate-keys/import-pubring.pgp`
  to `/usr/lib/systemd/import-pubring.pgp` inside the container.

### Sysext merge and unit checks

```bash
podman run -d --name sysext-test --privileged --cgroupns=host \
  -v "$SCRATCH:/test:z" quay.io/fedora/fedora:latest \
  bash -c 'dnf install -y systemd erofs-utils && exec /usr/sbin/init'
podman exec sysext-test bash -c '
  mount --make-shared /usr && mount --make-shared /opt
  erofsfuse /test/k3s.raw /mnt && cp -a /mnt/. /var/lib/extensions/k3s/
  systemd-sysext merge && systemd-sysext status
  k3s --version
  systemd-tmpfiles --create
  cat /etc/rancher/k3s/config.yaml.d/50-bluefin-tuning.yaml
  systemctl list-unit-files | grep k3s'
```

- Rootless podman cannot loop-mount the `.raw` directly; extract via
  `erofsfuse` into a `/var/lib/extensions/<name>/` directory instead.
- `systemd-sysext merge` needs `/usr` and `/opt` to be shared mount points.
- `systemctl start k3s` in a nested container can fail for environmental reasons;
  full startup verification still needs a real VM or bare metal.

## Verification

- [ ] `elements/k3s/k3s-bin.bst` uses a real upstream k3s release URL and a
      matching SHA256.
- [ ] `files/k3s/sysext/extension-release.k3s` has `ID=_any`.
- [ ] Both `k3s.service` and `k3s-agent.service` are present and neither is
      enabled by default.
- [ ] `k3s.service` uses `/sbin/modprobe` `ExecStartPre` lines, not `/bin/sh`.
- [ ] `files/k3s/sysext/k3s-bluefin.conf` seeds tuning defaults with a `C+`
      line targeting `/etc/rancher/k3s/config.yaml.d/`.
- [ ] `files/os/sysupdate.d/70-k3s.transfer` uses a static `Path=` and OS-release
      `@v` patterns plus `CurrentSymlink=k3s.raw`.
- [ ] `just validate` resolves the element graph after any k3s version bump.
- [ ] `just build-sysext && just export-sysext` produces the expected files.
