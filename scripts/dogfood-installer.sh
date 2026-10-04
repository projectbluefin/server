#!/usr/bin/env bash
# End-to-end check of the offline USB installer in QEMU with Secure Boot:
#   1. boot bluefin-server-installer_<ver>.raw once so systemd-boot enrolls
#      the dev keys (secure-boot-enroll if-safe)
#   2. boot it with the target disk (blank, or not empty: DOGFOOD_TARGET) and
#      no network; the shipped systemd-sysinstall.service runs unattended,
#      erases the disk, installs exactly the ESP and usr slot A (+ verity),
#      and reboots
#   3. boot the target disk on its own: /usr must come from its
#      bluefin_usr_<ver> slot, the first boot creates slot B and the xfs root,
#      and no unit may fail
#   4. boot the target again with the installer still attached: /usr must
#      still come from the target, never from the installer's
#      bluefin-installer-usr partition
#   with <next> (the out-of-the-box update contract):
#   5. boot the target with a network: the update timers are on, the keyring
#      is the image's, and the login banner shows the version and "never"
#      checked. systemd-sysupdate.service (the unit the timer starts) must
#      then fail against an unreachable source and against a set signed by a
#      foreign key, each a failed unit and a banner error line, and finally
#      stage <next> from a local HTTP server; the banner shows it staged
#   6. boot the target: it must run <next> from slot B, bless the
#      boot-counted UKI, and the banner must show <next> with the persisted
#      last check and no error
#   DOGFOOD_TARGET=prior-install (no <next>) instead adds:
#   5. install again from the stick onto that installed disk (ESP, both usr
#      slots, xfs root), which must erase it like a blank one (#359)
#   6. boot the reinstalled disk: a new root (boot 1), and step 3's checks
#   <next> is an image set with a higher version signed by the same key (dev
#   keys locally, as in CI), or "release": the transfers stay on the image's
#   own source (GitHub Releases) and the newest release must be found, staged
#   and booted; only an official stick proves the official contract this way.
#
# The kernel still has partition devices for a disk that is not empty when
# systemd-repart erases it; stock v261 then fails with "Device or resource
# busy" after wiping the disk (#359); the image's
# 90-bluefin-installer-forget-partitions.rules udev rule works around it.
#
# systemd-sysinstall is interactive on /dev/console. The test makes it
# unattended with a systemd.unit-dropin.systemd-sysinstall.service SMBIOS
# credential (installed as 50-credential.conf, after the image's
# 10-bluefin-installer.conf) that re-runs the image drop-in's ExecStart= with
# the target disk and --confirm=no appended (the image drop-in already passes
# --erase=yes --variables=yes), and with StandardInput=null: no prompt is left
# (the image drop-in also skips the erase question and reboots via
# SuccessAction=), so any prompt a regression adds fails at once instead of
# hanging.
#
# Usage: dogfood-installer.sh <dir with bluefin-server-installer_<ver>.raw> [<next dir>|release]
# Environment:
#   DOGFOOD_PORT=<port>        HTTP port serving <next> (default 8765)
#   DOGFOOD_STATE=<dir>        logs, target disk and UEFI vars (default dist/dogfood-installer)
#   DOGFOOD_TARGET_DISK=<file> target disk image, recreated (default <state>/target.raw)
#   DOGFOOD_TARGET=<kind>      what the target holds before the install:
#                              blank (default); foreign-gpt (another OS: GPT
#                              with a vfat ESP, ext4 /boot, swap, ext4 root);
#                              ext4 or xfs (one filesystem on the whole disk,
#                              no partition table); prior-install (steps 5-6:
#                              reinstall over the Bluefin install of steps 2-4;
#                              not with <next>)
#   DOGFOOD_TARGET_DEV=<path>  target device the installer is told to use
#                              (default /dev/disk/by-id/virtio-bluefin-target)
#   DOGFOOD_SYSINSTALL_ARGS=.. extra systemd-sysinstall arguments
#                              (default --confirm=no)
#   DOGFOOD_SYSINSTALL_CRED=0  do not pass the unattended drop-in credential
#   DOGFOOD_MEM=<MiB>          guest memory (default 4096)
#   DOGFOOD_TIMEOUT=<s>        per-boot timeout (default 600)
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
dir="$(realpath "${1:?usage: $0 <artifact dir> [<next dir>|release]}")"
next="${2:-}"
next_ver=""
case "${next}" in
    "" | release) ;;
    *)
        next="$(realpath "${next}")"
        for f in "${next}"/bluefin-server-[0-9]*.efi; do
            [ -e "${f}" ] && { next_ver="${f##*/bluefin-server-}"; next_ver="${next_ver%.efi}"; }
        done
        [ -n "${next_ver}" ] || { echo "ERROR: no bluefin-server-<ver>.efi in ${next}" >&2; exit 1; } ;;
