#!/usr/bin/env bash
# QEMU check of the USB installer's Homelab entries, offline, with Secure
# Boot: two blank disks become a homelab from bluefin-server-installer_<ver>.raw
# alone.
#
#   1. control plane: the stick's "Homelab: control plane" boot entry (the
#      installer UKI's profile, picked with loader.conf's default= on a copy
#      of the stick) installs onto a blank disk with no network, with a TPM2
#      (swtpm), so systemd-sysinstall seals the template credential to it and
#      the installed initrd must unseal it
#   2. its first boot on the LAN: bluefin-sysext-fetch installs the kubeadm
#      and homelab sysexts from the copy the installer put on the ESP (no
#      download), kubeadm init, the default homelab components, and the join
#      passphrase it generated (read here from the probe, as a person reads
#      the console)
#   3. node: the "Homelab: node" entry installs a second blank disk offline,
#      with the passphrase as the bluefin-cluster.passphrase credential (what
#      the installer's prompt would write), without a TPM (null-key sealed
#      credentials)
#   4. its first boot: same seed, then it finds the control plane over mDNS
#      and joins; the control plane sees both nodes Ready
#
# The installs are unattended the way scripts/dogfood-installer.sh makes them
# (a systemd-sysinstall drop-in credential re-running the image drop-in's
# ExecStart= with --confirm=no and the target disk), which also proves the
# image drop-in's $BLUEFIN_INSTALL_ARGS reaches sysinstall.
# Needs guest internet for the cluster images; DOGFOOD_DNS as in
# dogfood-homelab-cluster.sh.
# Usage: dogfood-homelab-installer.sh <dir with bluefin-server-installer_<ver>.raw>
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
dir="$(realpath "${1:?usage: $0 <artifact dir>}")"
state="$(realpath -m "${DOGFOOD_STATE:-dist/dogfood-homelab-installer}")"
link_port="${DOGFOOD_LINK_PORT:-40190}"
dropin_src="${here}/../files/os/systemd/system/systemd-sysinstall.service.d/10-bluefin-installer.conf"
target_serial=bluefin-target
target_dev="/dev/disk/by-id/virtio-${target_serial}"

# shellcheck disable=SC2012 # release file names have no odd characters
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
fail() { echo "FAIL: $* (logs: ${state})" >&2; exit 1; }
cred() { printf 'type=11,value=io.systemd.credential.binary:%s=%s' "$1" "$(base64 -w0 < "$2")"; }

# A copy of the stick whose systemd-boot starts the profile for <machine>
# (cp: homelab-control-plane, node: homelab-node).
stick_for() {
    local role="$1" stick="${state}/$1-stick.raw" off
    [ "${role}" != cp ] || role=control-plane
    cp --sparse=always "${installer}" "${stick}"
    off="$(sfdisk --json "${stick}" | python3 -c 'import json, sys
print(next(p["start"] for p in json.load(sys.stdin)["partitiontable"]["partitions"] if p.get("name") == "bluefin-installer") * 512)')"
    printf 'timeout 3\nconsole-mode keep\nsecure-boot-enroll if-safe\ndefault bluefin-server-installer_*@homelab-%s\n' "${role}" \
        > "${state}/$1-loader.conf"
    mcopy -o -i "${stick}@@${off}" "${state}/$1-loader.conf" ::/loader/loader.conf
    echo "${stick}"
}

