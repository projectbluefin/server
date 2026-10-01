#!/usr/bin/env bash
# End-to-end A/B check in QEMU with Secure Boot:
#   1. boot <dir> diskless and run systemd-sysinstall onto a blank disk
#   2. boot the installed disk (usr slot A, persistent root)
#   3. with <next-dir>: systemd-sysupdate to that version over HTTP, reboot,
#      and confirm the node runs it from slot B with a boot-counted UKI
#   4. with <broken-dir>: update to it, break it, and confirm boot counting
#      rolls the node back to <next-dir> on its own. DOGFOOD_BROKEN=slot
#      (default) corrupts its usr slot, so the initrd fails; DOGFOOD_BROKEN=unit
#      adds a unit that fails on that version only, so the boot reaches
#      multi-user.target but never boot-complete.target, and
#      bluefin-boot-deadline.timer (shortened to DOGFOOD_DEADLINE, default 2min)
#      must reboot it until systemd-boot falls back. After the fallback the
#      failed version must not count as pending: no kured flag, and the
#      nightly reboot unit is skipped.
# The updates run through systemd-sysupdate.service, the unit the
# preset-enabled timer starts, verify the signed SHA256SUMS and have the
# optional "zfs" sysupdate feature enabled, so the ZFS sysext follows the OS
# in lock-step and must still be active after the rollback. Once an update is
# staged the kured flag must be set, and the reboot unit must stand down while
# a stand-in kubelet.service runs. Every disk boot has both update timers
# enabled; a boot-counted UKI is blessed only after boot-complete.target,
# which requires that no unit failed.
# Usage: [DOGFOOD_BROKEN=slot|unit] dogfood-install.sh <dir> [<next-dir> [<broken-dir>]]
# <next-dir> and <broken-dir> are image sets with increasingly higher versions.
# DOGFOOD_PORT (default 8765) is shared with dogfood-diskless.sh's server.
# DOGFOOD_PROFILE=complete|core explicitly selects the signed USB installer
# profile for installation, then reuses the same disk for the A/B scenarios.
# Unset/none retains the original diskless, no-profile Core/legacy path.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
dir="$(realpath "${1:?usage: $0 <dir> [<next-dir> [<broken-dir>]]}")"
next="${2:+$(realpath "$2")}"
broken="${3:+$(realpath "$3")}"
profile="${DOGFOOD_PROFILE:-none}"
case "${profile}" in none|complete|core) ;; *) echo 'ERROR: DOGFOOD_PROFILE must be none, complete or core' >&2; exit 1 ;; esac
state="$(realpath -m "${DOGFOOD_STATE:-dist/dogfood-install}")"
[ ! -e "${state}" ] || { echo "ERROR: choose a fresh DOGFOOD_STATE; refusing to delete ${state}" >&2; exit 1; }
mkdir -p "${state}"
if [ "${profile}" = none ]; then truncate -s 16G "${state}/disk.raw"; fi

export DOGFOOD_PORT="${DOGFOOD_PORT:-8765}"
export DOGFOOD_STATE_DISK="${state}/disk.raw"
export DOGFOOD_VARS="${state}/vars.fd"
run() { DOGFOOD_EXTRA_PROBE="$2" bash "${here}/dogfood-diskless.sh" "$1" --check; }

cat > "${state}/install.probe" <<'EOF'
systemctl start run-bluefin-boot.mount
kernel="$(ls /run/bluefin/boot/EFI/Linux/bluefin-server-[0-9]*.efi)"
rc=0
systemd-sysinstall --erase=yes --confirm=no --variables=yes --reboot=no \
    --definitions=/run/bluefin/boot/bluefin/repart.d \
    --kernel="${kernel}" /dev/vdb > /run/sysinstall.log 2>&1 || rc=$?
echo "PROBE install=${rc}"
tail -n 15 /run/sysinstall.log | sed 's/^/PROBE-LOG /'
lsblk -no NAME,PARTLABEL,SIZE /dev/vdb | sed 's/^/PROBE-LOG /'
EOF

cat > "${state}/disk.probe" <<'EOF'
echo "PROBE usr-part=$(lsblk -rsno PARTLABEL /dev/mapper/usr | grep bluefin_usr_ | tr '\n' ' ')"
echo "PROBE zfs=$(systemctl is-active zfs.target) $(ls /var/lib/extensions 2>/dev/null | tr '\n' ' ')"
echo "PROBE boot-entry=$(bootctl status 2>/dev/null | sed -n 's/^ *Current Entry: *//p' | head -n1)"
echo "PROBE firstboot-ran=$(systemctl show -P ConditionResult systemd-firstboot.service)"
bootctl list --no-pager 2>/dev/null | sed -n 's/^ *\(title\|id\): */PROBE-LOG \1 /p'
systemctl start boot-complete.target 2>/dev/null || true
echo "PROBE ukis=$(ls /boot/EFI/Linux 2>/dev/null | tr '\n' ' ')"
echo "PROBE timers-enabled=$(systemctl is-enabled systemd-sysupdate.timer systemd-sysupdate-reboot.timer | tr '\n' ' ')"
echo "PROBE health=$(systemctl is-active systemd-boot-check-no-failures.service boot-complete.target | tr '\n' ' ')bless=$(/usr/lib/systemd/systemd-bless-boot status 2>/dev/null)"
echo "PROBE deadline=$(systemctl is-active bluefin-boot-deadline.timer) $(systemctl show -P ConditionResult bluefin-boot-deadline.timer)"
EOF

