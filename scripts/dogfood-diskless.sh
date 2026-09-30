#!/usr/bin/env bash
# Boot a Bluefin Server build diskless in QEMU, the way a PXE/HTTP-booted
# node would: firmware -> signed systemd-boot -> signed UKI -> initrd pulls
# bluefin-server_<ver>.raw over HTTP into RAM -> dm-verity /usr, tmpfs root.
#
# Secure Boot firmware starts in setup mode; systemd-boot enrolls the dev
# keys from the ESP (secure-boot-enroll if-safe) and reboots, so every
# later boot is verified. The UKI's cmdline is locked, so the download URL
# is handed over as the import.pull system credential via SMBIOS.
#
# Usage: dogfood-diskless.sh <dir with .raw/.efi/.esp.raw> [--check]
#   --check  headless: boot, run a probe, exit 0 if Secure Boot was enforced and no
#            unit failed. With DOGFOOD_TAMPER set, exit 0 only if the initrd
#            refuses the image.
# Environment:
#   DOGFOOD_PORT=<port>        HTTP port for the built-in server (default 8765)
#   DOGFOOD_MEM=<MiB>          guest memory (default 4096)
#   DOGFOOD_TIMEOUT=<seconds>  --check deadline (default 600)
#   DOGFOOD_EXPECT=<ERE>       --check also requires the probe output to match
#   DOGFOOD_IGNITION=<file>    pass an Ignition config as the ignition.config credential
#   DOGFOOD_CREDS=<dir>        pass every file in <dir> as a system credential named after it
#   DOGFOOD_STATE_DISK=<file>  attach a persistent second disk (/dev/vdb), created if missing
#   DOGFOOD_EXTRA_PROBE=<file> shell snippet appended to the in-guest probe
#   DOGFOOD_VARS=<file>        persistent UEFI variable store (keeps enrolled keys)
#   DOGFOOD_BOOT=disk          boot DOGFOOD_STATE_DISK instead of the netboot ESP
#   DOGFOOD_BOOT=http          UEFI HTTP boot the netboot UKI (the initrd derives the
#                              /usr image URL from the boot URL); enrolls keys first
#   DOGFOOD_BOOT_URL=<url>     HTTP boot from another server (e.g. Booty) instead
#   DOGFOOD_NODE_IGN=<file>    serve it as bluefin-node.ign next to the UKI (HTTP boot)
#   DOGFOOD_SERVE_EXTRA=<dir>  also serve the files in <dir>
#   DOGFOOD_TAMPER=raw|sums    serve a corrupted image (raw), or a corrupted image with
#                              SHA256SUMS re-hashed to match it but no longer matching
#                              SHA256SUMS.gpg (sums); --check then passes only if the
#                              initrd's pull refuses it for that reason
set -euo pipefail

dir="$(realpath "${1:?usage: $0 <artifact dir> [--check]}")"
mode="${2:-interactive}"
port="${DOGFOOD_PORT:-8765}"
mem="${DOGFOOD_MEM:-4096}"
timeout_s="${DOGFOOD_TIMEOUT:-600}"

esp="$(ls "${dir}"/bluefin-server-netboot_*.esp.raw | tail -n1)"
ver="${esp##*/bluefin-server-netboot_}"; ver="${ver%.esp.raw}"
image="bluefin-server_${ver}.raw"
[ -f "${dir}/${image}" ] || { echo "ERROR: ${dir}/${image} missing" >&2; exit 1; }

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

work="$(mktemp -d /tmp/bluefin-dogfood.XXXXXX)"
# Never leave a guest behind: an orphaned QEMU keeps its port and the caller's
# locks. Only kill PIDs that are set; `kill 0` signals the whole process group.
cleanup() {
    local pid
    for pid in ${qemu_pid:-} ${enroll_pid:-} ${http_pid:-}; do kill "${pid}" 2>/dev/null || true; done
    rm -rf "${work}"
}
trap cleanup EXIT
vars="${DOGFOOD_VARS:-${work}/vars.fd}"
[ -f "${vars}" ] || cp "${vars_tmpl}" "${vars}"
cp "${esp}" "${work}/esp.raw"
boot="${DOGFOOD_BOOT:-netboot}"

