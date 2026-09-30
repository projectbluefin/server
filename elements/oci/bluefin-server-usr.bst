kind: script
description: |
  Bluefin Server /usr image: a discoverable disk image (UAPI.3 DDI) with an
  erofs usr partition and its dm-verity hash partition, built offline by
  systemd-repart. /etc holds no image content: its defaults live in
  /usr/share/factory/etc and are copied in by systemd-tmpfiles. A diskless
  node keeps /etc on tmpfs, so it starts empty every boot; a disk install
  keeps it on the root partition, where it persists across A/B updates.

  Outputs (assembled into the full DDI by bluefin-server-image.bst):
    bluefin-server_<ver>.usr.raw          erofs usr partition (sysupdate source)
    bluefin-server_<ver>.usr-verity.raw   dm-verity hash partition (sysupdate source)
    bluefin-server_<ver>.usrhash          dm-verity root hash, baked into the UKIs

  Partition labels are bluefin_usr_<ver> / bluefin_usr_verity_<ver>: the
  disk UKI finds its slot by label and sysupdate matches the same pattern.
  GPT labels hold at most 36 characters, so keep them short.

(@):
- include/image.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- freedesktop-sdk.bst:components/erofs-utils.bst
- freedesktop-sdk.bst:components/fakecap.bst
- freedesktop-sdk.bst:components/findutils.bst
- freedesktop-sdk.bst:components/jq.bst
- freedesktop-sdk.bst:components/sed.bst
- freedesktop-sdk.bst:components/systemd.bst
- bluefin-server/os-initial-scripts.bst
- filename: bluefin-server/os-filesystem.bst
  config:
    location: /sysroot

environment:
  LD_PRELOAD: /usr/libexec/fakecap/fakecap.so
  FAKECAP_DB: /fakecap

variables:
  image-name: bluefin-server_%{image-version}
  usr-label: bluefin_usr_%{image-version}
  usr-verity-label: bluefin_usr_verity_%{image-version}