# QEMU for one machine; its serial ports land in ${state}/<name>.ttyS{0,1,2}.
pids=()
tpm_pids=()
cleanup() { kill "${pids[@]}" "${tpm_pids[@]}" 2>/dev/null || true; lan_stop; }
# vm <name> <machine> <qemu args...>: start it in the background; VM_PID.
vm() {
    local name="$1" machine="$2" log="${state}/$1"
    shift 2
    local tpm=()
    if [ -d "${state}/${machine}-tpm" ]; then
        rm -f "${state}/${machine}-tpm/sock"
        swtpm socket --tpm2 --tpmstate "dir=${state}/${machine}-tpm" \
            --ctrl "type=unixio,path=${state}/${machine}-tpm/sock" --flags startup-clear --terminate \
            > "${state}/${name}.swtpm.log" 2>&1 &
        tpm_pids+=($!)
        for _ in $(seq 50); do [ -S "${state}/${machine}-tpm/sock" ] && break; sleep 0.1; done
        # shellcheck disable=SC2054 # commas belong to the QEMU options
        tpm=(-chardev "socket,id=chrtpm,path=${state}/${machine}-tpm/sock"
             -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-crb,tpmdev=tpm0)
    fi
    # shellcheck disable=SC2054 # commas belong to the QEMU options
    qemu-system-x86_64 -machine q35,smm=on,accel=kvm -cpu host -m "${MEM}" -smp 2 \
        -global driver=cfi.pflash01,property=secure,value=on \
        -drive if=pflash,format=raw,unit=0,readonly=on,file="${code}" \
        -drive if=pflash,format=raw,unit=1,file="${state}/${machine}-vars.fd" \
        -display none -monitor none -no-reboot "${tpm[@]}" "$@" \
        -serial "file:${log}.ttyS0" -serial "file:${log}.ttyS1" -serial "file:${log}.ttyS2" \
        </dev/null >"${log}.qemu.log" 2>&1 &
    VM_PID=$!
    pids+=("${VM_PID}")
}
# finish <name> <pid> <done-regex> <timeout>: wait for the regex on ttyS1 or
# for QEMU to exit (-no-reboot), then stop it; 1 on a timeout.
finish() {
    local name="$1" pid="$2" done_re="$3" deadline=$(( $(date +%s) + $4 )) log="${state}/$1" rc=0
    while kill -0 "${pid}" 2>/dev/null && [ "$(date +%s)" -lt "${deadline}" ]; do
        [ -n "${done_re}" ] && grep -aqE "${done_re}" "${log}.ttyS1" 2>/dev/null && { sleep 3; break; }
        sleep 2
    done
    if kill -0 "${pid}" 2>/dev/null; then
        [ "$(date +%s)" -lt "${deadline}" ] || rc=1
        kill "${pid}" 2>/dev/null || true
    fi
    wait "${pid}" 2>/dev/null || true
    for s in ttyS0 ttyS1 ttyS2; do
        sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\x1bP[^\x1b]*\x1b\\//g' "${log}.${s}" 2>/dev/null | tr -d '\r' > "${log}.${s}.log" || true
    done
    grep -aoE 'PROBE[ -].*' "${log}.ttyS1.log" | grep -v '^PROBE-LOG live' | sed "s/^/${name}: /" || true
    return "${rc}"
}

# The unattended install: the image drop-in's ExecStart= (with its
# $BLUEFIN_INSTALL_ARGS) plus --confirm=no and the target disk.
exec_start="$(sed -n 's/^ExecStart=\(..*\)$/\1/p' "${dropin_src}" | tail -n1)"
# shellcheck disable=SC2016 # the literal word systemd expands
[[ "${exec_start}" == *' $BLUEFIN_INSTALL_ARGS' ]] || fail "the image drop-in does not append \$BLUEFIN_INSTALL_ARGS"
cat > "${state}/sysinstall.conf" <<EOF
[Unit]
Wants=dogfood-journal.service

[Service]
StandardInput=null
StandardError=journal+console
ExecStart=
ExecStart=${exec_start} --confirm=no ${target_dev}
ExecStopPost=/bin/bash -c 'exec >/dev/ttyS1 2>&1; echo "PROBE sysinstall=\$\${SERVICE_RESULT} \$\${EXIT_STATUS} homelab-install=\$\$(systemctl show -P Result bluefin-homelab-install.service)"; cat /run/bluefin-homelab-install/sysinstall.env | sed "s/^/PROBE-LOG env /"; udevadm settle -t 10 || true; mkdir -p /run/t; mount -o ro ${target_dev}-part1 /run/t && { echo "PROBE esp-seed=\$\$(echo \$\$(ls /run/t/bluefin/extensions)) "; echo "PROBE esp-creds=\$\$(echo \$\$(ls /run/t/*/ | grep "cred\$\$")) "; cat /run/t/loader/entries/*.conf | sed "s/^/PROBE-LOG entry /"; umount /run/t; }'
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
install_creds=(-smbios "$(cred systemd.extra-unit.dogfood-journal.service "${state}/journal.service")"
    -smbios "$(cred systemd.unit-dropin.systemd-sysinstall.service "${state}/sysinstall.conf")")
