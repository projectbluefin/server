#!/usr/bin/env bash
# End-to-end A/B check in QEMU with Secure Boot:
#   1. boot <dir> diskless and run systemd-sysinstall onto a blank disk
#   2. boot the installed disk (usr slot A, persistent root); its first boot
#      names it bluefin-<machine-id[:8]>, and the probe renames it with
#      hostnamectl, a name every later boot must keep
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
# in lock-step and must still be active after the rollback.
# DOGFOOD_SYSEXT is a comma-separated list of zfs (the default) and nvidia.
# nvidia enables the "nvidia-open-595" feature plus the NVIDIA Container
# Toolkit component and its activation unit; after the update and after the
# rollback the driver sysext matching the booted version must be merged, its
# units must skip themselves (QEMU has no NVIDIA GPU), loading nvidia through
# bluefin-sysext-modules must reach the driver's own init (signed, "No NVIDIA
# GPU found") and the toolkit must be merged. zfs,nvidia merges both module
# sysexts at once; zfs must also have its module loaded. Once an update is
# staged the kured flag must be set, and the reboot unit must stand down while
# a stand-in kubelet.service runs. Every disk boot has both update timers
# enabled; a boot-counted UKI is blessed only after boot-complete.target,
# which requires that no unit failed.
# Usage: [DOGFOOD_BROKEN=slot|unit] [DOGFOOD_SYSEXT=zfs|nvidia|zfs,nvidia] dogfood-install.sh <dir> [<next-dir> [<broken-dir>]]
# <next-dir> and <broken-dir> are image sets with increasingly higher versions.
# DOGFOOD_PORT (default 8765) is shared with dogfood-diskless.sh's server.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
dir="$(realpath "${1:?usage: $0 <dir> [<next-dir> [<broken-dir>]]}")"
next="${2:+$(realpath "$2")}"
broken="${3:+$(realpath "$3")}"
state="$(realpath "${DOGFOOD_STATE:-dist/dogfood-install}")"
rm -rf "${state}"
mkdir -p "${state}"
truncate -s 16G "${state}/disk.raw"

features="" toolkit=0 want_zfs=0 want_nvidia=0
IFS=, read -r -a sysexts <<< "${DOGFOOD_SYSEXT:-zfs}"
for sysext in "${sysexts[@]}"; do
    case "${sysext}" in
        zfs) want_zfs=1 features="${features} zfs" ;;
        nvidia) want_nvidia=1 toolkit=1 features="${features} nvidia-open-595" ;;
        *) echo "ERROR: DOGFOOD_SYSEXT must list zfs and/or nvidia, comma-separated" >&2; exit 1 ;;
    esac
done
features="${features# }"

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
# bluefin-sysext-activate.service re-requests multi-user.target after the
# merge, so the load units may still be queued or running.
for _ in $(seq 180); do
    systemctl list-jobs --no-legend | grep -qE 'zfs-load-module|nvidia-load' || break
    sleep 1