config:
  commands:
  - mkdir -p /fakecap /tmp /var/tmp

  - |
    set -eu
    for script in /etc/fdsdk/initial_scripts/*; do
      [ -e "${script}" ] || break
      echo "Running initial script $(basename "${script}")"
      "${script}" /sysroot
    done

  - |
    set -eu
    systemd-sysusers --root=/sysroot
    chmod 0600 /sysroot/etc/shadow /sysroot/etc/gshadow
    # No shipped password: root is locked. "!unprovisioned" is systemd's
    # marker for a root account nobody has configured yet; login, su and
    # sulogin treat it as locked, and systemd-firstboot still applies a
    # passwd.hashed-password.root / passwd.plaintext-password.root
    # credential over it (docs/skills/tpm2-credential-sealing.md).
    sed -i '/^root:/d' /sysroot/etc/shadow
    printf 'root:!unprovisioned:::::::\n' >> /sysroot/etc/shadow
    grep -q '^root:' /sysroot/etc/passwd
    chmod 0400 /sysroot/etc/shadow /sysroot/etc/gshadow

    mkdir -p /sysroot/etc/systemd/system /sysroot/etc/systemd/journald.conf.d /sysroot/etc/sysctl.d
    # Headless: homed-firstboot would block the console asking for a user.
    ln -sf /dev/null /sysroot/etc/systemd/system/systemd-homed-firstboot.service
    # The initrd's import.pull credential (local name "rootdisk") stays in
    # /run/credentials after switch-root; keep the host from re-running it.
    # /etc is the only unit directory that outranks generator output.
    ln -sf /dev/null /sysroot/etc/systemd/system/systemd-import@var-lib-machines-rootdisk.raw.service
    ln -sf /dev/null /sysroot/etc/systemd/system/systemd-loop@var-lib-machines-rootdisk.raw.service
    printf '[Journal]\nForwardToConsole=no\nMaxLevelConsole=warning\n' > /sysroot/etc/systemd/journald.conf.d/10-console.conf
    printf 'kernel.printk = 3 4 1 3\n' > /sysroot/etc/sysctl.d/10-console.conf
    printf 'LANG=C.UTF-8\n' > /sysroot/etc/locale.conf
    ln -sf ../usr/share/zoneinfo/UTC /sysroot/etc/localtime
    rm -f /sysroot/etc/machine-id

  - |
    set -eu
    factory=/sysroot/usr/share/factory/etc
    rm -rf "${factory}"
    mkdir -p "$(dirname "${factory}")"
    mv /sysroot/etc "${factory}"
    mkdir /sysroot/etc
    conf=/sysroot/usr/lib/tmpfiles.d/00-bluefin-factory-etc.conf
    printf 'd /etc 0755 root root -\n' > "${conf}"
    for entry in $(ls -A "${factory}"); do
      if [ -L "${factory}/${entry}" ]; then
        printf 'L /etc/%s - - - - %s\n' "${entry}" "$(readlink "${factory}/${entry}")" >> "${conf}"
      else
        printf 'C /etc/%s - - - - %s\n' "${entry}" "/usr/share/factory/etc/${entry}" >> "${conf}"
      fi
    done
    echo "Factory /etc entries: $(wc -l < "${conf}")"

  - |
    set -eu
    # BuildStream records no directory modes and the sandbox umask is 0, so
    # staged directories and the files written above come out group- and
    # world-writable. /etc is copied from the factory tree with its modes,
    # which would let any local user rewrite /etc/sudoers.d or unit files.
    # Clear group/other write on everything but sticky directories.
    factory=/sysroot/usr/share/factory/etc
    # tmpfiles C only copies what is missing, and a disk install keeps /etc
    # across A/B updates, so a fixed image does not by itself fix a node
    # installed from an older one. Record what needs repairing there; the
    # one-shot unit below clears the same bits on the node's next boot.
    # A z line would do it too, but z asserts the factory mode on *every*
    # boot and would undo an operator's own tightening of, say, a
    # sshd_config.d drop-in; chmod go-w only ever removes access.
    mkdir -p /sysroot/usr/lib/bluefin /sysroot/usr/libexec
    list=/sysroot/usr/lib/bluefin/etc-mode-repair.list
    find "${factory}" -mindepth 1 \( -type d ! -perm -1000 -o -type f \) -perm /022 -printf '%P\n' | LC_ALL=C sort > "${list}"

    cat > /sysroot/usr/libexec/bluefin-repair-etc-modes <<'EOF'
    #!/usr/bin/bash
    # bluefin-repair-etc-modes — one-shot repair of /etc modes on nodes
    # installed from an image built before the sysroot modes were fixed.
    #
    # Only clears group/other write. It never widens a mode and never
    # re-asserts a factory mode, so an operator who tightened a path keeps
    # their mode. Runs once; a stamp in /var suppresses later boots.
    set -euo pipefail
    list=/usr/lib/bluefin/etc-mode-repair.list
    stamp=/var/lib/bluefin/etc-mode-repair.stamp
    repaired=0
    while IFS= read -r rel; do
        path="/etc/${rel}"
        # Skip what the node no longer has, symlinks (chmod would follow
        # them out of /etc) and sticky dirs, which are meant to be 1777.
        if [ ! -e "${path}" ] || [ -L "${path}" ] || [ -k "${path}" ]; then
            continue
        fi
        chmod go-w "${path}"
        repaired=$(( repaired + 1 ))
    done < "${list}"
    mkdir -p "$(dirname "${stamp}")"
    : > "${stamp}"
    echo "Cleared group/other write from ${repaired} path(s) under /etc"
    EOF
    chmod 0755 /sysroot/usr/libexec/bluefin-repair-etc-modes

    unit=/sysroot/usr/lib/systemd/system/bluefin-repair-etc-modes.service
    cat > "${unit}" <<'EOF'
    [Unit]
    Description=Clear group/other write from /etc paths left by older images
    Documentation=file:/usr/libexec/bluefin-repair-etc-modes
    ConditionPathExists=!/var/lib/bluefin/etc-mode-repair.stamp
    ConditionPathExists=/usr/lib/bluefin/etc-mode-repair.list
    After=systemd-tmpfiles-setup.service
    # Finish before anything can log in and before sshd reads its drop-ins.
    Before=systemd-user-sessions.service sshd.service

    [Service]
    Type=oneshot
    RemainAfterExit=yes
    ExecStart=/usr/libexec/bluefin-repair-etc-modes

    [Install]
    WantedBy=multi-user.target
    EOF
    mkdir -p /sysroot/usr/lib/systemd/system/multi-user.target.wants
    ln -sf ../bluefin-repair-etc-modes.service \
      /sysroot/usr/lib/systemd/system/multi-user.target.wants/bluefin-repair-etc-modes.service

    find /sysroot \( -type d ! -perm -1000 -o -type f \) -perm /022 -exec chmod go-w {} +
    echo "Cleared group/other write; /etc paths to repair in place: $(wc -l < "${list}")"

  - |
    set -eu
    mkdir -p /tmp/repart.d
    cat > /tmp/repart.d/10-usr.conf <<EOF
    [Partition]
    Type=usr
    Label=%{usr-label}
    Format=erofs
    Compression=lz4hc
    CopyFiles=/usr:/
    Verity=data
    VerityMatchKey=usr
    Minimize=best
    SplitName=usr
    EOF
    cat > /tmp/repart.d/20-usr-verity.conf <<EOF
    [Partition]
    Type=usr-verity
    Label=%{usr-verity-label}
    Verity=hash
    VerityMatchKey=usr
    Minimize=best
    SplitName=usr-verity
    EOF

  - |
    set -eu
    cd "%{install-root}"
    systemd-repart \
      --empty=create --size=auto --offline=yes --dry-run=no \
      --seed=6f1b0fe2-3c2a-4f2e-9f0a-b1e5e7a5e001 \
      --root=/sysroot --definitions=/tmp/repart.d \
      --split=yes --json=short \
      "%{image-name}.raw" > /tmp/repart.json
    jq . /tmp/repart.json
    jq -r '.[] | select(.type | startswith("usr-") and endswith("-verity") | not) | select(.roothash != null) | .roothash' /tmp/repart.json | head -n1 > "%{image-name}.usrhash"
    if [ ! -s "%{image-name}.usrhash" ]; then
      jq -r '[.[] | .roothash | select(. != null and . != "")][0]' /tmp/repart.json > "%{image-name}.usrhash"
    fi
    grep -Eq '^[0-9a-f]{64}$' "%{image-name}.usrhash"
    echo "usrhash: $(cat "%{image-name}.usrhash")"
    rm -f "%{image-name}.raw"
    ls -l