cat > "${state}/update.probe" <<'EOF'
mkdir -p /etc/sysupdate.d/zfs.feature.d
printf '[Feature]\nEnabled=true\n' > /etc/sysupdate.d/zfs.feature.d/enable.conf
for f in /usr/lib/sysupdate.d/*.transfer; do
    sed -e 's|^Path=https://.*|Path=http://10.0.2.2:@DOGFOOD_PORT@/|' \
        "${f}" > "/etc/sysupdate.d/${f##*/}"
done
rm -f /run/reboot-required
rc=0
systemctl start --wait systemd-sysupdate.service || rc=$?
echo "PROBE update=${rc}"
journalctl -b -o cat --no-pager -u systemd-sysupdate.service | tail -n 15 | sed 's/^/PROBE-LOG /'
timeout 60 systemd-sysupdate list --no-pager 2>&1 | sed 's/^/PROBE-LOG /'
echo "PROBE kured-flag=$(test -e /run/reboot-required && echo set || echo none)"
systemd-run --quiet --unit=kubelet.service sleep 600
systemctl start systemd-sysupdate-reboot.service
echo "PROBE interlock=$(systemctl show -P Result systemd-sysupdate-reboot.service)"
systemctl stop kubelet.service
EOF
sed -i "s|@DOGFOOD_PORT@|${DOGFOOD_PORT}|" "${state}/update.probe"

if [ "${profile}" = none ]; then
    echo "==> 1/4 diskless boot + systemd-sysinstall (no-profile legacy path)"
    run "${dir}" "${state}/install.probe" | tee "${state}/1-install.log"
    grep -q 'PROBE install=0' "${state}/1-install.log"
else
    echo "==> 1/4 signed native USB installer profile: ${profile}"
    DOGFOOD_STATE="${state}/native" DOGFOOD_TARGET_DISK="${state}/native/target.raw" \
        DOGFOOD_INSTALL_ONLY=0 DOGFOOD_PROFILE="${profile}" \
        bash "${here}/dogfood-installer.sh" "${dir}" | tee "${state}/1-install.log"
    export DOGFOOD_STATE_DISK="${state}/native/target.raw"
    export DOGFOOD_VARS="${state}/native/vars.fd"
fi

echo "==> 2/4 boot the installed disk"
DOGFOOD_BOOT=disk run "${dir}" "${state}/disk.probe" | tee "${state}/2-disk.log"
grep -q 'PROBE root=xfs' "${state}/2-disk.log"
grep -q 'PROBE timers-enabled=enabled enabled' "${state}/2-disk.log"
grep -q 'PROBE update-timers=active active inactive' "${state}/2-disk.log"

[ -n "${next}" ] || { echo "PASS: installed and booted from disk"; exit 0; }

echo "==> 3/4 systemd-sysupdate to $(basename "${next}")"
DOGFOOD_TIMEOUT="${DOGFOOD_UPDATE_TIMEOUT:-900}" DOGFOOD_BOOT=disk run "${next}" "${state}/update.probe" | tee "${state}/3-update.log"
grep -q 'PROBE update=0' "${state}/3-update.log"
grep -q 'PROBE kured-flag=set' "${state}/3-update.log"
grep -q 'PROBE interlock=exec-condition' "${state}/3-update.log"

echo "==> 4/4 boot the updated disk"
DOGFOOD_BOOT=disk run "${next}" "${state}/disk.probe" | tee "${state}/4-updated.log"
new_ver="$(ls "${next}"/bluefin-server-[0-9]*.efi | sed -n 's|.*/bluefin-server-\(.*\)\.efi$|\1|p')"
grep -q "PROBE os=bluefin-server ${new_ver}" "${state}/4-updated.log"
grep -q "PROBE zfs=active" "${state}/4-updated.log"
grep -q "PROBE health=active active bless=good" "${state}/4-updated.log"
[ -n "${broken}" ] || { echo "PASS: installed, updated A->B and booted ${new_ver}"; exit 0; }

bad_ver="$(ls "${broken}"/bluefin-server-[0-9]*.efi | sed -n 's|.*/bluefin-server-\(.*\)\.efi$|\1|p')"
mode="${DOGFOOD_BROKEN:-slot}"
case "${mode}" in
    slot)
        sed "s|^echo \"PROBE update=|dd if=/dev/urandom of=/dev/disk/by-partlabel/bluefin_usr_${bad_ver} bs=1M count=64 conv=fsync 2>/dev/null \&\& echo PROBE corrupted=${bad_ver}\necho \"PROBE update=|" \
            "${state}/update.probe" > "${state}/break.probe"
        cp "${state}/disk.probe" "${state}/rollback.probe" ;;
    unit)
        # A unit that fails on ${bad_ver} only, and a deadline short enough
        # for three tries in one run.
        { cat "${state}/update.probe"; cat <<BREAK; } > "${state}/break.probe"