done
echo "PROBE zfs-module=$(test -d /sys/module/zfs && echo loaded || echo missing) load=$(systemctl show -P Result zfs-load-module.service)"
echo "PROBE boot-entry=$(bootctl status 2>/dev/null | sed -n 's/^ *Current Entry: *//p' | head -n1)"
echo "PROBE firstboot-ran=$(systemctl show -P ConditionResult systemd-firstboot.service)"
# The disk's first boot named it bluefin-<machine-id[:8]>; rename it as an
# operator would. Every later boot (reboot, A/B update, rollback) must keep it.
case "$(hostname)" in bluefin-*) hostnamectl set-hostname dogfood-renamed && echo "PROBE renamed=$(hostnamectl --static)" ;; esac
bootctl list --no-pager 2>/dev/null | sed -n 's/^ *\(title\|id\): */PROBE-LOG \1 /p'
systemctl start boot-complete.target 2>/dev/null || true
echo "PROBE ukis=$(ls /boot/EFI/Linux 2>/dev/null | tr '\n' ' ')"
echo "PROBE timers-enabled=$(systemctl is-enabled systemd-sysupdate.timer systemd-sysupdate-reboot.timer | tr '\n' ' ')"
echo "PROBE health=$(systemctl is-active systemd-boot-check-no-failures.service boot-complete.target | tr '\n' ' ')bless=$(/usr/lib/systemd/systemd-bless-boot status 2>/dev/null)"
echo "PROBE deadline=$(systemctl is-active bluefin-boot-deadline.timer) $(systemctl show -P ConditionResult bluefin-boot-deadline.timer)"
iv="$(. /usr/lib/os-release; echo "${IMAGE_VERSION}")"
echo "PROBE nvidia-driver=$(cat /usr/lib/extension-release.d/extension-release.nvidia-open-595_* 2>/dev/null | sed -n 's/^VERSION_ID=//p' | tr '\n' ' ')image=${iv} file=$(ls /var/lib/extensions 2>/dev/null | grep -x "nvidia-open-595_${iv}.raw") guard=$(systemctl is-active nvidia-flavour-guard.service) load=$(systemctl show -P Result nvidia-load.service)"
echo "PROBE nvidia-toolkit=$(test -e /usr/lib/extension-release.d/extension-release.nvidia-container-toolkit && echo merged) activate=$(systemctl show -P Result nvidia-container-toolkit-activate.service) ctk=$(nvidia-ctk --version 2>/dev/null | head -n1)"
echo "PROBE nvidia-toolkit-staged=$(ls /var/lib/nvidia-container-toolkit 2>/dev/null | tr '\n' ' ')"
if [ -e "/usr/lib/extension-release.d/extension-release.nvidia-open-595_${iv}" ]; then
    # nvidia-load.service skipped itself (no GPU); load by hand through the
    # helper: it must resolve the in-tree dependencies and reach the driver's
    # init, which fails with ENODEV, not "not found" or "Unknown symbol".
    kmods="$(/usr/libexec/bluefin-sysext-modules --basedir 2>/dev/null)"
    echo "PROBE nvidia-sig=$(for m in nvidia nvidia-uvm nvidia-modeset nvidia-drm; do modinfo -b "${kmods}" -F sig_hashalgo "${m}"; done | tr '\n' ' ')"
    modprobe -d "${kmods}" --show-depends nvidia-drm | sed 's|^|PROBE-LOG nvidia-drm deps: |'
    rc=0; /usr/libexec/bluefin-sysext-modules nvidia > /run/nvidia-helper.log 2>&1 || rc=$?
    echo "PROBE nvidia-helper=${rc} $(grep -v ' indexed ' /run/nvidia-helper.log | tr '\n' ' ')"
    echo "PROBE nvidia-no-gpu=$(journalctl -k -b -o cat --no-pager | grep -c 'NVRM: No NVIDIA GPU found')"
    echo "PROBE nvidia-rejected=$(journalctl -k -b -o cat --no-pager | cat - /run/nvidia-helper.log | grep -ciE 'module verification failed|key was rejected|unsigned module|required key not available|unknown symbol')"
    echo "PROBE nouveau-blacklisted=$(modprobe -d "${kmods}" -c | grep -cx 'blacklist nouveau')"
fi
EOF

cat > "${state}/update.probe" <<'EOF'
for feature in @FEATURES@; do
    mkdir -p "/etc/sysupdate.d/${feature}.feature.d"
    printf '[Feature]\nEnabled=true\n' > "/etc/sysupdate.d/${feature}.feature.d/enable.conf"
done
for f in /usr/lib/sysupdate.d/*.transfer; do
    sed -e 's|^Path=https://.*|Path=http://10.0.2.2:@DOGFOOD_PORT@/|' \
        "${f}" > "/etc/sysupdate.d/${f##*/}"
done
if [ @TOOLKIT@ = 1 ]; then
    # Own version axis: the component is fetched and merged on the next boot
    # by its opt-in activation unit, not by the OS update.
    mkdir -p /etc/sysupdate.nvidia-container-toolkit.d
    for f in /usr/lib/sysupdate.nvidia-container-toolkit.d/*.transfer; do
        sed -e 's|^Path=https://.*|Path=http://10.0.2.2:@DOGFOOD_PORT@/|' \
            "${f}" > "/etc/sysupdate.nvidia-container-toolkit.d/${f##*/}"
    done
    systemctl enable nvidia-container-toolkit-activate.service 2>/dev/null
fi
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
sed -i -e "s|@DOGFOOD_PORT@|${DOGFOOD_PORT}|" -e "s|@FEATURES@|${features}|" \
    -e "s|@TOOLKIT@|${toolkit}|" "${state}/update.probe"

