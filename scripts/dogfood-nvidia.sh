#!/usr/bin/env bash
# QEMU check of an NVIDIA driver sysext on a disk install without an NVIDIA GPU:
#   1. dogfood-install.sh <dir>: diskless boot, systemd-sysinstall, disk boot
#   2. disk boot: download the sysext into /var/lib/extensions
#   3. disk boot: systemd-sysext merges it at boot, and the probe asserts
#      that the extension-release matches the image, loading nvidia through
#      bluefin-sysext-modules gets as far as the driver's own init (which
#      finds no GPU) with no module signature rejection or unknown symbol,
#      ldconfig lists libcuda.so.1, the flavour guard
#      passed, and no unit failed: without a GPU the NVIDIA units skip
#      themselves, so the expected set of failed units is empty.
# Usage: dogfood-nvidia.sh <dir> <flavour>_<image-version>.raw.zst
# The sysext's image version must be the one of the image set in <dir>.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
dir="$(realpath "${1:?usage: $0 <dir> <sysext.raw.zst>}")"
sysext="$(realpath "${2:?usage: $0 <dir> <sysext.raw.zst>}")"
name="${sysext##*/}"; name="${name%.raw.zst}"
flavour="${name%_*}"
ver="${name##*_}"
export DOGFOOD_STATE="${DOGFOOD_STATE:-dist/dogfood-nvidia}"
state="$(realpath -m "${DOGFOOD_STATE}")"

echo "==> 1/3 install ${dir##*/} to disk"
bash "${here}/dogfood-install.sh" "${dir}"

export DOGFOOD_PORT="${DOGFOOD_PORT:-8765}"
export DOGFOOD_STATE_DISK="${state}/disk.raw"
export DOGFOOD_VARS="${state}/vars.fd"
export DOGFOOD_BOOT=disk
mkdir -p "${state}/serve"
ln -sf "${sysext}" "${state}/serve/${name}.raw.zst"
run() { DOGFOOD_EXTRA_PROBE="$2" bash "${here}/dogfood-diskless.sh" "$1" --check; }

cat > "${state}/fetch.probe" <<EOF
mkdir -p /var/lib/extensions
curl -sSf http://10.0.2.2:${DOGFOOD_PORT}/${name}.raw.zst | zstd -dq -o /var/lib/extensions/${name}.raw
echo "PROBE fetched=\$(ls /var/lib/extensions | tr '\n' ' ')"
EOF

cat > "${state}/nvidia.probe" <<EOF
echo "PROBE sysext=\$(systemd-sysext list --no-legend 2>/dev/null | cut -d' ' -f1 | tr '\n' ' ')"
echo "PROBE release=\$(tr '\n' ' ' < /usr/lib/extension-release.d/extension-release.${name})"
echo "PROBE guard=\$(systemctl is-active nvidia-flavour-guard.service) ldconfig-unit=\$(systemctl is-active nvidia-ldconfig.service)"
echo "PROBE load-unit=\$(systemctl show -P Result nvidia-load.service) \$(systemctl show -P ActiveState nvidia-load.service)"
echo "PROBE nodes-unit=\$(systemctl show -P ConditionResult nvidia-device-nodes.service) persistenced=\$(systemctl show -P ConditionResult nvidia-persistenced.service)"
kmods="\$(/usr/libexec/bluefin-sysext-modules --basedir 2>/dev/null)"
echo "PROBE sig=\$(for m in nvidia nvidia-uvm nvidia-modeset nvidia-drm; do modinfo -b "\${kmods}" -F sig_hashalgo "\${m}"; done | tr '\n' ' ')"
echo "PROBE nouveau-blacklisted=\$(modprobe -d "\${kmods}" -c | grep -cx 'blacklist nouveau')"
rc=0; /usr/libexec/bluefin-sysext-modules nvidia > /run/modprobe.log 2>&1 || rc=\$?
echo "PROBE modprobe=\${rc} \$(grep -v ' indexed ' /run/modprobe.log | tr '\n' ' ')"
journalctl -k -b -o cat --no-pager | grep -E 'NVRM|nvidia' | head -n 5 | sed 's/^/PROBE-LOG /'
echo "PROBE no-gpu=\$(journalctl -k -b -o cat --no-pager | grep -c 'NVRM: No NVIDIA GPU found')"
echo "PROBE sig-rejected=\$(journalctl -k -b -o cat --no-pager | cat - /run/modprobe.log | grep -ciE 'module verification failed|key was rejected|unsigned module|required key not available|unknown symbol')"
echo "PROBE libcuda=\$(ldconfig -p | grep -c 'libcuda.so.1 ')"
echo "PROBE firmware=\$(ls /usr/lib/firmware/nvidia/*/ | tr '\n' ' ')"
echo "PROBE nvidia-smi=\$(nvidia-smi -L > /dev/null 2>&1; echo \$?)"
EOF

echo "==> 2/3 download ${name} into /var/lib/extensions"
DOGFOOD_SERVE_EXTRA="${state}/serve" run "${dir}" "${state}/fetch.probe" | tee "${state}/2-fetch.log"
grep -q "PROBE fetched=.*${name}.raw" "${state}/2-fetch.log"

echo "==> 3/3 boot with ${name} merged"
run "${dir}" "${state}/nvidia.probe" | tee "${state}/3-nvidia.log"
log="${state}/3-nvidia.log"
grep -q "PROBE sysext=.*${name}" "${log}"
grep -q "PROBE release=NAME=${flavour} ID=bluefin-server EXTENSION_RELOAD_MANAGER=1 VERSION_ID=${ver} ARCHITECTURE=x86-64 " "${log}"
grep -q "PROBE guard=active ldconfig-unit=active" "${log}"
grep -q "PROBE load-unit=exec-condition inactive" "${log}"
grep -q "PROBE nodes-unit=no persistenced=no" "${log}"
grep -q "PROBE sig=sha512 sha512 sha512 sha512 " "${log}"
grep -q "PROBE nouveau-blacklisted=1" "${log}"
grep -q "PROBE modprobe=1 modprobe: ERROR: could not insert 'nvidia': No such device" "${log}"
grep -q "PROBE no-gpu=1" "${log}"
grep -q "PROBE sig-rejected=0" "${log}"
grep -q "PROBE libcuda=1" "${log}"
grep -q "PROBE failed=0" "${log}"
echo "PASS: ${name} merged on a disk install; the driver loads signed and finds no GPU, libcuda is in the linker cache, no unit failed"