# Serve a symlink farm so per-run extras never land in the artifact directory.
srv="${work}/srv"
mkdir -p "${srv}"
for f in "${dir}"/*; do ln -s "${f}" "${srv}/"; done
[ -n "${DOGFOOD_NODE_IGN:-}" ] && cp "${DOGFOOD_NODE_IGN}" "${srv}/bluefin-node.ign"
if [ -n "${DOGFOOD_SERVE_EXTRA:-}" ]; then for f in "${DOGFOOD_SERVE_EXTRA}"/*; do ln -sf "$(realpath "${f}")" "${srv}/"; done; fi
image_re="${image//./\\.}"
case "${DOGFOOD_TAMPER:-}" in
    raw|sums)
        rm "${srv}/${image}"; cp "${dir}/${image}" "${srv}/${image}"
        printf 'X' | dd of="${srv}/${image}" bs=1 seek=4096 conv=notrunc status=none ;;&
    raw)
        refusal_re="DOWNLOAD INVALID: Checksum of ${image_re} file did not check out" ;;
    sums)
        # What an attacker without the signing key can do: make the manifest
        # match the modified image. Only the signature check can catch it.
        rm "${srv}/SHA256SUMS"
        sum="$(sha256sum "${srv}/${image}" | cut -d' ' -f1)"
        sed -E "s/^[0-9a-f]{64}( [ *]${image_re})$/${sum}\1/" "${dir}/SHA256SUMS" > "${srv}/SHA256SUMS"
        grep -q "^${sum} " "${srv}/SHA256SUMS" || { echo "ERROR: ${image} not in SHA256SUMS" >&2; exit 1; }
        refusal_re="DOWNLOAD INVALID: Signature verification failed" ;;
    '') ;;
    *) echo "ERROR: DOGFOOD_TAMPER must be raw or sums" >&2; exit 1 ;;
esac
(cd "${srv}" && exec python3 -m http.server --bind 127.0.0.1 "${port}" >"${work}/http.log" 2>&1) &
http_pid=$!

cred() { printf 'type=11,value=io.systemd.credential.binary:%s=%s' "$1" "$(base64 -w0 < "$2")"; }

# wait_for <seconds> <pid> <command...>: poll the command once a second until
# it succeeds (0), or the process exits or the time runs out (1).
wait_for() {
    local deadline=$(( $(date +%s) + $1 )) pid="$2"
    shift 2
    while [ "$(date +%s)" -lt "${deadline}" ]; do
        "$@" && return 0
        kill -0 "${pid}" 2>/dev/null || { "$@"; return; }
        sleep 1
    done
    return 1
}

printf 'raw,machine,verify=signature,blockdev:rootdisk:http://10.0.2.2:%s/%s\n' "${port}" "${image}" > "${work}/import.pull"
qemu=(qemu-system-x86_64
    -machine q35,smm=on,accel=kvm -cpu host -m "${mem}" -smp 2
    -global driver=cfi.pflash01,property=secure,value=on
    -drive if=pflash,format=raw,unit=0,readonly=on,file="${code}"
    -drive if=pflash,format=raw,unit=1,file="${vars}"
    )
if [ "${boot}" = http ] && [ ! -s "${vars}.enrolled" ]; then
    # HTTP boot starts the UKI directly, with no systemd-boot to enroll the
    # Secure Boot keys; enroll them once from the netboot ESP.
    echo "Enrolling Secure Boot keys from the netboot ESP"
    "${qemu[@]}" -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
        -drive "if=none,id=esp,format=raw,file=${work}/esp.raw" -device virtio-blk-pci,drive=esp,bootindex=1 \
        -display none -monitor none \
        -serial "file:${work}/enroll.log" </dev/null >/dev/null 2>&1 &
    enroll_pid=$!
    # systemd-boot resets the machine after enrolling; the firmware loading a
    # boot option again proves the variable store has the keys.
    enrolled_and_reset() { sed -n '/successfully enrolled/,$p' "${work}/enroll.log" 2>/dev/null | grep -aq 'BdsDxe: loading'; }
    rc=0
    wait_for 90 "${enroll_pid}" enrolled_and_reset || rc=$?
    kill "${enroll_pid}" 2>/dev/null || true
    wait "${enroll_pid}" 2>/dev/null || true
    cp "${work}/enroll.log" "${dir}/dogfood-enroll.log" 2>/dev/null || true
    [ "${rc}" = 0 ] || { echo "ERROR: key enrollment failed (log: ${dir}/dogfood-enroll.log)" >&2; exit 1; }
    echo enrolled > "${vars}.enrolled"
fi
if [ "${boot}" = http ]; then
    qemu+=(-netdev "user,id=n0,bootfile=${DOGFOOD_BOOT_URL:-http://10.0.2.2:${port}/bluefin-server-netboot_${ver}.efi}"
           -device virtio-net-pci,netdev=n0,bootindex=1)
else
    qemu+=(-netdev user,id=n0 -device virtio-net-pci,netdev=n0)
fi
if [ "${boot}" = netboot ]; then
    qemu+=(-drive "if=virtio,format=raw,file=${work}/esp.raw"
           -smbios "$(cred import.pull "${work}/import.pull")")
elif [ "${boot}" = disk ] && [ -z "${DOGFOOD_STATE_DISK:-}" ]; then
    echo "ERROR: DOGFOOD_BOOT=disk needs DOGFOOD_STATE_DISK" >&2; exit 1
fi

if [ -n "${DOGFOOD_STATE_DISK:-}" ]; then
    [ -f "${DOGFOOD_STATE_DISK}" ] || truncate -s 8G "${DOGFOOD_STATE_DISK}"
    qemu+=(-drive "if=virtio,format=raw,file=${DOGFOOD_STATE_DISK}")
fi
if [ -n "${DOGFOOD_IGNITION:-}" ]; then
    qemu+=(-smbios "$(cred ignition.config "${DOGFOOD_IGNITION}")")
fi
tamper="${DOGFOOD_TAMPER:-}"
if [ -n "${tamper}" ]; then
    # The initrd's console shows only that the download unit failed; copy the
    # pull's own messages (from the unit and from systemd-importd, which runs
    # the transfer) there so the log names why the image was refused. systemd
    # tools log natively to the journal when they can, bypassing the stream
    # journald forwards, so make them write to stderr.
    printf '[Service]\nEnvironment=SYSTEMD_LOG_TARGET=console\nStandardOutput=journal+console\nStandardError=journal+console\n' > "${work}/import-console.conf"
    qemu+=(-smbios "$(cred systemd.unit-dropin.systemd-import@.service "${work}/import-console.conf")"
           -smbios "$(cred systemd.unit-dropin.systemd-importd.service "${work}/import-console.conf")")
fi
if [ -n "${DOGFOOD_CREDS:-}" ]; then
    for f in "${DOGFOOD_CREDS}"/*; do
        if [ -f "${f}" ]; then qemu+=(-smbios "$(cred "${f##*/}" "${f}")"); fi
    done
