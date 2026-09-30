#!/usr/bin/env bash
# End-to-end check of the offline USB installer in QEMU with Secure Boot:
#   1. boot bluefin-server-installer_<ver>.raw once so systemd-boot enrolls
#      the dev keys (secure-boot-enroll if-safe)
#   2. boot it with a blank target disk and no network; the shipped
#      systemd-sysinstall.service runs unattended and reboots
#   3. boot the target disk on its own: /usr must come from its
#      bluefin_usr_<ver> slot, the first boot creates slot B and the xfs root,
#      and no unit may fail
#   4. boot the target again with the installer still attached: /usr must
#      still come from the target, never from the installer's
#      bluefin-installer-usr partition
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
# Usage: dogfood-installer.sh <dir with bluefin-server-installer_<ver>.raw>
# Environment:
#   DOGFOOD_STATE=<dir>        logs, target disk and UEFI vars (default dist/dogfood-installer)
#   DOGFOOD_TARGET_DISK=<file> target disk image, recreated blank (default <state>/target.raw)
#   DOGFOOD_TARGET_DEV=<path>  target device the installer is told to use
#                              (default /dev/disk/by-id/virtio-bluefin-target)
#   DOGFOOD_SYSINSTALL_ARGS=.. extra systemd-sysinstall arguments
#                              (default --confirm=no)
#   DOGFOOD_SYSINSTALL_CRED=0  do not pass the unattended drop-in credential
#   DOGFOOD_MEM=<MiB>          guest memory (default 4096)
#   DOGFOOD_TIMEOUT=<s>        per-boot timeout (default 600)
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
dir="$(realpath "${1:?usage: $0 <artifact dir>}")"
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

echo "==> 1/4 enroll Secure Boot keys from the installer (${ver})"
boot 1-enroll '' "${stick[@]}" -nic none
grep -aq 'successfully enrolled' "${state}/1-enroll.ttyS0.log" || fail "key enrollment"

exec_start="$(sed -n 's/^ExecStart=\(..*\)$/\1/p' "${dropin_src}" | tail -n1)"
[ -n "${exec_start}" ] || fail "no ExecStart= in ${dropin_src}"
cat > "${state}/sysinstall.conf" <<EOF
[Unit]
Wants=dogfood-journal.service

[Service]
StandardInput=null
StandardError=journal+console
ExecStart=
ExecStart=${exec_start} ${install_args} ${target_dev}
ExecStopPost=/bin/bash -c 'exec >/dev/ttyS1 2>&1; echo "PROBE sysinstall=\$\${SERVICE_RESULT} \$\${EXIT_STATUS}"; udevadm settle -t 10 || true; echo "PROBE installed-slot-b=\$\$(lsblk -rno PARTLABEL ${target_dev} | grep -cx _empty)"; lsblk -o NAME,PARTLABEL,FSTYPE,SIZE ${target_dev} | sed "s/^/PROBE-LOG installed /"'
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

echo "==> 2/4 offline install: ExecStart=${exec_start} ${install_args} ${target_dev}"
# Offline (-nic none): the installer must not need a network.
boot 2-install 'PROBE sysinstall=([^s]|s[^u])' \
    "${stick[@]}" "${disk[@]}" -nic none "${install_creds[@]}"
grep -aq 'PROBE sysinstall=success' "${state}/2-install.ttyS1.log" \
    || { grep -a 'sysinstall' "${state}/2-install.ttyS2.log" | grep -v audit | tail -n 20 >&2 || true; fail "systemd-sysinstall did not succeed"; }
grep -aq 'PROBE installed-slot-b=0' "${state}/2-install.ttyS1.log" \
    || fail "slot B exists before the first boot of the target"

{
    printf 'ver=%q\ntarget=/dev/disk/by-id/virtio-%s\n' "${ver}" "${target_serial}"
    cat <<'PROBE'
serial() { cat "/sys/block/$(lsblk -dno PKNAME "$1")/serial" 2>/dev/null; }
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
boots=$(( $(cat /var/lib/dogfood-boots 2>/dev/null || echo 0) + 1 ))
echo "${boots}" > /var/lib/dogfood-boots
echo "PROBE boots=${boots}"
sync
echo "PROBE failed=$(systemctl --failed --no-legend | wc -l) $(systemctl --failed --no-legend --plain | cut -d' ' -f1 | tr '\n' ' ')"
PROBE
} > "${state}/probe.sh"
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
probe_creds=(
    -smbios "$(cred dogfood.probe "${state}/probe.sh")"
    -smbios "$(cred systemd.extra-unit.dogfood-probe.service "${state}/probe.service")"
    -smbios "$(cred systemd.unit-dropin.multi-user.target~dogfood-probe "${state}/probe-wants.conf")"
)

check_disk_boot() {
    local log="${state}/$1.ttyS1.log" serial0="${state}/$1.ttyS0.log" b
    grep -aq 'PROBE failed=' "${log}" || fail "$1: probe did not run"
    grep -aq "PROBE os=bluefin-server ${ver}" "${log}" || fail "$1: not running ${ver}"
    grep -aq "PROBE boots=$2" "${log}" || fail "$1: expected boot $2 of the persistent root"
    grep -aq "PROBE root=xfs@${target_serial}" "${log}" || fail "$1: / is not the target's xfs root"
    grep -aq 'PROBE slot-b=2' "${log}" || fail "$1: slot B (usr + usr-verity) missing"
    [ "$(grep -ac 'PROBE usr-backing=' "${log}")" -ge 2 ] || fail "$1: no dm-verity backing for /usr"
    while read -r b; do
        [[ "${b}" =~ ^PROBE\ usr-backing=bluefin_usr_(verity_)?${ver//./\\.}@${target_serial}$ ]] \
            || fail "$1: /usr backed by ${b#PROBE usr-backing=}, not the target's bluefin_usr_${ver} slot"
    done < <(grep -aoE 'PROBE usr-backing=.*' "${log}")
    grep -aq 'PROBE failed=0' "${log}" || fail "$1: failed units: $(grep -ao 'PROBE failed=.*' "${log}")"
    ! grep -a '\[FAILED\]' "${serial0}" >&2 || fail "$1: units failed during boot"
}

echo "==> 3/4 first boot of the target (creates slot B and the xfs root)"
boot 3-first-boot 'PROBE failed=' "${disk[@]}" -nic user,model=virtio-net-pci "${probe_creds[@]}"
check_disk_boot 3-first-boot 1

echo "==> 4/4 boot the target with the installer still attached"
boot 4-with-installer 'PROBE failed=' "${disk[@]}" "${stick[@]}" -nic user,model=virtio-net-pci "${probe_creds[@]}"
check_disk_boot 4-with-installer 2

echo "PASS: offline installer installed ${ver} onto a blank disk; the target booted twice (with and without the installer attached) from its own bluefin_usr_${ver} slot with slot B and the xfs root created on first boot and no failed units"
