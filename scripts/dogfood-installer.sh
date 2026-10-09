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
#   DOGFOOD_SECURE_BOOT=off (no <next>, not prior-install) runs on firmware
#   without Secure Boot (OVMF_CODE_INSECURE) and skips step 1; step 2 then
#   boots the stick twice: the unattended install must be refused before any
#   disk write (#309), and then installs with the
#   bluefin.install-allow-insecure-boot credential
#   DOGFOOD_TARGET=prior-install (no <next>) instead adds:
#   5. install again from the stick onto that installed disk (ESP, both usr
#      slots, xfs root), which must erase it like a blank one (#359)
#   6. boot the reinstalled disk: a new root (boot 1), and step 3's checks
#   DOGFOOD_INSTALL=console (no <next>, not prior-install, Secure Boot on)
#   instead installs the way a person at the monitor does (#311): no
#   unattended credential; the test types on the guest keyboard (QEMU
#   monitor sendkey) and reads the monitor (tty1, mirrored to a virtio port):
#   2. pick the target among two disks by its number in the installer's disk
#      list (size, model, by-id name), type "yes" at sysinstall's
#      confirmation, and see "installed ... remove the USB stick" before the
#      restart; the other disk stays untouched
#   3. the first boot asks for a root password on tty1: an empty answer is
#      refused and asked again, then a password typed twice; the tty1 login
#      banner shows the hostname and IP address, a wrong password is refused,
#      and root logs in at tty1 with the password typed
#   Every install also checks the "installed" screen, and every first boot
#   the serial console's login banner (hostname and IP address).
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
#   DOGFOOD_SECURE_BOOT=<mode> enforcing (default: the keys from step 1) or
#                              off (firmware without Secure Boot)
#   DOGFOOD_INSTALL=<mode>     unattended (default: the drop-in credential) or
#                              console (typed at the monitor, see above)
#   DOGFOOD_MEM=<MiB>          guest memory (default 4096)
#   DOGFOOD_TIMEOUT=<s>        per-boot timeout (default 600; key enrollment: 120)
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
secure_boot="${DOGFOOD_SECURE_BOOT:-enforcing}"
case "${secure_boot}" in
    enforcing) ;;
    off) [ -z "${next}" ] && [ "${target_kind}" != prior-install ] \
        || { echo "ERROR: DOGFOOD_SECURE_BOOT=off does not combine with <next> or prior-install" >&2; exit 1; } ;;
    *) echo "ERROR: DOGFOOD_SECURE_BOOT must be enforcing or off, not '${secure_boot}'" >&2; exit 1 ;;
esac
install_mode="${DOGFOOD_INSTALL:-unattended}"
case "${install_mode}" in
    unattended) ;;
    console) [ -z "${next}" ] && [ "${target_kind}" != prior-install ] && [ "${secure_boot}" = enforcing ] \
        || { echo "ERROR: DOGFOOD_INSTALL=console does not combine with <next>, prior-install or DOGFOOD_SECURE_BOOT=off" >&2; exit 1; } ;;
    *) echo "ERROR: DOGFOOD_INSTALL must be unattended or console, not '${install_mode}'" >&2; exit 1 ;;
esac
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
machine=(-machine "q35,smm=on,accel=kvm" -global "driver=cfi.pflash01,property=secure,value=on")
if [ "${secure_boot}" = off ]; then
    code="${OVMF_CODE_INSECURE:-$(first_existing \
        /usr/share/edk2/ovmf/OVMF_CODE.fd \
        /usr/share/OVMF/OVMF_CODE_4M.fd \
        /usr/share/OVMF/OVMF_CODE.fd \
        /usr/share/edk2/x64/OVMF_CODE.4m.fd)}" || { echo "ERROR: no OVMF_CODE without Secure Boot found (set OVMF_CODE_INSECURE)" >&2; exit 1; }
    machine=(-machine "q35,accel=kvm")
fi

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
    "${machine[@]}" -cpu host -m "${mem}" -smp 2
    -drive if=pflash,format=raw,unit=0,readonly=on,file="${code}"
    -drive if=pflash,format=raw,unit=1,file="${vars}"
    -display none -no-reboot
    )
# snapshot=on keeps the release artifact untouched.
stick=(-drive "if=none,id=stick,format=raw,snapshot=on,file=${installer}"
       -device virtio-blk-pci,drive=stick,serial=bluefin-installer)
