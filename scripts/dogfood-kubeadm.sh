#!/usr/bin/env bash
# QEMU check of the kubeadm sysext's single-node control plane, on a diskless
# boot configured the way a node would be, through Ignition only:
#   - Ignition writes kubeadm_<ver>.raw to /etc/extensions (sha256-verified)
#     and links kubeadm-init.service into multi-user.target.wants. A link,
#     not `enabled: true`: the unit only exists once systemd-sysext has
#     merged the image, after PID 1 applied the boot's presets.
#   - the probe waits for kubeadm init, applies Cilium as the CNI and
#     kube-proxy replacement (rendered here from a pinned chart; test-only,
#     the sysext ships no CNI), then asserts the node is Ready and
#     untainted, kube-proxy is absent, every kube-system pod Runs with
#     CoreDNS Ready, root's kubectl works, and a second start of
#     kubeadm-init.service is skipped by its admin.conf condition.
# Needs helm and curl on the host and internet access from the guest
# (registry.k8s.io, quay.io): the control-plane and Cilium images are pulled.
# DOGFOOD_DNS=<ip> adds a resolver for the guest (systemd-resolved's
# network.dns credential) when QEMU's DNS proxy cannot use the host's.
# Usage: dogfood-kubeadm.sh <dir with the release set>
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
dir="$(realpath "${1:?usage: $0 <dir>}")"
sysexts=("${dir}"/kubeadm_*.raw.zst)
sysext="${sysexts[-1]}"
[ -f "${sysext}" ] || { echo "ERROR: no kubeadm_<ver>.raw.zst in ${dir}" >&2; exit 1; }
name="${sysext##*/}"; name="${name%.raw.zst}"
state="$(realpath -m "${DOGFOOD_STATE:-dist/dogfood-kubeadm}")"
export DOGFOOD_PORT="${DOGFOOD_PORT:-8765}"
cilium_version=1.20.2
cilium_sha256=b2afd87b7f75f875f92a14559f14f59b7babbb479d968e3fd625a20bf30ec20e

command -v helm >/dev/null || { echo "ERROR: helm is required to render Cilium" >&2; exit 1; }
mkdir -p "${state}/serve"
zstd -dqf "${sysext}" -o "${state}/serve/${name}.raw"
sum="$(sha256sum "${state}/serve/${name}.raw" | cut -d' ' -f1)"

chart="${state}/cilium-${cilium_version}.tgz"
[ -f "${chart}" ] || curl -fsSL -o "${chart}" "https://helm.cilium.io/cilium-${cilium_version}.tgz"
echo "${cilium_sha256}  ${chart}" | sha256sum -c --quiet -
# K8S_SERVICE_HOST: the probe substitutes the node's address. Without
# kube-proxy, Cilium cannot reach the API through the service VIP.
helm template cilium "${chart}" --namespace kube-system \
    --set kubeProxyReplacement=true --set k8sServiceHost=K8S_SERVICE_HOST --set k8sServicePort=6443 \
    --set routingMode=tunnel --set tunnelProtocol=vxlan --set ipam.mode=kubernetes \
    --set operator.replicas=1 --set hubble.enabled=false > "${state}/serve/cilium.yaml"

cat > "${state}/kubeadm.ign" <<EOF
{
  "ignition": {"version": "3.6.0"},
  "storage": {
    "files": [{
      "path": "/etc/extensions/${name}.raw",
      "mode": 420,
      "overwrite": true,
      "contents": {
        "source": "http://10.0.2.2:${DOGFOOD_PORT}/${name}.raw",
        "verification": {"hash": "sha256-${sum}"}
      }
    }],
    "links": [{
      "path": "/etc/systemd/system/multi-user.target.wants/kubeadm-init.service",
      "target": "/usr/lib/systemd/system/kubeadm-init.service",
      "overwrite": true
    }]
  }
}
EOF

cat > "${state}/kubeadm.probe" <<EOF
export KUBECONFIG=/etc/kubernetes/admin.conf
for _ in \$(seq 750); do
    case "\$(systemctl show -P ActiveState kubeadm-init.service)" in active|failed) break ;; esac
    [ "\$(systemctl show -P NRestarts kubeadm-init.service)" -ge 2 ] && break
    sleep 2