for kv in firstboot.locale=C.UTF-8 firstboot.timezone=UTC 'passwd.hashed-password.root=!*'; do
    printf '%s' "${kv#*=}" > "${state}/${kv%%=*}"
    install_creds+=(-smbios "$(cred "${kv%%=*}" "${state}/${kv%%=*}")")
done

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

cat > "${state}/common.probe" <<'EOF'
journalctl -f -n all -o cat -u bluefin-sysext-fetch.service -u kubeadm-init.service -u bluefin-homelab-apply.service -u 'bluefin-cluster-*' | sed -u 's/^/PROBE-LOG live: /' &
echo "PROBE os=$(. /usr/lib/os-release; echo "${IMAGE_ID} ${IMAGE_VERSION}") secureboot=$(bootctl status 2>/dev/null | sed -n 's/.*Secure Boot: *//p' | head -n1) tpm=$(ls /sys/class/tpm 2>/dev/null | tr '\n' ' ')"
echo "PROBE root=$(findmnt -no FSTYPE /) ignition=$([ -e /etc/bluefin/homelab.conf.template ] && echo applied)"
echo "PROBE creds=$(ls /run/credentials/@encrypted 2>/dev/null | tr '\n' ' ')"
for _ in $(seq 120); do [ "$(systemctl show -P ActiveState bluefin-sysext-fetch.service)" = active ] && break; sleep 5; done
echo "PROBE fetch=$(systemctl show -P Result bluefin-sysext-fetch.service) $(journalctl -b -o cat -u bluefin-sysext-fetch.service | sed -n 's/.*: merged the \(.*\) sysext(s) for .* (\(.*\))$/\1 via \2/p' | tr ' ' '-') seed-left=$(ls "$(bootctl --print-esp-path)/bluefin" 2>/dev/null | grep -c extensions)"
echo "PROBE merged=$(ls /usr/lib/extension-release.d | sed 's/^extension-release\.//' | tr '\n' ' ')"
echo "PROBE conf role=$(sed -n 's/^HOMELAB_ROLE=//p' /etc/bluefin/homelab.conf) passphrase-lines=$(grep -c '^HOMELAB_JOIN_PASSPHRASE' /etc/bluefin/homelab.conf)"
EOF

