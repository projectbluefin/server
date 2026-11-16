kind: manual

description: |
  Install first-boot systemd credential provisioning contracts into the target OS.
  Supports sysusers credentials, systemd-network-generator network.* credentials,
  and the firstboot.* credentials (locale, keymap, timezone, hostname).

  The systemd-firstboot.service drop-in removes upstream's interactive root
  password prompt: root ships locked, so without it every headless boot would
  wait on the console. The passwd.*.root credentials still apply.

  systemd-firstboot also reads the firstboot.* credentials, but writes each
  file only when it does not exist yet and takes firstboot.hostname only
  when no static hostname is set. /usr/libexec/bluefin-firstboot-credentials
  (bluefin-host, os-host.bst) applies them unconditionally: the same files
  in the same format (/etc/locale.conf, /etc/vconsole.conf, /etc/localtime),
  plus /etc/hostname and the live kernel hostname, so the first DHCP request
  carries the name. Neither is ordered against the other; both take the
  values from the same credentials, so the order does not change the result.

  bluefin-hostname.service runs /usr/libexec/bluefin-hostname (bluefin-host)
  on first boot after those: a node whose static hostname is still unset or
  "localhost" gets the firstboot.hostname or system.hostname credential, or
  else bluefin-<first 8 hex of the machine ID>, as its static hostname, so
  appliances on one LAN never share an mDNS name. An invalid provisioned
  hostname fails the unit instead of being replaced.

  /usr/libexec/bluefin-homelab-install and its unit run on the USB installer
  only, booted from a Homelab entry (the bluefin.install-homelab credential):
  they hand systemd-sysinstall the Homelab template, the sysexts on the
  stick and, for a node, the join passphrase asked on the console.

  /usr/libexec/bluefin-installer-secure-boot and its unit also run on the USB
  installer only, required by systemd-sysinstall.service and the Homelab
  unit: Secure Boot on with the stick's keys continues, anything else is
  explained on the console and cancels unless the operator (or, unattended,
  the bluefin.install-allow-insecure-boot credential) allows it.

  /usr/libexec/bluefin-installer-disk and bluefin-installer-done, and their
  units, also run on the USB installer only: the target-disk question with
  each disk's size and model before systemd-sysinstall, and the "installed,
  restarting" screen after it.

  /usr/libexec/bluefin-root-password-prompt runs on the first boot of a disk
  the USB installer wrote (bluefin-root-password-prompt.service): stock
  systemd-firstboot --prompt-root-password, asked again until root has a
  password.

build-depends:
  - base/base-stack.bst

sources:
  - kind: local
    path: files/os/sysusers.d
    directory: sysusers-src
  - kind: local
    path: files/os/creds/systemd/system
    directory: systemd-src
  - kind: local
    path: files/os/libexec
    directory: libexec-src

# Disable binary stripping; this element only installs text files and the
# runtime-minimal sandbox does not include the stripper toolchain.
variables:
  strip-binaries: ""

config:
  install-commands:
    - |
      set -euo pipefail

      install -Dm0644 sysusers-src/*.conf -t "%{install-root}/usr/lib/sysusers.d/"
      mkdir -p "%{install-root}/usr/lib/systemd/system"
      cp -a systemd-src/. "%{install-root}/usr/lib/systemd/system/"
      install -Dm0755 libexec-src/bluefin-homelab-install \
        "%{install-root}/usr/libexec/bluefin-homelab-install"
      install -Dm0755 libexec-src/bluefin-home-server-install \
        "%{install-root}/usr/libexec/bluefin-home-server-install"
      install -Dm0755 libexec-src/bluefin-installer-secure-boot \
        "%{install-root}/usr/libexec/bluefin-installer-secure-boot"
      install -Dm0755 libexec-src/bluefin-installer-disk \
        "%{install-root}/usr/libexec/bluefin-installer-disk"
      install -Dm0755 libexec-src/bluefin-installer-done \
        "%{install-root}/usr/libexec/bluefin-installer-done"
      install -Dm0755 libexec-src/bluefin-root-password-prompt \
        "%{install-root}/usr/libexec/bluefin-root-password-prompt"
