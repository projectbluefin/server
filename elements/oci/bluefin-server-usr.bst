kind: script
description: |
  Bluefin Server /usr image: a discoverable disk image (UAPI.3 DDI) with an
  erofs usr partition and its dm-verity hash partition, built offline by
  systemd-repart. /etc is empty on every boot; its defaults live in
  /usr/share/factory/etc and are copied in by systemd-tmpfiles.

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
    conf=/sysroot/usr/lib/tmpfiles.d/00-bluefin-factory-etc.conf
    find "${factory}" -mindepth 1 \( -type d ! -perm -1000 -o -type f \) -perm /022 -printf '%P\n' | sort > /tmp/etc-writable
    find /sysroot \( -type d ! -perm -1000 -o -type f \) -perm /022 -exec chmod go-w {} +
    # C only copies what is missing and /etc persists across updates, so
    # repair the copies earlier images installed in place.
    while IFS= read -r rel; do
      printf 'z /etc/%s %s - - -\n' "${rel}" "$(stat -c %04a "${factory}/${rel}")" >> "${conf}"
    done < /tmp/etc-writable
    echo "Cleared group/other write; /etc paths repaired in place: $(wc -l < /tmp/etc-writable)"

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