# The lock-step sysexts matching the booted version $1 are active in log $2.
sysext_active() {
    local v="$1" log="$2" ctk
    if [ "${want_zfs}" = 1 ]; then
        grep -q "PROBE zfs=active" "${log}"
        grep -q "PROBE zfs-module=loaded load=success" "${log}"
    fi
    [ "${want_nvidia}" = 1 ] || return 0
    grep -q "PROBE nvidia-driver=${v} image=${v} file=nvidia-open-595_${v}.raw guard=active load=exec-condition" "${log}"
    grep -q "PROBE nvidia-sig=sha512 sha512 sha512 sha512 " "${log}"
    grep -q "PROBE nvidia-helper=1 modprobe: ERROR: could not insert 'nvidia': No such device " "${log}"
    grep -Eq "PROBE nvidia-no-gpu=[1-9]" "${log}"
    grep -q "PROBE nvidia-rejected=0" "${log}"
    grep -q "PROBE nouveau-blacklisted=1" "${log}"
    ctk="$(ls "${next}"/nvidia-container-toolkit-*.raw.zst | sed -n 's|.*/nvidia-container-toolkit-\(.*\)\.raw\.zst$|\1|p')"
    grep -q "PROBE nvidia-toolkit=merged activate=success ctk=NVIDIA Container Toolkit CLI version ${ctk}" "${log}"
    grep -Eq "PROBE nvidia-toolkit-staged=.*nvidia-container-toolkit-${ctk}\.raw " "${log}"
}

echo "==> 1/4 diskless boot + systemd-sysinstall"
run "${dir}" "${state}/install.probe" | tee "${state}/1-install.log"
grep -q 'PROBE install=0' "${state}/1-install.log"

echo "==> 2/4 boot the installed disk"
DOGFOOD_BOOT=disk run "${dir}" "${state}/disk.probe" | tee "${state}/2-disk.log"
grep -q 'PROBE root=xfs' "${state}/2-disk.log"
grep -q 'PROBE timers-enabled=enabled enabled' "${state}/2-disk.log"
grep -q 'PROBE update-timers=active active inactive' "${state}/2-disk.log"
grep -Eq 'PROBE identity=ok hostname=bluefin-[0-9a-f]{8} static=bluefin-[0-9a-f]{8} ' "${state}/2-disk.log"
grep -q 'PROBE renamed=dogfood-renamed' "${state}/2-disk.log"

[ -n "${next}" ] || { echo "PASS: installed and booted from disk"; exit 0; }

echo "==> 3/4 systemd-sysupdate to $(basename "${next}")"
DOGFOOD_TIMEOUT="${DOGFOOD_UPDATE_TIMEOUT:-900}" DOGFOOD_BOOT=disk run "${next}" "${state}/update.probe" | tee "${state}/3-update.log"
grep -q 'PROBE update=0' "${state}/3-update.log"
grep -q 'PROBE kured-flag=set' "${state}/3-update.log"
grep -q 'PROBE interlock=exec-condition' "${state}/3-update.log"
grep -q 'PROBE identity=ok hostname=dogfood-renamed static=dogfood-renamed ' "${state}/3-update.log"

echo "==> 4/4 boot the updated disk"
DOGFOOD_BOOT=disk run "${next}" "${state}/disk.probe" | tee "${state}/4-updated.log"
new_ver="$(ls "${next}"/bluefin-server-[0-9]*.efi | sed -n 's|.*/bluefin-server-\(.*\)\.efi$|\1|p')"
grep -q "PROBE os=bluefin-server ${new_ver}" "${state}/4-updated.log"
sysext_active "${new_ver}" "${state}/4-updated.log"
grep -q "PROBE health=active active bless=good" "${state}/4-updated.log"
grep -q 'PROBE identity=ok hostname=dogfood-renamed static=dogfood-renamed ' "${state}/4-updated.log"
[ -n "${broken}" ] || { echo "PASS: installed, updated A->B and booted ${new_ver} with the ${features} sysext(s)"; exit 0; }

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
sysext_active "${new_ver}" "${state}/6-rollback.log"
if [ "${mode}" = unit ]; then
    [ "$(grep -Ec "PROBE counted-boot=${bad_ver} bless=(indeterminate|dirty) failed=dogfood-broken.service .*deadline=active" "${state}/6-rollback.log")" = 3 ]
    [ "$(grep -c "PROBE-LOG Bluefin Server ${bad_ver} did not reach boot-complete.target .*rebooting so systemd-boot falls back" "${state}/6-rollback.log")" = 3 ]
    grep -q "PROBE deadline=inactive no" "${state}/6-rollback.log"
    grep -q "PROBE health=active active bless=clean" "${state}/6-rollback.log"
    grep -q "PROBE after-rollback kured-flag=none" "${state}/6-rollback.log"
    grep -q "PROBE after-rollback reboot-unit=exec-condition" "${state}/6-rollback.log"
    grep -q "PROBE failed=0" "${state}/6-rollback.log"
fi
echo "PASS: installed, updated A->B, and rolled back from a broken (${mode}) ${bad_ver} to ${new_ver} with the ${features} sysext(s)"