disk=(-drive "if=none,id=target,format=raw,file=${target}"
      -device "virtio-blk-pci,drive=target,serial=${target_serial}")

# boot_start <name> <qemu args...>: start QEMU in the background. Serial logs
# land in ${state}/<name>.*.log; the monitor (what a person sees on tty1)
# in <name>.screen.log, through a virtio port the dogfood-screen.service
# credential writes to; <name>.mon is the QEMU monitor that types on the
# guest keyboard (type_keys).
boot_start() {
    local name="$1"; shift
    local log="${state}/${name}"
    rm -f "${log}.mon"
    "${qemu[@]}" "$@" \
        -serial "file:${log}.ttyS0" -serial "file:${log}.ttyS1" -serial "file:${log}.ttyS2" \
        -monitor "unix:${log}.mon,server=on,wait=off" \
        -device virtio-serial-pci,id=dogfood-vser \
        -chardev "file,id=dogfood-screen,path=${log}.screen.log" \
        -device virtserialport,bus=dogfood-vser.0,chardev=dogfood-screen,name=dogfood.screen \
        </dev/null >"${log}.qemu.log" 2>&1 &
    qemu_pid=$! qemu_deadline=$(( $(date +%s) + timeout_s )) screen_seen=0
}

# boot_wait <name> <done-regex> [<serial>]: wait until QEMU exits (-no-reboot
# turns every reboot into an exit), <done-regex> shows up in the <serial> log
# (default ttyS1), or the timeout hits.
boot_wait() {
    local name="$1" done_re="$2" serial="${3:-ttyS1}"
    local log="${state}/${name}"
    while kill -0 "${qemu_pid}" 2>/dev/null && [ "$(date +%s)" -lt "${qemu_deadline}" ]; do
        # A few seconds of grace so the journal mirror catches up.
        [ -n "${done_re}" ] && grep -aqE "${done_re}" "${log}.${serial}" 2>/dev/null && { sleep 3; break; }
        sleep 2
    done
    local timed_out=0
    if kill -0 "${qemu_pid}" 2>/dev/null; then
        [ "$(date +%s)" -ge "${qemu_deadline}" ] && timed_out=1
        kill "${qemu_pid}" 2>/dev/null || true
    fi
    wait "${qemu_pid}" 2>/dev/null || true
    for s in ttyS0 ttyS1 ttyS2; do
        sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\x1bP[^\x1b]*\x1b\\//g' "${log}.${s}" 2>/dev/null \
            | tr -d '\r' > "${log}.${s}.log" || true
        rm -f "${log}.${s}"
    done
    rm -f "${log}.mon"
    grep -aoE 'PROBE[ -].*' "${log}.ttyS1.log" || true
    [ "${timed_out}" = 0 ] || { tail -n 40 "${log}.ttyS0.log" >&2; fail "${name}: no result within ${timeout_s}s"; }
}

# boot <name> <done-regex> <qemu args...>
boot() {
    local name="$1" done_re="$2"; shift 2
    boot_start "${name}" "$@"
    boot_wait "${name}" "${done_re}"
}

# wait_screen <name> <ERE> [<seconds>]: wait until a snapshot of the monitor
# taken since the last wait_screen shows <ERE> (each snapshot is the whole
# screen, so text still on screen shows up again in the next one).
wait_screen() {
    local f="${state}/$1.screen.log" deadline=$(( $(date +%s) + ${3:-300} ))
    while kill -0 "${qemu_pid}" 2>/dev/null && [ "$(date +%s)" -lt "${deadline}" ]; do
        if tail -c "+$(( screen_seen + 1 ))" "${f}" 2>/dev/null | grep -aqE -- "$2"; then
            screen_seen="$(stat -c %s "${f}")"
            return 0
        fi
        sleep 1
    done
    kill "${qemu_pid}" 2>/dev/null || true
    tail -n 30 "${f}" >&2 || true
    fail "$1: the monitor never showed '$2'"
}

# wait_prompt <name> <ERE> [<seconds>]: wait until the line with the cursor
# on the monitor (where it waits for input) matches <ERE>.
wait_prompt() {
    local deadline=$(( $(date +%s) + ${3:-300} ))
    while kill -0 "${qemu_pid}" 2>/dev/null && [ "$(date +%s)" -lt "${deadline}" ]; do
        awk '/^=== screen /{y=$NF; n=0; line=""; next} {n++; if (n == y + 1) line=$0} END{print line}' \
            "${state}/$1.screen.log" 2>/dev/null | grep -aqE -- "$2" && return 0
        sleep 1
    done
    kill "${qemu_pid}" 2>/dev/null || true
    tail -n 30 "${state}/$1.screen.log" >&2 || true
    fail "$1: the monitor never asked '$2'"
}