cat > "${state}/cp.probe" <<'EOF'
export KUBECONFIG=/etc/kubernetes/admin.conf
for _ in $(seq 360); do pass="$(bluefin-cluster passphrase 2>/dev/null)" && [ -n "${pass}" ] && break; sleep 5; done
# Test only: handed to the node's install, as a person reads it off the console.
echo "PROBE cp-passphrase=${pass}"
for _ in $(seq 720); do [ "$(systemctl show -P ActiveState bluefin-homelab-apply.service)" = active ] && break; sleep 5; done
journalctl -b -o cat --no-pager -u bluefin-homelab-apply.service | tail -n 15 | sed 's/^/PROBE-LOG apply: /'
echo "PROBE cp-init=$(systemctl show -P ActiveState kubeadm-init.service) apply=$(systemctl show -P ActiveState bluefin-homelab-apply.service)/$(systemctl show -P Result bluefin-homelab-apply.service)"
ready() { kubectl get nodes -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' 2>/dev/null | grep -c True; }
for i in $(seq 540); do
    [ "$(ready)" -ge 2 ] && break
    [ $((i % 30)) = 0 ] && kubectl get nodes --no-headers 2>&1 | sed 's/^/PROBE-LOG nodes: /'
    sleep 5
done
kubectl get nodes -o wide --no-headers | sed 's/^/PROBE-LOG node: /'
kubectl get pods -A --no-headers | sed 's/^/PROBE-LOG pod: /'
echo "PROBE cp-nodes-ready=$(ready) nodes=$(kubectl get nodes --no-headers | wc -l)"
# Release the node (until now pods may run on it), and give it time to see it.
kubectl label nodes --all --overwrite dogfood-done=true >/dev/null
sleep 60
EOF
cat > "${state}/node.probe" <<'EOF'
for _ in $(seq 600); do [ -e /var/lib/bluefin-cluster/joined ] && break; sleep 5; done
echo "PROBE node-joined=$([ -e /var/lib/bluefin-cluster/joined ] && echo yes || echo no) kubelet=$(systemctl is-active kubelet.service)"
k() { kubectl --kubeconfig /etc/kubernetes/kubelet.conf "$@"; }
for _ in $(seq 180); do
    [ "$(k get node "$(hostname)" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)" = True ] && break
    sleep 5
done
echo "PROBE node-ready=$(k get node "$(hostname)" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
# Stay up, running its share of the pods, until the control plane is done.
for _ in $(seq 720); do
    [ "$(k get node "$(hostname)" -o jsonpath='{.metadata.labels.dogfood-done}' 2>/dev/null)" = true ] && break
    sleep 5
done
EOF
for role in cp node; do
    # shellcheck disable=SC2016,SC2028 # a line of the guest's probe
    { cat "${state}/common.probe" "${state}/${role}.probe"; echo 'echo "PROBE failed=$(systemctl --failed --no-legend | wc -l) $(systemctl --failed --no-legend --plain | cut -d" " -f1 | tr "\n" " ")"'; } \
        > "${state}/${role}-probe.sh"
done
disk_creds() {
    printf '%s\n' -smbios "$(cred dogfood.probe "${state}/$1-probe.sh")" \
        -smbios "$(cred systemd.extra-unit.dogfood-probe.service "${state}/probe.service")" \
        -smbios "$(cred systemd.unit-dropin.multi-user.target~dogfood-probe "${state}/probe-wants.conf")" \
        -smbios "$(cred passwd.hashed-password.root "${state}/passwd.hashed-password.root")"
    if [ -n "${DOGFOOD_DNS:-}" ]; then
        printf '%s\n' "${DOGFOOD_DNS}" > "${state}/network.dns"
        printf '%s\n' -smbios "$(cred network.dns "${state}/network.dns")"
    fi
}

# shellcheck source=scripts/dogfood-lan.sh
. "${here}/dogfood-lan.sh"
lan_start "${state}" "${link_port}"
trap cleanup EXIT

# install <role> [qemu args...]: enroll keys, then install.
install() {
    local role="$1" stick target="${state}/$1-disk.raw"
    shift 1
    stick="$(stick_for "${role}")"
    cp "${vars_tmpl}" "${state}/${role}-vars.fd"
    truncate -s 16G "${target}"
    # shellcheck disable=SC2054 # commas belong to the QEMU options
    local stick_args=(-drive "if=none,id=stick,format=raw,file=${stick}" -device virtio-blk-pci,drive=stick,serial=bluefin-installer)
    MEM=4096 vm "${role}-1-enroll" "${role}" "${stick_args[@]}" -nic none
    finish "${role}-1-enroll" "${VM_PID}" '' 300 || fail "${role}: key enrollment timed out"
    grep -aq 'successfully enrolled' "${state}/${role}-1-enroll.ttyS0.log" || fail "${role}: key enrollment"
    MEM=4096 vm "${role}-2-install" "${role}" "${stick_args[@]}" \
        -drive "if=none,id=target,format=raw,file=${target}" -device "virtio-blk-pci,drive=target,serial=${target_serial}" \
        -nic none "${install_creds[@]}" "$@"
    finish "${role}-2-install" "${VM_PID}" 'PROBE sysinstall=([^s]|s[^u])|PROBE esp-creds=' 1200 || fail "${role}: install timed out"
    grep -aq 'PROBE sysinstall=success' "${state}/${role}-2-install.ttyS1.log" \
        || fail "${role}: systemd-sysinstall did not succeed"
}

# boot_disk <role> <mac suffix> <mem>: the installed disk on the LAN.
boot_disk() {
    local creds
    mapfile -t creds < <(disk_creds "$1")
    read -r -a net <<<"$(nic "$2")"
    MEM="$3" vm "$1-3-disk" "$1" -drive "if=none,id=target,format=raw,file=${state}/$1-disk.raw" \
        -device "virtio-blk-pci,drive=target,serial=${target_serial}" "${net[@]}" "${creds[@]}"
}

echo "==> control plane: install from the \"Homelab: control plane\" entry, offline, with a TPM2"
mkdir -p "${state}/cp-tpm"
install cp
echo "==> control plane: first boot on the LAN"
boot_disk cp 41 "${DOGFOOD_CP_MEM:-6144}"
cp_pid="${VM_PID}"
pass=""
for _ in $(seq 400); do
    pass="$(grep -aoE 'PROBE cp-passphrase=[a-z-]+' "${state}/cp-3-disk.ttyS1" 2>/dev/null | head -n1 | cut -d= -f2)" || true
    [ -n "${pass}" ] && break
    kill -0 "${cp_pid}" 2>/dev/null || break
    sleep 5
done
[ -n "${pass}" ] || { finish cp-3-disk "${cp_pid}" '' 1 || true; fail "the control plane showed no join passphrase"; }
printf '%s' "${pass}" > "${state}/bluefin-cluster.passphrase"

echo "==> node: install from the \"Homelab: node\" entry, offline, with the passphrase"
install node -smbios "$(cred bluefin-cluster.passphrase "${state}/bluefin-cluster.passphrase")"
echo "==> node: first boot on the LAN"
boot_disk node 42 4096
node_pid="${VM_PID}"
rc=0
finish node-3-disk "${node_pid}" 'PROBE failed=' 3000 || rc=1
finish cp-3-disk "${cp_pid}" 'PROBE failed=' 4200 || rc=1

check() { grep -aqE "$2" "${state}/$1.ttyS1.log" || { echo "FAIL: $1: no match for: $2" >&2; rc=1; }; }
v="${ver//./\\.}"
# The stick seeds the kubeadm and homelab sysexts and the homelab add-ons;
# the control plane's template enables the add-ons, a node's only the two.
for role in cp node; do
    check "${role}-2-install" "PROBE sysinstall=success 0 homelab-install=success"
    check "${role}-2-install" "PROBE esp-seed=SHA256SUMS argo-workflows_${v}\.raw\.zst homelab_${v}\.raw\.zst kubeadm_${v}\.raw\.zst kubestellar_${v}\.raw\.zst mcp_${v}\.raw\.zst "
    check "${role}-3-disk" "PROBE os=bluefin-server ${v} secureboot=enabled"
    check "${role}-3-disk" 'PROBE root=xfs ignition=applied'
    check "${role}-3-disk" 'PROBE failed=0'
done
check cp-3-disk 'PROBE fetch=success argo-workflows-homelab-kubeadm-kubestellar-mcp-via-seed seed-left=0'
check cp-3-disk "PROBE merged=argo-workflows_${v} homelab_${v} kubeadm_${v} kubestellar_${v} mcp_${v} "
check node-3-disk 'PROBE fetch=success homelab-kubeadm-via-seed seed-left=0'
check node-3-disk "PROBE merged=homelab_${v} kubeadm_${v} "
check cp-2-install 'PROBE esp-creds=.*ignition\.config\.cred'
check node-2-install 'PROBE esp-creds=.*bluefin-cluster\.passphrase\.cred.*ignition\.config\.cred'
check cp-3-disk 'PROBE os=.* tpm=tpm0'
check cp-3-disk 'PROBE conf role=control-plane passphrase-lines=0'
check node-3-disk 'PROBE conf role=node passphrase-lines=0'
check cp-3-disk 'PROBE cp-init=active apply=active/success'
check cp-3-disk 'PROBE cp-nodes-ready=2 nodes=2'
check node-3-disk 'PROBE node-joined=yes kubelet=active'
check node-3-disk 'PROBE node-ready=True'
[ "${rc}" = 0 ] || fail "see above"
echo "PASS: offline Homelab installs from ${installer##*/}: control plane (TPM2-sealed template) applied the default homelab set; node installed with the passphrase joined; both Ready"