esac
port="${DOGFOOD_PORT:-8765}"
target_kind="${DOGFOOD_TARGET:-blank}"
case "${target_kind}" in
    blank|foreign-gpt|ext4|xfs|prior-install) ;;
    *) echo "ERROR: DOGFOOD_TARGET must be blank, foreign-gpt, ext4, xfs or prior-install, not '${target_kind}'" >&2; exit 1 ;;
esac
[ "${target_kind}" != prior-install ] || [ -z "${next}" ] \
    || { echo "ERROR: DOGFOOD_TARGET=prior-install does not combine with <next>" >&2; exit 1; }
steps=4
[ -z "${next}" ] || steps=6
[ "${target_kind}" != prior-install ] || steps=6
state="$(realpath -m "${DOGFOOD_STATE:-dist/dogfood-installer}")"
mem="${DOGFOOD_MEM:-4096}"
timeout_s="${DOGFOOD_TIMEOUT:-600}"
target_serial=bluefin-target
target_dev="${DOGFOOD_TARGET_DEV:-/dev/disk/by-id/virtio-${target_serial}}"
install_args="${DOGFOOD_SYSINSTALL_ARGS:---confirm=no}"
dropin_src="${here}/../files/os/systemd/system/systemd-sysinstall.service.d/10-bluefin-installer.conf"

installer="$(ls "${dir}"/bluefin-server-installer_*.raw 2>/dev/null | tail -n1)" \
    || { echo "ERROR: no bluefin-server-installer_<ver>.raw in ${dir}" >&2; exit 1; }
ver="${installer##*/bluefin-server-installer_}"; ver="${ver%.raw}"

first_existing() { for f in "$@"; do [ -f "$f" ] && { echo "$f"; return 0; }; done; return 1; }
code="${OVMF_CODE:-$(first_existing \
    /usr/share/edk2/ovmf/OVMF_CODE.secboot.fd \
    /usr/share/OVMF/OVMF_CODE_4M.secboot.fd \
    /usr/share/OVMF/OVMF_CODE.secboot.fd \
    /usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd)}" || { echo "ERROR: no Secure Boot OVMF_CODE found (set OVMF_CODE)" >&2; exit 1; }
vars_tmpl="${OVMF_VARS:-$(first_existing \
    /usr/share/edk2/ovmf/OVMF_VARS.fd \
    /usr/share/OVMF/OVMF_VARS_4M.fd \
    /usr/share/OVMF/OVMF_VARS.fd \
    /usr/share/edk2/x64/OVMF_VARS.4m.fd)}" || { echo "ERROR: no blank OVMF_VARS found (set OVMF_VARS)" >&2; exit 1; }

rm -rf "${state}"
mkdir -p "${state}"
target="${DOGFOOD_TARGET_DISK:-${state}/target.raw}"
[ -b "${target}" ] && { echo "ERROR: ${target} is a block device; use a disk image file" >&2; exit 1; }
rm -f "${target}"
truncate -s 16G "${target}"
vars="${state}/vars.fd"
cp "${vars_tmpl}" "${vars}"

fail() {
    echo "FAIL: $* (logs: ${state})" >&2
    exit 1
}

# put_fs <start MiB> <size MiB> <mkfs command...>: make a filesystem in a
# scratch file and write it into the target at that offset.
put_fs() {
    local start="$1" size="$2" img="${state}/part.img"; shift 2
    rm -f "${img}"
    truncate -s "${size}M" "${img}"
    chmod 0600 "${img}"
    "$@" "${img}" >/dev/null 2>"${state}/part.err" || { cat "${state}/part.err" >&2; fail "$*"; }
    dd if="${img}" of="${target}" bs=1M seek="${start}" conv=notrunc,sparse status=none
    rm -f "${img}"
}