# last_screen <name>: the newest snapshot of the monitor.
last_screen() { awk '/^=== screen /{buf=""; next} {buf=buf $0 "\n"} END{printf "%s", buf}' "${state}/$1.screen.log"; }

# type_keys <name> <text>: type <text> on the guest's keyboard through the
# QEMU monitor (sendkey); a newline is Enter.
type_keys() {
    python3 - "${state}/$1.mon" "$2" <<'PY'
import socket, sys, time
keys = {" ": "spc", "\n": "ret", "-": "minus", ".": "dot", "/": "slash", "=": "equal", ",": "comma"}
with socket.socket(socket.AF_UNIX) as s:
    s.connect(sys.argv[1])
    for ch in sys.argv[2]:
        s.sendall(f"sendkey {keys.get(ch, ch)}\n".encode())
        time.sleep(0.15)
    time.sleep(0.5)
PY
}

# The monitor (the foreground VT: the installer's /dev/console, the installed
# disk's tty1) as text on the dogfood.screen virtio port, whenever it changes.
# Started early (sysinit.target), so it sees the first-boot prompt.
cat > "${state}/screen.sh" <<'SCREEN'
export LC_ALL=C
port=/dev/virtio-ports/dogfood.screen last=""
while :; do
    if [ -w "${port}" ] && [ -r /dev/vcsa ]; then
        # vcsa starts with the screen's rows, columns and the cursor's x, y.
        read -r _ cols _ y < <(od -An -tu1 -N4 /dev/vcsa)
        screen="cursor ${y}
$(tr '\000-\037\177-\377' '?' < /dev/vcs | fold -w "${cols:-80}" | sed 's/ *$//')"
        if [ "${screen}" != "${last}" ]; then
            printf '=== screen %s %s\n' "$(cut -d' ' -f1 /proc/uptime)" "${screen}" > "${port}"
            last="${screen}"
        fi
    fi
    sleep 0.5
done
SCREEN
cat > "${state}/screen.service" <<'UNIT'
[Unit]
Description=Dogfood monitor mirror
DefaultDependencies=no
Conflicts=shutdown.target
Before=shutdown.target
[Service]
ImportCredential=dogfood.screen
ExecStart=/bin/bash ${CREDENTIALS_DIRECTORY}/dogfood.screen
UNIT
printf '[Unit]\nWants=dogfood-screen.service\n' > "${state}/screen-wants.conf"
screen_creds=(
    -smbios "$(cred dogfood.screen "${state}/screen.sh")"
    -smbios "$(cred systemd.extra-unit.dogfood-screen.service "${state}/screen.service")"
    -smbios "$(cred systemd.unit-dropin.sysinit.target~dogfood-screen "${state}/screen-wants.conf")"
)

if [ "${secure_boot}" = off ]; then
    echo "==> 1/${steps} firmware without Secure Boot (${code##*/}): nothing to enroll"
else
    echo "==> 1/${steps} enroll Secure Boot keys from the installer (${ver})"
    # systemd-boot says "successfully enrolled" on the firmware console once
    # db, KEK and PK are written, then resets, which -no-reboot turns into an
    # exit; OVMF sometimes hangs in that reset instead, so the message ends
    # the boot. Enrolling takes seconds, not the per-boot timeout.
    timeout_s=120 boot_start 1-enroll "${stick[@]}" -nic none
    timeout_s=120 boot_wait 1-enroll 'successfully enrolled' ttyS0
    grep -aq 'successfully enrolled' "${state}/1-enroll.ttyS0.log" || fail "key enrollment"
fi
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
# Wanted by sysinit.target too: the console install has no sysinstall drop-in.
printf '[Unit]\nWants=dogfood-journal.service\n' > "${state}/journal-wants.conf"
install_creds=(-smbios "$(cred systemd.extra-unit.dogfood-journal.service "${state}/journal.service")"
    -smbios "$(cred systemd.unit-dropin.sysinit.target~dogfood-journal "${state}/journal-wants.conf")")