cat > /etc/systemd/system/dogfood-broken.service <<'UNIT'
[Unit]
Description=Dogfood: fail on ${bad_ver} only
ConditionOSRelease=IMAGE_VERSION=${bad_ver}
[Service]
Type=oneshot
ExecStart=/usr/bin/false
[Install]
WantedBy=multi-user.target
UNIT
systemctl enable dogfood-broken.service 2>/dev/null
mkdir -p /etc/systemd/system/bluefin-boot-deadline.timer.d
printf '[Timer]\nOnBootSec=\nOnBootSec=${DOGFOOD_DEADLINE:-2min}\n' > /etc/systemd/system/bluefin-boot-deadline.timer.d/dogfood.conf
echo "PROBE corrupted=${bad_ver} (dogfood-broken.service)"
BREAK
        # A broken boot reports the gate and waits for the deadline to reboot
        # it; only the fallback boot finishes the probe, and reads the
        # deadline's log of every try from the persistent journal.
        { cat <<GATE; cat "${state}/disk.probe" - <<'AFTER'; } > "${state}/rollback.probe"
if [ "\$(. /usr/lib/os-release; echo "\${IMAGE_VERSION}")" = ${bad_ver} ]; then
    echo "PROBE counted-boot=${bad_ver} bless=\$(/usr/lib/systemd/systemd-bless-boot status) failed=\$(systemctl --failed --no-legend --plain | cut -d' ' -f1 | tr '\n' ' ')deadline=\$(systemctl is-active bluefin-boot-deadline.timer)"
    exec sleep infinity
fi
GATE
journalctl -o cat --no-pager -u bluefin-boot-deadline.service | grep 'boot deadline' | sed 's/^/PROBE-LOG /'
rm -f /run/reboot-required
systemctl start --wait systemd-sysupdate.service || true
journalctl -b -o cat --no-pager -u systemd-sysupdate.service | grep 'failed its boot tries' | sed 's/^/PROBE-LOG /'
echo "PROBE after-rollback kured-flag=$(test -e /run/reboot-required && echo set || echo none)"
systemctl start systemd-sysupdate-reboot.service
echo "PROBE after-rollback reboot-unit=$(systemctl show -P Result systemd-sysupdate-reboot.service)"
AFTER
        ;;
    *) echo "ERROR: DOGFOOD_BROKEN must be slot or unit" >&2; exit 1 ;;
esac

echo "==> 5/6 update to ${bad_ver} and break it (${mode})"
DOGFOOD_TIMEOUT="${DOGFOOD_UPDATE_TIMEOUT:-900}" DOGFOOD_BOOT=disk run "${broken}" "${state}/break.probe" | tee "${state}/5-break.log"
grep -q "PROBE corrupted=${bad_ver}" "${state}/5-break.log"

echo "==> 6/6 boot: ${bad_ver} must fail its tries and fall back to ${new_ver}"
# In unit mode the broken boots log [FAILED] for the deliberately failed unit,
# so the fallback boot is judged by its own probe below.
DOGFOOD_TIMEOUT="${DOGFOOD_ROLLBACK_TIMEOUT:-1800}" DOGFOOD_BOOT=disk run "${broken}" "${state}/rollback.probe" \
    | tee "${state}/6-rollback.log" || [ "${mode}" = unit ]
grep -q "PROBE os=bluefin-server ${new_ver}" "${state}/6-rollback.log"
grep -q "bluefin-server-${bad_ver}+0-3.efi" "${state}/6-rollback.log"
grep -q "PROBE zfs=active" "${state}/6-rollback.log"
if [ "${mode}" = unit ]; then
    [ "$(grep -Ec "PROBE counted-boot=${bad_ver} bless=(indeterminate|dirty) failed=dogfood-broken.service .*deadline=active" "${state}/6-rollback.log")" = 3 ]
    [ "$(grep -c "PROBE-LOG Bluefin Server ${bad_ver} did not reach boot-complete.target .*rebooting so systemd-boot falls back" "${state}/6-rollback.log")" = 3 ]
    grep -q "PROBE deadline=inactive no" "${state}/6-rollback.log"
    grep -q "PROBE health=active active bless=clean" "${state}/6-rollback.log"
    grep -q "PROBE after-rollback kured-flag=none" "${state}/6-rollback.log"
    grep -q "PROBE after-rollback reboot-unit=exec-condition" "${state}/6-rollback.log"
    grep -q "PROBE failed=0" "${state}/6-rollback.log"
fi
echo "PASS: installed, updated A->B, and rolled back from a broken (${mode}) ${bad_ver} to ${new_ver}"