case "${target_kind}" in
    foreign-gpt)
        mkdir -p "${state}/foreign-root/etc"
        printf 'ID=foreign\nNAME="Another OS"\n' > "${state}/foreign-root/etc/os-release"
        sfdisk -q "${target}" <<'EOF'
label: gpt
start=1MiB, size=600MiB, type=uefi, name="EFI System Partition"
start=601MiB, size=1024MiB, type=linux, name=boot
start=1625MiB, size=1024MiB, type=swap, name=swap
start=2649MiB, size=8192MiB, type=linux, name=root
EOF
        put_fs 1 600 mkfs.vfat -F 32 -n EFI
        put_fs 601 1024 mkfs.ext4 -q -F -L boot
        put_fs 1625 1024 mkswap -L swap
        put_fs 2649 8192 mkfs.ext4 -q -F -L root -d "${state}/foreign-root"
        ;;
    ext4) mkfs.ext4 -q -F -L data "${target}" >/dev/null ;;
    xfs) mkfs.xfs -q -f -L data "${target}" >/dev/null ;;
esac
echo "==> target disk: ${target_kind}"
blkid -p "${target}" 2>/dev/null | sed 's/^/    /' || true
sfdisk -l "${target}" 2>/dev/null | sed -n '/^Device/,$p' | sed 's/^/    /' || true

cred() { printf 'type=11,value=io.systemd.credential.binary:%s=%s' "$1" "$(base64 -w0 < "$2")"; }

qemu=(qemu-system-x86_64
    -machine q35,smm=on,accel=kvm -cpu host -m "${mem}" -smp 2
    -global driver=cfi.pflash01,property=secure,value=on
    -drive if=pflash,format=raw,unit=0,readonly=on,file="${code}"
    -drive if=pflash,format=raw,unit=1,file="${vars}"
    -display none -monitor none -no-reboot
    )
# snapshot=on keeps the release artifact untouched.
stick=(-drive "if=none,id=stick,format=raw,snapshot=on,file=${installer}"
       -device virtio-blk-pci,drive=stick,serial=bluefin-installer)
disk=(-drive "if=none,id=target,format=raw,file=${target}"
      -device "virtio-blk-pci,drive=target,serial=${target_serial}")

# boot <name> <done-regex> <qemu args...>: run QEMU until it exits (-no-reboot
# turns every reboot into an exit), <done-regex> shows up in the ttyS1 log,
# or the timeout hits. Serial logs land in ${state}/<name>.*.log.
boot() {
    local name="$1" done_re="$2"; shift 2
    local log="${state}/${name}"
    "${qemu[@]}" "$@" \
        -serial "file:${log}.ttyS0" -serial "file:${log}.ttyS1" -serial "file:${log}.ttyS2" \
        </dev/null >"${log}.qemu.log" 2>&1 &
    local pid=$! deadline=$(( $(date +%s) + timeout_s ))
    while kill -0 "${pid}" 2>/dev/null && [ "$(date +%s)" -lt "${deadline}" ]; do
        # A few seconds of grace so the journal mirror catches up.
        [ -n "${done_re}" ] && grep -aqE "${done_re}" "${log}.ttyS1" 2>/dev/null && { sleep 3; break; }
        sleep 2
    done
    local timed_out=0
    if kill -0 "${pid}" 2>/dev/null; then
        [ "$(date +%s)" -ge "${deadline}" ] && timed_out=1
        kill "${pid}" 2>/dev/null || true
    fi
    wait "${pid}" 2>/dev/null || true
    for s in ttyS0 ttyS1 ttyS2; do
        sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\x1bP[^\x1b]*\x1b\\//g' "${log}.${s}" 2>/dev/null \
            | tr -d '\r' > "${log}.${s}.log" || true
        rm -f "${log}.${s}"
    done
    grep -aoE 'PROBE[ -].*' "${log}.ttyS1.log" || true
    [ "${timed_out}" = 0 ] || { tail -n 40 "${log}.ttyS0.log" >&2; fail "${name}: no result within ${timeout_s}s"; }
}