# systemd-firstboot prompts on the installer console first; answer it the
# unattended way. sysinstall copies locale, keymap and timezone to the target.
for kv in firstboot.locale=C.UTF-8 firstboot.keymap=us firstboot.timezone=UTC 'passwd.hashed-password.root=!*'; do
    printf '%s' "${kv#*=}" > "${state}/${kv%%=*}"
    install_creds+=(-smbios "$(cred "${kv%%=*}" "${state}/${kv%%=*}")")
done
install_creds+=("${screen_creds[@]}")
if [ "${install_mode}" = unattended ] && [ "${DOGFOOD_SYSINSTALL_CRED:-1}" != 0 ]; then
    install_creds+=(-smbios "$(cred systemd.unit-dropin.systemd-sysinstall.service "${state}/sysinstall.conf")")
fi

# check_done_screen <name>: after the install, before the restart, the
# monitor said so (bluefin-installer-done.service).
check_done_screen() {
    local text
    for text in 'is installed.' 'Remove the USB stick when the screen goes blank.'; do
        grep -aqF "${text}" "${state}/$1.screen.log" \
            || fail "$1: the monitor did not show '${text}' before the restart"
    done
    grep -aq 'bluefin-installer-done: installed, restarting' "${state}/$1.ttyS2.log" \
        || fail "$1: bluefin-installer-done.service did not run"
    grep -aF -B2 -A8 'is installed.' "${state}/$1.screen.log" | tail -n 11 | sed 's/^/    screen| /'
}

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
    check_done_screen "$1"
}

# console_install <name>: install the way a person at the monitor does: pick
# the target by its number among two disks, confirm with "yes", see the
# "installed" screen, press Enter to restart.
console_install() {
    local name="$1" log="${state}/$1" decoy="${state}/decoy.raw" list n
    rm -f "${decoy}"
    truncate -s 8G "${decoy}"
    cat > "${state}/done-probe.conf" <<EOF
[Service]
ExecStartPre=/bin/bash -c 'exec >/dev/ttyS1 2>&1; udevadm settle -t 10 || true; echo "PROBE sysinstall=\$\$(systemctl show -P Result systemd-sysinstall.service) installed-slot-b=\$\$(lsblk -rno PARTLABEL ${target_dev} | grep -cx _empty) installed-parts=\$\$(lsblk -rno TYPE ${target_dev} | grep -cx part) decoy-parts=\$\$(lsblk -rno TYPE /dev/disk/by-id/virtio-bluefin-decoy | grep -cx part)"; sed "s/^/PROBE-LOG disk-choice /" /run/bluefin-installer-disk/sysinstall.env'
EOF
    boot_start "${name}" "${stick[@]}" "${disk[@]}" \
        -drive "if=none,id=decoy,format=raw,file=${decoy}" -device virtio-blk-pci,drive=decoy,serial=bluefin-decoy \
        -nic none "${install_creds[@]}" -smbios "$(cred systemd.unit-dropin.bluefin-installer-done.service "${state}/done-probe.conf")"
    wait_prompt "${name}" 'Disk number \(1-2\), or q to cancel:$'
    list="$(last_screen "${name}" | grep -E '^  [0-9]\) ')"
    printf '%s\n' "${list}" | sed 's/^/    screen| /'
    n="$(printf '%s\n' "${list}" | sed -n 's/^  \([0-9]\)) .* virtio-bluefin-target$/\1/p')"
    [ -n "${n}" ] || fail "${name}: the target is not in the installer's disk list"
    printf '%s\n' "${list}" | grep -qE "^  ${n}\) 16G +.* virtio-bluefin-target$" || fail "${name}: the disk list does not show the target's size"
    printf '%s\n' "${list}" | grep -qE '^  [0-9]\) 8G +.* virtio-bluefin-decoy$' || fail "${name}: the disk list does not show the other disk"
    ! printf '%s\n' "${list}" | grep -q 'bluefin-installer' || fail "${name}: the installer offers its own stick"
    type_keys "${name}" $'9\n'
    wait_screen "${name}" 'There is no disk 9\.'
    wait_prompt "${name}" 'Disk number \(1-2\), or q to cancel:$'
    type_keys "${name}" "${n}"$'\n'
    wait_screen "${name}" "type 'yes' to confirm"
    last_screen "${name}" | grep -qF "${target_dev}" || fail "${name}: sysinstall's summary does not show ${target_dev}"
    last_screen "${name}" | sed '/^$/d' | sed 's/^/    screen| /'
    type_keys "${name}" $'yes\n'
    wait_screen "${name}" 'is installed\.' "${timeout_s}"
    # Enter restarts at once, without the countdown.
    type_keys "${name}" $'\n'
    boot_wait "${name}" ''
    grep -aq "PROBE sysinstall=success installed-slot-b=0 installed-parts=3 decoy-parts=0" "${log}.ttyS1.log" \
        || fail "${name}: expected the ESP and usr slot A (+ verity) on the target and the other disk untouched: $(grep -ao 'PROBE sysinstall=.*' "${log}.ttyS1.log")"
    grep -aqF "PROBE-LOG disk-choice BLUEFIN_INSTALL_TARGET=${target_dev}" "${log}.ttyS1.log" \
        || fail "${name}: the disk question did not hand ${target_dev} to sysinstall"
    check_done_screen "${name}"
}