fi

echo "Serving ${dir} on :${port}; ${boot} boot of ${ver} (Secure Boot)"
if [ "${mode}" != "--check" ]; then
    "${qemu[@]}" -nographic
    exit
fi

cat > "${work}/probe.sh" <<'PROBE'
echo "PROBE secureboot=$(bootctl status 2>/dev/null | sed -n 's/.*Secure Boot: *//p' | head -n1)"
echo "PROBE lockdown=$(cat /sys/kernel/security/lockdown)"
echo "PROBE usr=$(findmnt -no SOURCE,FSTYPE,OPTIONS /usr)"
echo "PROBE root=$(findmnt -no FSTYPE /)"
echo "PROBE verity=$(veritysetup status usr | sed -n 's/^ *status: *//p')"
echo "PROBE os=$(. /usr/lib/os-release; echo "${IMAGE_ID} ${IMAGE_VERSION}")"
echo "PROBE var=$(findmnt -no SOURCE,FSTYPE /var)"
echo "PROBE root-passwd=$(passwd -S root 2>&1 | cut -d' ' -f2)"
etc_writable=$(shopt -s globstar dotglob nullglob; for p in /etc /etc/**; do
    [ -L "${p}" ] && continue
    case "$(stat -c %A "${p}")" in [d-]????w????|[d-]???????w?) ;; *) continue ;; esac
    [ -k "${p}" ] || echo "${p}"
done)
echo "PROBE etc-writable=$(printf '%s' "${etc_writable}" | grep -c .) $(printf '%s' "${etc_writable}" | head -n 5 | tr '\n' ' ')"
boots=$(( $(cat /var/lib/dogfood-boots 2>/dev/null || echo 0) + 1 ))
echo "${boots}" > /var/lib/dogfood-boots
echo "PROBE boots=${boots}"
echo "PROBE update-timers=$(systemctl is-active systemd-sysupdate.timer systemd-sysupdate-reboot.timer bluefin-diskless-update-check.timer | tr '\n' ' ')"
if [ -e /run/machines/rootdisk.raw ]; then
    systemctl start bluefin-diskless-update-check.service || true
    echo "PROBE update-check=$(systemctl show -P Result bluefin-diskless-update-check.service) flag=$(test -e /run/reboot-required && echo set || echo none)"
    journalctl -b -o cat --no-pager -u bluefin-diskless-update-check.service | grep -v '^gpgv:' | tail -n 3 | sed 's/^/PROBE-LOG /'
fi
PROBE
[ -n "${DOGFOOD_EXTRA_PROBE:-}" ] && cat "${DOGFOOD_EXTRA_PROBE}" >> "${work}/probe.sh"
echo 'sync' >> "${work}/probe.sh"
echo 'echo "PROBE failed=$(systemctl --failed --no-legend | wc -l) $(systemctl --failed --no-legend --plain | cut -d" " -f1 | tr "\n" " ")"' >> "${work}/probe.sh"

cat > "${work}/probe.service" <<'UNIT'
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

# The probe reports on a second serial port: the getty on ttyS0 hangs up the
# console (vhangup) and would cut off a probe still writing to it.
"${qemu[@]}" -display none -monitor none -serial "file:${work}/serial.log" -serial "file:${work}/probe.log" \
    -smbios "$(cred dogfood.probe "${work}/probe.sh")" \
    -smbios "$(cred systemd.extra-unit.dogfood-probe.service "${work}/probe.service")" \
    </dev/null >/dev/null 2>&1 &
qemu_pid=$!
probe_done() { grep -aq 'PROBE failed=' "${work}/probe.log" 2>/dev/null; }
# Console output interleaves CSI, OSC and DCS escape sequences, sometimes in the
# middle of a line (the initrd's failure summary writes to the console while
# systemd-importd logs), so strip all three before matching.
clean_log() { sed -E 's/\x1b\][^\x07\x1b]*(\x07|\x1b\\)//g; s/\x1bP[^\x1b]*\x1b\\//g; s/\x1b\[[0-9;?]*[a-zA-Z]//g' | tr -d '\r'; }
refused() { clean_log < "${work}/serial.log" 2>/dev/null | grep -aqE "${refusal_re}"; }
status=1
if [ -n "${tamper}" ]; then
    stop() { probe_done || refused; }
else
    stop() { probe_done; }
fi
wait_for "${timeout_s}" "${qemu_pid}" stop && status=0
kill "${qemu_pid}" 2>/dev/null || true
wait "${qemu_pid}" 2>/dev/null || true
cat "${work}/serial.log" "${work}/probe.log" 2>/dev/null \
    | clean_log > "${dir}/dogfood-serial.log"
grep -a 'GET ' "${work}/http.log" > "${dir}/dogfood-http.log" || true
grep -aoE 'PROBE[ -].*' "${dir}/dogfood-serial.log" || true

if [ -n "${tamper}" ]; then
    served() { grep -aq "\"GET /$1 HTTP/1.1\" 200" "${dir}/dogfood-http.log"; }
    if probe_done; then
        echo "FAIL: tamper=${tamper}: the tampered image booted (serial log: ${dir}/dogfood-serial.log)" >&2
        status=1
    elif ! refused; then
        echo "FAIL: tamper=${tamper}: no refusal within ${timeout_s}s (serial log: ${dir}/dogfood-serial.log)" >&2
        tail -n 40 "${dir}/dogfood-serial.log" >&2
        status=1
    elif ! served "${image}" || ! served SHA256SUMS || ! served SHA256SUMS.gpg; then
        # Refused before it had the image and the signed manifest: that is a
        # transport failure, not a verification failure.
        echo "FAIL: tamper=${tamper}: the pull failed before fetching ${image}, SHA256SUMS and SHA256SUMS.gpg" >&2
        status=1
    elif ! grep -aq 'Secure boot enabled' "${dir}/dogfood-serial.log"; then
        echo "FAIL: tamper=${tamper}: refused, but the kernel did not run with Secure Boot enabled" >&2
        status=1
    else
        grep -aE "${refusal_re}|Failed to start Download of " "${dir}/dogfood-serial.log" | sed 's/^/REFUSED /' | head -n 5
        echo "PASS: tamper=${tamper}: ${image} refused after fetching the signed manifest (serial log: ${dir}/dogfood-serial.log)"
        status=0
    fi
    if [ "${status}" = 0 ] && [ -n "${DOGFOOD_EXPECT:-}" ] && ! grep -aqE -- "${DOGFOOD_EXPECT}" "${dir}/dogfood-serial.log"; then
        echo "FAIL: tamper=${tamper}: serial log does not match DOGFOOD_EXPECT=${DOGFOOD_EXPECT}" >&2
        status=1
    fi
    exit "${status}"
fi

failed="$(grep -a '\[FAILED\]' "${dir}/dogfood-serial.log" || true)"
if [ "${status}" = 0 ] && [ -n "${DOGFOOD_EXPECT:-}" ] && ! grep -aqE -- "${DOGFOOD_EXPECT}" "${dir}/dogfood-serial.log"; then
    echo "FAIL: booted, but the probe output does not match DOGFOOD_EXPECT=${DOGFOOD_EXPECT}" >&2
    status=1
elif [ "${status}" = 0 ] && ! grep -aq 'PROBE etc-writable=0' "${dir}/dogfood-serial.log"; then
    echo "FAIL: group- or world-writable paths under /etc: $(grep -aoE 'PROBE etc-writable=.*' "${dir}/dogfood-serial.log" | head -n1)" >&2
    status=1
elif [ "${status}" = 0 ] && ! grep -aq 'PROBE secureboot=enabled' "${dir}/dogfood-serial.log"; then
    # Firmware that refuses the enrollment payloads boots on in setup mode,
    # where nothing is verified; that is not a Secure Boot boot.
    echo "FAIL: booted without Secure Boot ($(grep -aoE 'PROBE secureboot=.*' "${dir}/dogfood-serial.log" | head -n1)); see the enrollment messages in the serial log" >&2
    status=1
elif [ "${status}" = 0 ] && [ -z "${failed}" ] && grep -aq 'PROBE failed=0' "${dir}/dogfood-serial.log"; then
    echo "PASS: ${boot} boot with no failed units (serial log: ${dir}/dogfood-serial.log)"
elif [ "${status}" = 0 ]; then
    echo "FAIL: booted, but units failed:" >&2
    echo "${failed}" >&2
    status=1
else
    echo "FAIL: boot probe did not report within ${timeout_s}s (serial log: ${dir}/dogfood-serial.log)" >&2
    tail -n 40 "${dir}/dogfood-serial.log" >&2
fi
exit "${status}"