echo "==> 1/${steps} enroll Secure Boot keys from the installer (${ver})"
boot 1-enroll '' "${stick[@]}" -nic none
grep -aq 'successfully enrolled' "${state}/1-enroll.ttyS0.log" || fail "key enrollment"
# Firmware state right after enrollment: no boot entry for the target yet.
cp "${vars}" "${state}/vars-enrolled.fd"

exec_start="$(sed -n 's/^ExecStart=\(..*\)$/\1/p' "${dropin_src}" | tail -n1)"
[ -n "${exec_start}" ] || fail "no ExecStart= in ${dropin_src}"
cat > "${state}/sysinstall.conf" <<EOF
[Unit]
Wants=dogfood-journal.service

[Service]
StandardInput=null
StandardError=journal+console
ExecStartPre=/bin/bash -c 'lsblk -o NAME,PARTLABEL,FSTYPE,SIZE ${target_dev} | sed "s/^/PROBE-LOG before-install /" >/dev/ttyS1'
ExecStart=
ExecStart=${exec_start} ${install_args} ${target_dev}
ExecStopPost=/bin/bash -c 'exec >/dev/ttyS1 2>&1; echo "PROBE sysinstall=\$\${SERVICE_RESULT} \$\${EXIT_STATUS}"; udevadm settle -t 10 || true; echo "PROBE installed-slot-b=\$\$(lsblk -rno PARTLABEL ${target_dev} | grep -cx _empty) installed-parts=\$\$(lsblk -rno TYPE ${target_dev} | grep -cx part)"; lsblk -o NAME,PARTLABEL,FSTYPE,SIZE ${target_dev} | sed "s/^/PROBE-LOG installed /"'
EOF
cat > "${state}/journal.service" <<'EOF'
[Unit]
Description=Dogfood journal mirror on ttyS2
DefaultDependencies=no
[Service]
ExecStart=journalctl -b -f --no-pager -o short-monotonic
StandardOutput=tty
TTYPath=/dev/ttyS2
EOF
install_creds=(-smbios "$(cred systemd.extra-unit.dogfood-journal.service "${state}/journal.service")")
# systemd-firstboot prompts on the installer console first; answer it the
# unattended way. sysinstall copies locale, keymap and timezone to the target.
for kv in firstboot.locale=C.UTF-8 firstboot.keymap=us firstboot.timezone=UTC 'passwd.hashed-password.root=!*'; do
    printf '%s' "${kv#*=}" > "${state}/${kv%%=*}"
    install_creds+=(-smbios "$(cred "${kv%%=*}" "${state}/${kv%%=*}")")
done
if [ "${DOGFOOD_SYSINSTALL_CRED:-1}" != 0 ]; then
    install_creds+=(-smbios "$(cred systemd.unit-dropin.systemd-sysinstall.service "${state}/sysinstall.conf")")
fi

# run_install <name>: boot the stick with the target attached; sysinstall must
# succeed and leave exactly the ESP and usr slot A (+ verity) on the target.
run_install() {
    local log="${state}/$1.ttyS1.log"
    # Offline (-nic none): the installer must not need a network.
    boot "$1" 'PROBE sysinstall=([^s]|s[^u])' \
        "${stick[@]}" "${disk[@]}" -nic none "${install_creds[@]}"
    grep -aq 'PROBE sysinstall=success' "${log}" \
        || { grep -aE 'sysinstall|repart' "${state}/$1.ttyS2.log" | grep -v audit | tail -n 20 >&2 || true; fail "$1: systemd-sysinstall did not succeed"; }
    grep -aq 'PROBE installed-slot-b=0 installed-parts=3' "${log}" \
        || fail "$1: the target holds more than the ESP and usr slot A (+ verity) before its first boot"
}

echo "==> 2/${steps} offline install onto a ${target_kind} disk: ExecStart=${exec_start} ${install_args} ${target_dev}"
run_install 2-install