if [ "${secure_boot}" = off ]; then
    # bluefin-installer-secure-boot.service, which sysinstall Requires=,
    # reports its result on ttyS1.
    cat > "${state}/secure-boot-check.conf" <<'CHECK'
[Service]
ExecStartPost=/bin/bash -c 'echo "PROBE secure-boot-check=passed" >/dev/ttyS1'
ExecStopPost=/bin/bash -c '[ "$${SERVICE_RESULT}" = success ] || echo "PROBE secure-boot-check=$${SERVICE_RESULT} $${EXIT_STATUS}" >/dev/ttyS1'
CHECK
    install_creds+=(-smbios "$(cred systemd.unit-dropin.bluefin-installer-secure-boot.service "${state}/secure-boot-check.conf")")
    echo "==> 2/${steps} Secure Boot off: the unattended install is refused before any disk write"
    before="$(sha256sum < "${target}")"
    boot 2-refused 'PROBE (secure-boot-check|sysinstall)=' "${stick[@]}" "${disk[@]}" -nic none "${install_creds[@]}"
    grep -aq 'PROBE secure-boot-check=exit-code 1' "${state}/2-refused.ttyS1.log" || fail "2-refused: the Secure Boot check did not refuse"
    ! grep -aq 'PROBE sysinstall=' "${state}/2-refused.ttyS1.log" || fail "2-refused: systemd-sysinstall ran"
    grep -aq 'installation cancelled: unattended install and the firmware reports no Secure Boot state' "${state}/2-refused.ttyS2.log" \
        || fail "2-refused: no cancellation reason in the journal"
    [ "$(sha256sum < "${target}")" = "${before}" ] || fail "2-refused: the target disk changed"
    printf 1 > "${state}/allow-insecure-boot"
    install_creds+=(-smbios "$(cred bluefin.install-allow-insecure-boot "${state}/allow-insecure-boot")")
    echo "==> 2/${steps} with bluefin.install-allow-insecure-boot=1: ExecStart=${exec_start} ${install_args} ${target_dev}"
    run_install 2-install
    grep -aq 'PROBE secure-boot-check=passed' "${state}/2-install.ttyS1.log" || fail "2-install: the Secure Boot check did not pass"
    grep -aq 'continuing without Secure Boot (credential bluefin.install-allow-insecure-boot)' "${state}/2-install.ttyS2.log" \
        || fail "2-install: the check did not log why it continued"
elif [ "${install_mode}" = console ]; then
    echo "==> 2/${steps} offline install onto a ${target_kind} disk, typed at the monitor"
    console_install 2-install
else
    echo "==> 2/${steps} offline install onto a ${target_kind} disk: ExecStart=${exec_start} ${install_args} ${target_dev}"
    run_install 2-install
