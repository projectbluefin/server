#!/usr/bin/env bash
# QEMU check that two appliances find each other by name over mDNS, with no
# DNS server knowing them: two diskless guests on one L2 segment
# (scripts/dogfood-lan.sh), each with only the base OS.
#   a  pinned machine ID (system.machine_id credential), no hostname: names
#      itself bluefin-<machine-id[:8]>, the same name on every boot
#   b  firstboot.hostname=blueserver-1: the provisioned name
# Each resolves the other's <hostname>.local through resolved
# (resolvectl) and through NSS (getent, nss-resolve), as any program would.
# Usage: dogfood-mdns.sh <dir with the release set>
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
dir="$(realpath "${1:?usage: $0 <dir>}")"
state="$(realpath -m "${DOGFOOD_STATE:-dist/dogfood-mdns}")"
base_port="${DOGFOOD_PORT:-8781}"
link_port="${DOGFOOD_LINK_PORT:-40180}"
a_id=a1b2c3d4e5f60718293a4b5c6d7e8f90
a_name="bluefin-${a_id:0:8}"
b_name=blueserver-1

rm -rf "${state}"
mkdir -p "${state}/a-creds" "${state}/b-creds"
printf '%s' "${a_id}" > "${state}/a-creds/system.machine_id"
printf '%s' "${b_name}" > "${state}/b-creds/firstboot.hostname"

cat > "${state}/peer.probe" <<'EOF'
peer="$(cat /run/credentials/@system/dogfood.peer 2>/dev/null)"
for _ in $(seq 240); do
    addr="$(resolvectl query -4 --legend=no "${peer}.local" 2>/dev/null | sed -n '1s/^[^ ]* \([0-9.]*\).*/\1/p')"
    [ -n "${addr}" ] && break
    sleep 1
done
nss="$(getent ahostsv4 "${peer}.local" 2>/dev/null | sed -n '1s/ .*//p')"
echo "PROBE peer=${peer}.local resolved=${addr:-none} nss=${nss:-none}"
# Stay up until the other guest has resolved this one too.
sleep 90
EOF

# shellcheck source=scripts/dogfood-lan.sh
. "${here}/dogfood-lan.sh"
lan_start "${state}" "${link_port}"
trap lan_stop EXIT

# boot <guest> <port> <mac suffix> <peer name>
boot() {
    mkdir -p "${state}/$1-set"
    for f in "${dir}"/*; do ln -sf "${f}" "${state}/$1-set/"; done
    printf '%s' "$4" > "${state}/$1-creds/dogfood.peer"
    DOGFOOD_PORT="$2" DOGFOOD_NET="$(nic "$3")" DOGFOOD_TIMEOUT=900 \
    DOGFOOD_CREDS="${state}/$1-creds" DOGFOOD_EXTRA_PROBE="${state}/peer.probe" \
        bash "${here}/dogfood-diskless.sh" "${state}/$1-set" --check > "${state}/$1.log" 2>&1
}

echo "==> two appliances on one L2 segment (logs: ${state}/{a,b}.log)"
boot a "${base_port}" 11 "${b_name}" & a_pid=$!
boot b "$((base_port + 1))" 12 "${a_name}" & b_pid=$!
rc=0
wait "${a_pid}" || rc=1
wait "${b_pid}" || rc=1
for g in a b; do grep -aoE 'PROBE (identity|prompt|peer|failed)=.*' "${state}/${g}.log" | sed "s/^/${g}: /" || true; done

check() { grep -aqE "$2" "${state}/$1.log" || { echo "FAIL: $1: no match for: $2" >&2; rc=1; }; }
check a "PROBE identity=ok hostname=${a_name} static=${a_name} "
check b "PROBE identity=ok hostname=${b_name} static=${b_name} "
check a "PROBE peer=${b_name}\.local resolved=10\.0\.2\.[0-9]+ nss=10\.0\.2\.[0-9]+$"
check b "PROBE peer=${a_name}\.local resolved=10\.0\.2\.[0-9]+ nss=10\.0\.2\.[0-9]+$"
[ "${rc}" = 0 ] || exit 1
echo "PASS: ${a_name} (from its machine ID) and ${b_name} (provisioned) resolve each other as <hostname>.local over mDNS"