{
    printf 'target=/dev/disk/by-id/virtio-%s\n' "${target_serial}"
    cat <<'PROBE'
serial() { cat "/sys/block/$(lsblk -dno PKNAME "$1")/serial" 2>/dev/null; }
banner() {
    echo "PROBE banner-$1=$(tr '\n' '|' < /run/issue.d/40-bluefin-update.issue 2>/dev/null)"
    echo "PROBE motd-$1=$(tr '\n' '|' < /etc/motd 2>/dev/null)"
}
echo "PROBE secureboot=$(bootctl status 2>/dev/null | sed -n 's/.*Secure Boot: *//p' | head -n1)"
echo "PROBE os=$(. /usr/lib/os-release; echo "${IMAGE_ID} ${IMAGE_VERSION}")"
dm="$(basename "$(readlink -f /dev/mapper/usr)")"
for s in /sys/block/"${dm}"/slaves/*; do
    p="/dev/${s##*/}"
    echo "PROBE usr-backing=$(lsblk -dno PARTLABEL "${p}")@$(serial "${p}")"
done
echo "PROBE root=$(findmnt -no FSTYPE /)@$(serial "$(findmnt -no SOURCE /)")"
echo "PROBE slot-b=$(lsblk -rno PARTLABEL "${target}" | grep -cx _empty)"
lsblk -o NAME,PARTLABEL,FSTYPE,SIZE,MOUNTPOINTS | sed 's/^/PROBE-LOG /'
for s in /sys/block/*/serial; do echo "PROBE-LOG $(basename "$(dirname "${s}")") serial=$(cat "${s}")"; done
echo "PROBE timers-enabled=$(systemctl is-enabled systemd-sysupdate.timer systemd-sysupdate-reboot.timer | tr '\n' ' ')"
echo "PROBE keyring=$(sha256sum < /usr/lib/systemd/import-pubring.pgp | cut -d' ' -f1) etc-override=$(test -e /etc/systemd/import-pubring.pgp && echo present || echo none)"
systemctl start boot-complete.target 2>/dev/null || true
echo "PROBE bless=$(/usr/lib/systemd/systemd-bless-boot status 2>/dev/null)"
banner boot
boots=$(( $(cat /var/lib/dogfood-boots 2>/dev/null || echo 0) + 1 ))
echo "${boots}" > /var/lib/dogfood-boots
echo "PROBE boots=${boots}"
sync
echo "PROBE failed=$(systemctl --failed --no-legend | wc -l) $(systemctl --failed --no-legend --plain | cut -d' ' -f1 | tr '\n' ' ')"
PROBE
} > "${state}/probe.sh"
# Appended to the probe of step 5. @SOURCE@ is the local server, or empty to
# keep the image's own source.
cat > "${state}/update.sh" <<'UPDATE'
source_at() {
    mkdir -p /etc/sysupdate.d
    for f in /usr/lib/sysupdate.d/*.transfer; do
        sed -e "s|^Path=https://.*|Path=$1|" "${f}" > "/etc/sysupdate.d/${f##*/}"
    done
}
# check <name>: one run of the unit systemd-sysupdate.timer starts, then wait
# for the bluefin-update-status.service run it triggers.
check() {
    local before rc=0
    before="$(systemctl show -P InvocationID bluefin-update-status.service)"
    systemctl start --wait systemd-sysupdate.service || rc=$?
    for _ in $(seq 60); do
        [ "$(systemctl show -P InvocationID bluefin-update-status.service)" != "${before}" ] \
            && [ "$(systemctl show -P ActiveState bluefin-update-status.service)" != activating ] && break
        sleep 1
    done
    echo "PROBE check-$1=${rc} unit=$(systemctl is-failed systemd-sysupdate.service)"
    journalctl -b -o cat --no-pager -p err "_SYSTEMD_INVOCATION_ID=$(systemctl show -P InvocationID systemd-sysupdate.service)" \
        | sed "s/^/PROBE-LOG $1 error: /"
    banner "$1"
}
if [ -n "@SOURCE@" ]; then
    source_at http://10.0.2.2:9/
    check unreachable
    source_at @SOURCE@/foreign/
    check foreign
    source_at @SOURCE@/next/