fi

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
want="$(ls /usr/lib/sysupdate.d | sed -n 's/\.feature$//p' | sort | tr '\n' ' ')"
got="$(updatectl --no-pager --no-legend features 2>/run/dogfood-updatectl.err | sed -E 's/^[^ ]+ +([^ ]+).*/\1/' | sort | tr '\n' ' ')"
if [ -n "${want}" ] && [ "${got}" = "${want}" ]; then echo "PROBE updatectl-features=ok ${got}"
else echo "PROBE updatectl-features=FAIL want=${want}got=${got}$(tr '\n' ' ' < /run/dogfood-updatectl.err)"; fi
echo "PROBE keyring=$(sha256sum < /usr/lib/systemd/import-pubring.pgp | cut -d' ' -f1) etc-override=$(test -e /etc/systemd/import-pubring.pgp && echo present || echo none)"
systemctl start boot-complete.target 2>/dev/null || true
echo "PROBE bless=$(/usr/lib/systemd/systemd-bless-boot status 2>/dev/null)"
IFS=: read -r _ hash _ < <(grep '^root:' /etc/shadow)
case "${hash}" in '' | '!'* | '*'*) echo "PROBE root-password=locked" ;; *) echo "PROBE root-password=set" ;; esac
# The login banner as agetty renders it (it needs a terminal on stdin), once
# DHCP gave an address.
for _ in $(seq 60); do ip -4 -o addr show scope global | grep -q ' inet ' && break; sleep 1; done
echo "PROBE hostname=$(hostname)"
echo "PROBE ipv4=$(ip -4 -o addr show scope global | sed -n 's/.* inet \([0-9.]*\)\/.*/\1/p' | head -n1)"
echo "PROBE issue=$(agetty --show-issue < /dev/ttyS1 2>/dev/null | tr -d '\r' | tr '\n' '|')"
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
# probe_creds <probe> [prompt]: with "prompt" no passwd credential, so the
# first boot asks for the root password on tty1.
probe_creds() {
    creds=(
        -smbios "$(cred dogfood.probe "$1")"
        -smbios "$(cred systemd.extra-unit.dogfood-probe.service "${state}/probe.service")"
        -smbios "$(cred systemd.unit-dropin.multi-user.target~dogfood-probe "${state}/probe-wants.conf")"
        "${screen_creds[@]}"
    )
    [ "${2:-}" = prompt ] || creds+=(-smbios "$(cred passwd.hashed-password.root "${state}/passwd.hashed-password.root")")
}