done
echo "PROBE kubeadm-init=\$(systemctl show -P ActiveState kubeadm-init.service) result=\$(systemctl show -P Result kubeadm-init.service) restarts=\$(systemctl show -P NRestarts kubeadm-init.service)"
journalctl -b -o cat --no-pager -u kubeadm-init.service | grep -vE '^\[(certs|kubeconfig|etcd|control-plane)\] ' | tail -n 40 | sed 's/^/PROBE-LOG init: /'
crictl ps -a 2>&1 | sed 's/^/PROBE-LOG crictl: /'
echo "PROBE init-config=\$([ "\$(sha256sum < /etc/kubernetes/bluefin/init.yaml)" = "\$(sha256sum < /usr/share/bluefin/kubeadm/init.yaml)" ] && echo seeded || echo differs) kubeconfig=\$(readlink /root/.kube/config) enabled=\$(systemctl is-enabled containerd.service kubelet.service | tr '\n' ',')"
ip="\$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')"
curl -fsS "http://10.0.2.2:${DOGFOOD_PORT}/cilium.yaml" | sed "s/K8S_SERVICE_HOST/\${ip}/g" \
    | kubectl apply --server-side -f - > /run/cilium-apply.log 2>&1
echo "PROBE cilium-apply=\$? host=\${ip}"
kubectl wait --for=condition=Ready nodes --all --timeout=15m > /dev/null
kubectl -n kube-system wait --for=condition=Ready pods -l k8s-app=kube-dns --timeout=10m > /dev/null
kubectl -n kube-system wait --for=condition=Ready pods --all --timeout=10m > /dev/null
echo "PROBE node=\$(kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name} Ready={.status.conditions[?(@.type=="Ready")].status} {.status.nodeInfo.kubeletVersion}{end}')"
taints="\$(kubectl get nodes -o jsonpath='{.items[*].spec.taints[*].key}')"
echo "PROBE taints=\${taints:-none} kube-proxy=\$(kubectl -n kube-system get daemonset kube-proxy > /dev/null 2>&1 && echo present || echo absent) recorded=\$(kubectl -n kube-system get configmap kubeadm-config -o jsonpath='{.data.ClusterConfiguration}' | grep -A1 '^proxy:' | tr -d ' \n')"
echo "PROBE coredns=\$(kubectl -n kube-system get pods -l k8s-app=kube-dns -o jsonpath='{range .items[*]}{.status.phase}/{.status.containerStatuses[0].ready} {end}')"
echo "PROBE kube-system-not-running=\$(kubectl -n kube-system get pods --field-selector=status.phase!=Running --no-headers 2>/dev/null | wc -l) root-kubectl=\$(env -u KUBECONFIG HOME=/root kubectl get nodes --no-headers 2>/dev/null | wc -l)"
kubectl -n kube-system get pods --no-headers | sed 's/^/PROBE-LOG /'
systemctl restart kubeadm-init.service
echo "PROBE rerun=\$(systemctl show -P ConditionResult kubeadm-init.service) \$(systemctl show -P ActiveState kubeadm-init.service)"
EOF

echo "==> diskless boot of ${dir##*/} with ${name} and kubeadm-init.service from Ignition"
if [ -n "${DOGFOOD_DNS:-}" ]; then
    mkdir -p "${state}/creds"
    printf '%s\n' "${DOGFOOD_DNS}" > "${state}/creds/network.dns"
    export DOGFOOD_CREDS="${state}/creds"
fi
log="${state}/kubeadm.log"
DOGFOOD_IGNITION="${state}/kubeadm.ign" DOGFOOD_SERVE_EXTRA="${state}/serve" \
DOGFOOD_EXTRA_PROBE="${state}/kubeadm.probe" DOGFOOD_MEM="${DOGFOOD_MEM:-8192}" \
DOGFOOD_TIMEOUT="${DOGFOOD_TIMEOUT:-2400}" \
    bash "${here}/dogfood-diskless.sh" "${dir}" --check | tee "${log}"
# Report every expectation that does not hold, not only the first.
rc=0
check() { grep -q "$@" "${log}" || { echo "FAIL: no match in ${log}: ${*: -1}" >&2; rc=1; }; }
check "PROBE kubeadm-init=active result=success "
check "PROBE init-config=seeded kubeconfig=/etc/kubernetes/admin.conf enabled=enabled,enabled,"
check "PROBE cilium-apply=0 "
check -E "PROBE node=[^ ]+ Ready=True v"
check "PROBE taints=none kube-proxy=absent recorded=proxy:disabled:true"
check -x "PROBE coredns=Running/true Running/true "
check "PROBE kube-system-not-running=0 root-kubectl=1"
check "PROBE rerun=no inactive"
check "PROBE failed=0"
[ "${rc}" = 0 ] || exit 1
echo "PASS: kubeadm-init.service brought up a single-node control plane from Ignition; node Ready and untainted, no kube-proxy, kube-system Running with CoreDNS Ready, rerun skipped"