fi
timeout 300 systemd-sysupdate list --no-pager 2>&1 | sed 's/^/PROBE-LOG list: /'
echo "PROBE check-new=$(timeout 300 systemd-sysupdate check-new 2>/dev/null)"
check update
ls "$(bootctl -p)"/EFI/Linux | sed 's/^/PROBE-LOG uki: /'
newest="$(ls "$(bootctl -p)"/EFI/Linux | sed -n 's/^bluefin-server-\([^+]*\)+.*\.efi$/\1/p' | sort -V | tail -n1)"
echo "PROBE staged=${newest} pending=$(systemd-sysupdate pending >/dev/null 2>&1 && echo yes || echo no)"
# QEMU is killed right after this line: the staged UKI and the recorded check
# must be on disk first.
sync
echo "PROBE update-done"
UPDATE
# Appended to the probe of step 6: an SSH login through systemd-ssh-generator's
# local socket must print the banner (sshd reads /etc/motd). sshd refuses a
# locked root even for keys, so root gets the unlocked "*" first.
cat > "${state}/ssh.sh" <<'SSH'
usermod -p '*' root
ssh-keygen -q -t ed25519 -N '' -f /run/dogfood-ssh
install -d -m 0700 /root/.ssh
cat /run/dogfood-ssh.pub >> /root/.ssh/authorized_keys
out="$(printf 'exit\n' | timeout 60 ssh -tt -i /run/dogfood-ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@.host 2>&1 | tr -d '\r')"
echo "PROBE ssh-motd=$(printf '%s\n' "${out}" | grep -m1 '^Bluefin Server')"
printf '%s\n' "${out}" | head -n 8 | sed 's/^/PROBE-LOG ssh: /'
SSH
source=""
[ -z "${next_ver}" ] || source="http://10.0.2.2:${port}"
sed -i "s|@SOURCE@|${source}|g" "${state}/update.sh"
cat "${state}/probe.sh" "${state}/update.sh" > "${state}/probe-update.sh"
cat "${state}/probe.sh" "${state}/ssh.sh" > "${state}/probe-updated.sh"
cat > "${state}/probe.service" <<'UNIT'
[Unit]
Description=Dogfood boot probe
After=multi-user.target
[Service]
Type=oneshot
ImportCredential=dogfood.probe
TimeoutStartSec=infinity
StandardOutput=tty
StandardError=tty
TTYPath=/dev/ttyS1
ExecStart=/bin/bash ${CREDENTIALS_DIRECTORY}/dogfood.probe
[Install]
WantedBy=multi-user.target
UNIT
printf '[Unit]\nWants=dogfood-probe.service\n' > "${state}/probe-wants.conf"
# The installed disk asks for a root password on its first boot
# (bluefin-root-password-prompt.service); a passwd credential answers it.
probe_creds() {
    creds=(
        -smbios "$(cred dogfood.probe "$1")"
        -smbios "$(cred systemd.extra-unit.dogfood-probe.service "${state}/probe.service")"
        -smbios "$(cred systemd.unit-dropin.multi-user.target~dogfood-probe "${state}/probe-wants.conf")"
        -smbios "$(cred passwd.hashed-password.root "${state}/passwd.hashed-password.root")"
    )
}
keyring="${dir}/sysupdate-keys/import-pubring.pgp"
[ -f "${keyring}" ] || keyring="${here}/../files/os/sysupdate-keys/import-pubring.gpg"
keyring_sum="$(sha256sum < "${keyring}" | cut -d' ' -f1)"