# check_issue <name>: the login banner, as agetty renders it, shows the
# node's hostname and IPv4 address and how to reach it over SSH.
check_issue() {
    local log="${state}/$1.ttyS1.log" host ip issue
    host="$(sed -n 's/^PROBE hostname=//p' "${log}" | tail -n1)"
    ip="$(sed -n 's/^PROBE ipv4=//p' "${log}" | tail -n1)"
    issue="$(sed -n 's/^PROBE issue=//p' "${log}" | tail -n1)"
    [ -n "${host}" ] && [ -n "${ip}" ] || fail "$1: no hostname or IPv4 address to look for"
    [[ "${issue}" == "Bluefin Server ${host} ("* ]] || fail "$1: the login banner does not start with the hostname ${host}: ${issue}"
    [[ "${issue}" == *"|"*": ${ip}"* ]] || fail "$1: the login banner does not list ${ip}: ${issue}"
    [[ "${issue}" == *"|SSH, when enabled (keys only): ssh root@${ip}|"* ]] || fail "$1: the login banner has no SSH line for ${ip}: ${issue}"
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
    [ "${secure_boot}" != enforcing ] || grep -aq 'PROBE secureboot=enabled (user)' "${log}" \
        || fail "$1: Secure Boot is not enforcing: $(grep -ao 'PROBE secureboot=.*' "${log}")"
    grep -aq "PROBE slot-b=$4" "${log}" || fail "$1: expected $4 empty slot-B partitions"
    [ "$(grep -ac 'PROBE usr-backing=' "${log}")" -ge 2 ] || fail "$1: no dm-verity backing for /usr"
    while read -r b; do
        [[ "${b}" =~ ^PROBE\ usr-backing=bluefin_usr_(verity_)?${v//./\\.}@${target_serial}$ ]] \
            || fail "$1: /usr backed by ${b#PROBE usr-backing=}, not the target's bluefin_usr_${v} slot"
    done < <(grep -aoE 'PROBE usr-backing=.*' "${log}")
    grep -aq 'PROBE timers-enabled=enabled enabled' "${log}" || fail "$1: the update timers are not enabled"
    # A published release older than the fix for #375 cannot list them.
    if [ "${next}" != release ] || [ "${v}" = "${ver}" ]; then
        grep -aq 'PROBE updatectl-features=ok ' "${log}" \
            || fail "$1: updatectl features does not list the image's optional features: $(grep -ao 'PROBE updatectl-features=.*' "${log}")"
    fi
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

# console_first_boot <name>: the first boot asks for the root password on
# tty1; an empty answer is refused, then a password typed twice. At the tty1
# login the banner shows the hostname and IP address, a wrong password is
# refused, and root logs in with the password typed.
console_first_boot() {
    local name="$1" log="${state}/$1" pw
    pw="$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
    boot_start "${name}" "${disk[@]}" -nic user,model=virtio-net-pci "${creds[@]}"
    wait_prompt "${name}" 'new root password' "${timeout_s}"
    type_keys "${name}" $'\n'
    wait_screen "${name}" 'not accepted here' 60
    wait_prompt "${name}" 'new root password' 60
    type_keys "${name}" "${pw}"$'\n'
    wait_prompt "${name}" 'root password again' 60
    type_keys "${name}" "${pw}"$'\n'
    # agetty reprints the banner when DHCP adds the address.
    wait_screen "${name}" 'ssh root@[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+'
    wait_prompt "${name}" ' login:$'
    last_screen "${name}" > "${log}.login-screen.log"
    sed '/^$/d; s/^/    screen| /' "${log}.login-screen.log"
    type_keys "${name}" $'root\n'
    wait_prompt "${name}" 'Password:$' 60
    type_keys "${name}" $'wrongpassword\n'
    wait_screen "${name}" 'Login incorrect' 60
    wait_prompt "${name}" ' login:$' 60
    type_keys "${name}" $'root\n'
    wait_prompt "${name}" 'Password:$' 60
    type_keys "${name}" "${pw}"$'\n'
    wait_prompt "${name}" '[#$]$' 60
    type_keys "${name}" $'id\n'
    wait_screen "${name}" 'uid=0\(root\) gid=0\(root\)' 60
    last_screen "${name}" | sed '/^$/d' | tail -n 6 | sed 's/^/    screen| /'
    boot_wait "${name}" 'PROBE failed='
    grep -aqF 'Please enter the new root password' "${log}.screen.log" || fail "${name}: no root password prompt on tty1"
    grep -aq 'PROBE root-password=set' "${log}.ttyS1.log" || fail "${name}: root has no password after the prompt"
    grep -aqF 'would lock root for good, so it is not accepted here.' "${log}.screen.log" \
        || fail "${name}: the empty answer was not refused"
    local host ip
    host="$(sed -n 's/^PROBE hostname=//p' "${log}.ttyS1.log" | tail -n1)"
    ip="$(sed -n 's/^PROBE ipv4=//p' "${log}.ttyS1.log" | tail -n1)"
    grep -qF "Bluefin Server ${host} (tty1)" "${log}.login-screen.log" || fail "${name}: the tty1 banner does not show the hostname ${host}"
    grep -qE ": ${ip//./\\.}( |$)" "${log}.login-screen.log" || fail "${name}: the tty1 banner does not list ${ip}"
    grep -qF "ssh root@${ip}" "${log}.login-screen.log" || fail "${name}: the tty1 banner has no SSH line for ${ip}"
}

if [ "${install_mode}" = console ]; then
    probe_creds "${state}/probe.sh" prompt
    echo "==> 3/${steps} first boot of the target: root password and login typed at tty1"
    console_first_boot 3-first-boot
else
    probe_creds "${state}/probe.sh"
    echo "==> 3/${steps} first boot of the target (creates slot B and the xfs root)"
    boot 3-first-boot 'PROBE failed=' "${disk[@]}" -nic user,model=virtio-net-pci "${creds[@]}"
    # The passwd.hashed-password.root credential answered the prompt, as given.
    grep -aq 'PROBE root-password=locked' "${state}/3-first-boot.ttyS1.log" || fail "3-first-boot: the credential did not answer the root password prompt"
fi
check_disk_boot 3-first-boot 1 "${ver}" 2
check_issue 3-first-boot
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

[ "${install_mode}" != console ] || { echo "PASS: offline installer installed ${ver} at the console: the target picked by number from a list with size and model, confirmed, 'installed, remove the USB stick' shown before the restart; the first boot refused an empty root password, took one typed at tty1, showed the hostname and IP address on the login banner, and root logged in at tty1 with it"; exit 0; }
[ -n "${next}" ] || { echo "PASS: offline installer installed ${ver} onto a ${target_kind} disk$([ "${target_kind}" = prior-install ] && echo ' and again over that install')$([ "${secure_boot}" = off ] && echo ' without Secure Boot, only once a credential allowed it'); the target booted from its own bluefin_usr_${ver} slot (also with the installer attached) with slot B and the xfs root created on first boot and no failed units"; exit 0; }

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
