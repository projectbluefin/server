kind: manual
description: |
  Install the Bluefin Server sshd policy drop-in (key-only authentication,
  no password or keyboard-interactive root login) under the vendor prefix
  and wire it into the effective sshd configuration.

  Image-native layout: vendor configuration ships read-only under
  /usr/etc; /etc stays operator-owned and mutable. Upstream OpenSSH —
  and therefore the FSDK openssh component — compiles its default config
  path in at build time (/etc/ssh/sshd_config) with no /usr/etc support and
  no search path, and the FSDK sshd.service runs plain `sshd -D`. The
  merged vendor config is therefore reachable only through a shim at the
  compiled-in path: this element replaces /etc/ssh/sshd_config with a
  relative symlink to /usr/etc/ssh/sshd_config. That symlink is the single,
  documented /etc artifact of this repo's SSH policy — "single" scopes to
  the sshd wiring, not to all package content in the image; an operator
  may replace it with a regular file to fully own the sshd configuration. A `-f` unit override was
  rejected instead: it would leave FSDK's stock /etc/ssh/sshd_config present
  but silently inert for anyone editing the documented default path.

  The merged vendor config is a build-time copy of the real staged FSDK
  sshd_config (never a static copy vendored in this repo). sshd uses
  first-match-wins, so the Includes are prepended in precedence order:
  operator drop-ins in /etc/ssh/sshd_config.d/*.conf first (including
  systemd's userdb wiring), then the vendor drop-in dir
  /usr/etc/ssh/sshd_config.d/, then the stock body. The overlap on
  /etc/ssh/sshd_config is declared so this shim wins when composed.

  sshd.service stays disabled by default via the FSDK openssh.preset; an
  operator enables it explicitly after provisioning an authorized key.

build-depends:
  # bash and coreutils are build-only dependencies for this sandbox.
  - freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
  # Stages the real upstream /etc/ssh/sshd_config into the build sandbox
  # so it can be transformed.
  - freedesktop-sdk.bst:components/openssh-systemd.bst

# Runtime dependency on openssh-systemd guarantees deterministic staging
# order: this element stages after OpenSSH, so its /etc/ssh/sshd_config shim
# wins the overlap in composed rootfs trees.
depends:
  - freedesktop-sdk.bst:components/openssh-systemd.bst

# Text-only element; the build sandbox has no stripper toolchain.
variables:
  strip-binaries: ''

sources:
  - kind: local
    path: files/os/ssh/sshd_config.d

config:
  install-commands:
    - |
      # A `local` source stages the *contents* of its directory, so the
      # drop-in lands in the sandbox CWD under its bare filename.
      install -Dm644 -t "%{install-root}%{prefix}/etc/ssh/sshd_config.d" \
        bluefin-server.conf
    - |
      set -eu
      src="%{sysconfdir}/ssh/sshd_config"
      dest="%{install-root}%{prefix}/etc/ssh/sshd_config"
      have_include=0
      while read -r line; do
        case "${line}" in
          *[[:space:]]/usr/etc/ssh/sshd_config.d/*) have_include=1; break ;;
        esac
      done < "${src}"
      mkdir -p "%{install-root}%{prefix}/etc"
      if [ "${have_include}" -eq 1 ]; then
        # Impossible today (the vendor drop-in dir is this repo's
        # invention); kept so a future refactor does not double-include.
        cat "${src}" > "${dest}"
      else
        # First-match-wins: operator drop-ins precede systemd's
        # Operator drop-ins (including systemd's userdb wiring) precede
        # vendor drop-ins, and both precede every stock directive they override.
        {
          echo 'Include /etc/ssh/sshd_config.d/*.conf'
          echo 'Include /usr/etc/ssh/sshd_config.d/*.conf'
          echo
          cat "${src}"
        } > "${dest}"
      fi
      chmod 644 "${dest}"
    - |
      # Compatibility shim: sshd's default config path is compiled in as
      # /etc/ssh/sshd_config (no /usr/etc support upstream; the FSDK unit
      # passes no -f), so the vendor config is reachable only through
      # this symlink. Relative so it resolves inside any composed rootfs.
      mkdir -p "%{install-root}%{sysconfdir}/ssh"
      ln -sfn ../../usr/etc/ssh/sshd_config "%{install-root}%{sysconfdir}/ssh/sshd_config"

public:
  bst:
    # Deliberately replaces the OpenSSH sshd_config with the /usr/etc shim
    # (same pattern as FSDK ldconfig.bst -> ld.so.conf).
    overlap-whitelist:
      - "%{sysconfdir}/ssh/sshd_config"