# check_disk_boot <name> <boot number> <version> <empty slot-B partitions> [failures-expected]
check_disk_boot() {
    local log="${state}/$1.ttyS1.log" serial0="${state}/$1.ttyS0.log" v="$3" b
    grep -aq 'PROBE failed=' "${log}" || fail "$1: probe did not run"
    grep -aq "PROBE os=bluefin-server ${v}" "${log}" || fail "$1: not running ${v}"
    grep -aq "PROBE boots=$2" "${log}" || fail "$1: expected boot $2 of the persistent root"
    grep -aq "PROBE root=xfs@${target_serial}" "${log}" || fail "$1: / is not the target's xfs root"
    grep -aq "PROBE slot-b=$4" "${log}" || fail "$1: expected $4 empty slot-B partitions"
    [ "$(grep -ac 'PROBE usr-backing=' "${log}")" -ge 2 ] || fail "$1: no dm-verity backing for /usr"
    while read -r b; do
        [[ "${b}" =~ ^PROBE\ usr-backing=bluefin_usr_(verity_)?${v//./\\.}@${target_serial}$ ]] \
            || fail "$1: /usr backed by ${b#PROBE usr-backing=}, not the target's bluefin_usr_${v} slot"
    done < <(grep -aoE 'PROBE usr-backing=.*' "${log}")
    grep -aq 'PROBE timers-enabled=enabled enabled' "${log}" || fail "$1: the update timers are not enabled"
    grep -aq "PROBE keyring=${keyring_sum} etc-override=none" "${log}" \
        || fail "$1: the keyring is not ${keyring##*/} of the set: $(grep -ao 'PROBE keyring=.*' "${log}")"
    grep -aqF "PROBE banner-boot=Bluefin Server ${v}," "${log}" || fail "$1: the console banner does not show ${v}"
    grep -aqF "PROBE motd-boot=Bluefin Server ${v}," "${log}" || fail "$1: /etc/motd does not show ${v}"
    [ -n "${5:-}" ] && return 0
    grep -aq 'PROBE failed=0' "${log}" || fail "$1: failed units: $(grep -ao 'PROBE failed=.*' "${log}")"
    ! grep -a '\[FAILED\]' "${serial0}" >&2 || fail "$1: units failed during boot"
}

# banner_has <name> <probe> <text>: the issue and motd lines of <probe> carry <text>.
banner_has() {
    local log="${state}/$1.ttyS1.log"
    grep -aF "PROBE banner-$2=" "${log}" | grep -aqF -- "$3" || fail "$1: console banner after '$2' lacks '$3': $(grep -aF "PROBE banner-$2=" "${log}")"
    grep -aF "PROBE motd-$2=" "${log}" | grep -aqF -- "$3" || fail "$1: /etc/motd after '$2' lacks '$3'"
}
banner_lacks() {
    local log="${state}/$1.ttyS1.log"
    ! grep -aF "PROBE banner-$2=" "${log}" | grep -aqF -- "$3" || fail "$1: console banner after '$2' still shows '$3'"
}

probe_creds "${state}/probe.sh"
echo "==> 3/${steps} first boot of the target (creates slot B and the xfs root)"
boot 3-first-boot 'PROBE failed=' "${disk[@]}" -nic user,model=virtio-net-pci "${creds[@]}"
check_disk_boot 3-first-boot 1 "${ver}" 2
banner_has 3-first-boot boot 'Last update check: never'

echo "==> 4/${steps} boot the target with the installer still attached"
boot 4-with-installer 'PROBE failed=' "${disk[@]}" "${stick[@]}" -nic user,model=virtio-net-pci "${creds[@]}"
check_disk_boot 4-with-installer 2 "${ver}" 2

if [ "${target_kind}" = prior-install ]; then
    echo "==> 5/6 install again over that Bluefin install (ESP, usr A + B, xfs root)"
    # The firmware now boots the target's own entry first; picking the stick
    # in the boot menu is what a user does. Drop that entry instead.
    cp "${state}/vars-enrolled.fd" "${vars}"
    run_install 5-reinstall
    echo "==> 6/6 boot the reinstalled target (a new xfs root and slot B)"
    boot 6-reinstalled-boot 'PROBE failed=' "${disk[@]}" -nic user,model=virtio-net-pci "${creds[@]}"
    check_disk_boot 6-reinstalled-boot 1 "${ver}" 2
fi

[ -n "${next}" ] || { echo "PASS: offline installer installed ${ver} onto a ${target_kind} disk$([ "${target_kind}" = prior-install ] && echo ' and again over that install'); the target booted from its own bluefin_usr_${ver} slot (also with the installer attached) with slot B and the xfs root created on first boot and no failed units"; exit 0; }

if [ -n "${next_ver}" ]; then
    # A local release server: next/ is <next> as built, foreign/ the same
    # files with SHA256SUMS signed by a key the image does not trust.
    www="${state}/www"
    mkdir -p "${www}/foreign"
    ln -s "${next}" "${www}/next"
    for f in "${next}"/*; do [ -f "${f}" ] && ln -s "${f}" "${www}/foreign/${f##*/}"; done
    rm "${www}/foreign/SHA256SUMS.gpg"
    export GNUPGHOME="${state}/gnupg"
    mkdir -m 0700 "${GNUPGHOME}"
    gpg --batch --quiet --passphrase '' --quick-gen-key 'Dogfood Foreign Key <foreign@invalid>' default sign never
    gpg --batch --quiet --detach-sign --output "${www}/foreign/SHA256SUMS.gpg" "${next}/SHA256SUMS"
    (cd "${www}" && exec python3 -m http.server --bind 127.0.0.1 "${port}" >"${state}/http.log" 2>&1) &
    http_pid=$!
    trap 'kill "${http_pid}" 2>/dev/null || true' EXIT
fi

checks="an unreachable and a foreign-signed source, then ${next_ver}"
[ -n "${next_ver}" ] || checks="the newest release from the image's own source"
echo "==> 5/${steps} update checks on ${ver}: ${checks}"
probe_creds "${state}/probe-update.sh"
boot 5-update 'PROBE update-done' "${disk[@]}" -nic user,model=virtio-net-pci "${creds[@]}"
check_disk_boot 5-update 3 "${ver}" 2 failures-expected
log5="${state}/5-update.ttyS1.log"
if [ -n "${next_ver}" ]; then
    grep -aqE 'PROBE check-unreachable=[1-9][0-9]* unit=failed' "${log5}" || fail "an unreachable source did not fail systemd-sysupdate.service"
    banner_has 5-update unreachable 'Last update check FAILED'
    banner_has 5-update unreachable 'update source unreachable'
    grep -aqE 'PROBE check-foreign=[1-9][0-9]* unit=failed' "${log5}" || fail "a foreign-signed set did not fail systemd-sysupdate.service"
    banner_has 5-update foreign 'Last update check FAILED'
    banner_has 5-update foreign 'signature'
    grep -aqF "PROBE check-new=${next_ver}" "${log5}" || fail "systemd-sysupdate check-new did not find ${next_ver}: $(grep -ao 'PROBE check-new=.*' "${log5}")"
else
    next_ver="$(sed -n 's/^PROBE staged=\([^ ]*\) .*/\1/p' "${log5}" | tail -n1)"
    [ -n "${next_ver}" ] && [ "${next_ver}" != "${ver}" ] \
        && [ "$(printf '%s\n%s\n' "${ver}" "${next_ver}" | sort -V | tail -n1)" = "${next_ver}" ] \
        || fail "no release newer than ${ver} was staged from the image's own source"
fi
grep -aq 'PROBE check-update=0 unit=' "${log5}" || fail "systemd-sysupdate.service did not stage ${next_ver}"
grep -aq "PROBE staged=${next_ver} pending=yes" "${log5}" || fail "${next_ver} is not staged: $(grep -ao 'PROBE staged=.*' "${log5}")"
banner_has 5-update update "Bluefin Server ${ver},"
banner_has 5-update update "${next_ver} staged"
banner_lacks 5-update update 'FAILED'

echo "==> 6/${steps} boot the updated target"
probe_creds "${state}/probe-updated.sh"
boot 6-updated 'PROBE ssh-motd=' "${disk[@]}" -nic user,model=virtio-net-pci "${creds[@]}"
check_disk_boot 6-updated 4 "${next_ver}" 0
grep -aq 'PROBE bless=good' "${state}/6-updated.ttyS1.log" || fail "6-updated: the boot-counted ${next_ver} UKI was not blessed"
banner_lacks 6-updated boot 'never'
banner_lacks 6-updated boot 'FAILED'
banner_lacks 6-updated boot 'staged'
grep -aqF "PROBE ssh-motd=Bluefin Server ${next_ver}, automatic updates on" "${state}/6-updated.ttyS1.log" \
    || fail "6-updated: an SSH login does not show the banner: $(grep -a 'ssh' "${state}/6-updated.ttyS1.log" | tail -n 5)"

checked="a local server after reporting an unreachable and a foreign-signed source as failed checks on its banner"
[ "${next}" != release ] || checked="the image's own source"
echo "PASS: offline installer installed ${ver}; the installed disk had its update timers on and the image keyring, staged ${next_ver} from ${checked}, and booted it blessed from slot B with the banner showing it"
