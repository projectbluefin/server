#!/usr/bin/env bash
# QEMU check of a multi-node homelab: one control plane and one node that
# knows only the join passphrase, plus a node with a wrong passphrase.
#
# Network: one L2 segment, a switch on the host joining the three guests
# and a QEMU user-net (DHCP, DNS, internet), so all three get
# distinct DHCP leases on one link, exactly as the base 20-wired.network
# configures them; only the homelab sysext's drop-in turns mDNS on.
#
# Every guest boots diskless with the kubeadm and homelab sysexts from
# Ignition and a homelab.conf; nothing else is configured:
#   cp    HOMELAB_ROLE=control-plane, kubeadm-init.service; homelab set
#         reduced to Cilium (the CNI both nodes need) to save time
#   node  HOMELAB_ROLE=node + the passphrase: discovers the control plane
#         with DNS-SD over mDNS and joins with kubeadm
#   bad   HOMELAB_ROLE=node + a wrong passphrase: must be refused
# Passes when the control plane sees both itself and the node Ready, the
# node removed its passphrase, and the wrong passphrase got no token.
# Needs guest internet (registry.k8s.io, quay.io); DOGFOOD_DNS=<ip> adds a
# resolver (network.dns credential) when QEMU's DNS proxy cannot use the host's.
# Usage: dogfood-homelab-cluster.sh <dir with the release set>
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
dir="$(realpath "${1:?usage: $0 <dir>}")"
state="$(realpath -m "${DOGFOOD_STATE:-dist/dogfood-homelab-cluster}")"
base_port="${DOGFOOD_PORT:-8771}"
link_port="${DOGFOOD_LINK_PORT:-40170}"
pass="orbit-maple-candle-riverbank-sparrow"
wrong="orbit-maple-candle-riverbank-swallow"

rm -rf "${state}"
mkdir -p "${state}/serve"
names=()
for kind in kubeadm homelab; do
    files=("${dir}/${kind}"_*.raw.zst)
    f="${files[-1]}"
    [ -f "${f}" ] || { echo "ERROR: no ${kind}_<ver>.raw.zst in ${dir}" >&2; exit 1; }
    n="${f##*/}"; n="${n%.raw.zst}"
    zstd -dqf "${f}" -o "${state}/serve/${n}.raw"
    names+=("${n}")
done

# ignition <role> <homelab.conf text> <port>
ignition() {
    local conf entries="" n sum
    conf="$(printf '%s' "$2" | base64 -w0)"
    for n in "${names[@]}"; do
        sum="$(sha256sum "${state}/serve/${n}.raw" | cut -d' ' -f1)"
        entries+="{\"path\": \"/etc/extensions/${n}.raw\", \"mode\": 420, \"overwrite\": true,
          \"contents\": {\"source\": \"http://10.0.2.2:$3/${n}.raw\", \"verification\": {\"hash\": \"sha256-${sum}\"}}},"
    done
    local links=""
    if [ "$1" = cp ]; then
        links='"links": [{"path": "/etc/systemd/system/multi-user.target.wants/kubeadm-init.service",
          "target": "/usr/lib/systemd/system/kubeadm-init.service", "overwrite": true}],'
    fi
    cat <<EOF
{
  "ignition": {"version": "3.6.0"},
  "storage": {
    ${links}
    "files": [${entries}
      {"path": "/etc/bluefin/homelab.conf", "mode": 384, "overwrite": true,
       "contents": {"source": "data:;base64,${conf}"}}]
  }
}
EOF
}

cp_conf="HOMELAB_ROLE=control-plane
HOMELAB_JOIN_PASSPHRASE=${pass}
HOMELAB_CLUSTER_NAME=dogfood
HOMELAB_LOCAL_PATH_PROVISIONER=no
HOMELAB_METALLB=no
HOMELAB_ENVOY_GATEWAY=no
HOMELAB_CERT_MANAGER=no
HOMELAB_ARGOCD=no
HOMELAB_METRICS_SERVER=no
HOMELAB_RELOADER=no
HOMELAB_KURED=no
"

cat > "${state}/cp.probe" <<'EOF'
journalctl -f -n all -o cat -u 'bluefin-cluster-*' -u kubeadm-init.service | sed -u 's/^/PROBE-LOG live: /' &
export KUBECONFIG=/etc/kubernetes/admin.conf
for _ in $(seq 900); do
    case "$(systemctl show -P ActiveState kubeadm-init.service)" in active|failed) break ;; esac
    [ "$(systemctl show -P NRestarts kubeadm-init.service)" -ge 1 ] && break
    sleep 2
done
journalctl -b -o cat --no-pager -u kubeadm-init.service | grep -vE '^\[(certs|kubeconfig|etcd|control-plane)\] ' | tail -n 30 | sed 's/^/PROBE-LOG init: /'
journalctl -b -o cat --no-pager -u bluefin-cluster-prepare.service -u bluefin-cluster-mdns.service | sed 's/^/PROBE-LOG prepare: /'
resolvectl status 2>&1 | grep -iE 'link|mDNS|MulticastDNS' | sed 's/^/PROBE-LOG resolved: /'
host="$(hostname)"
echo "PROBE cp-init=$(systemctl show -P ActiveState kubeadm-init.service) hostname=${host} endpoint=$(sed -n 's/^controlPlaneEndpoint: //p' /etc/kubernetes/bluefin/init.yaml) server=$(sed -n 's/^ *server: //p' /etc/kubernetes/admin.conf)"
grep '^hosts:' /etc/nsswitch.conf | sed 's/^/PROBE-LOG nss: /'
resolvectl query "${host}.local" 2>&1 | sed 's/^/PROBE-LOG query-self: /'
# The image has sed and grep, not that other text tool.
first_addr() { resolvectl query -4 --legend=no "$1" 2>/dev/null | sed -n '1s/^[^ ]* \([0-9.]*\).*/\1/p'; }
pinned() { sed -n "s/^\([0-9a-f.:]*\) $1\$/\1/p" /etc/hosts; }
resolvectl query -4 --legend=no "${host}.local" 2>&1 | head -n 2 | sed 's/^/PROBE-LOG query4: /'
echo "PROBE cp-mdns=$(resolvectl mdns 2>/dev/null | grep -c ': yes') resolve-self=$(first_addr "${host}.local") pinned=$(pinned "${host}.local")"
for _ in $(seq 120); do [ -s /run/systemd/dnssd/bluefin-cluster.dnssd ] && break; sleep 5; done
cat /run/systemd/dnssd/bluefin-cluster.dnssd | sed 's/^/PROBE-LOG dnssd: /'
timeout 20 resolvectl service "${host}" _bluefin-cluster._tcp local 2>&1 | sed 's/^/PROBE-LOG service-self: /'
journalctl -b -o cat -u systemd-resolved.service | tail -n 8 | sed 's/^/PROBE-LOG resolved-log: /'
echo "PROBE cp-serve=$(systemctl is-active bluefin-cluster-serve.service) dnssd-txt=$(sed -n 's/^TxtText=//p' /run/systemd/dnssd/bluefin-cluster.dnssd | tr ' ' ',') dnssd-secret=$(grep -c -e orbit -e token /run/systemd/dnssd/bluefin-cluster.dnssd)"
echo "PROBE cp-passphrase-mode=$(stat -c %a /var/lib/bluefin-cluster/passphrase) issue-mode=$(stat -c %a /run/issue.d/50-bluefin-cluster.issue) cli=$(bluefin-cluster passphrase | tr -d '\n' | sha256sum | cut -c1-12)"
ready() { kubectl get nodes -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' 2>/dev/null | grep -c True; }
for i in $(seq 400); do
    [ "$(ready)" -ge 2 ] && break
    if [ $((i % 20)) = 0 ]; then
        kubectl get nodes --no-headers 2>&1 | sed 's/^/PROBE-LOG nodes: /'
        journalctl -b -o cat -u bluefin-homelab-apply.service | tail -n 3 | sed 's/^/PROBE-LOG apply: /'
        kubectl -n kube-system get pods -o wide --no-headers 2>&1 | grep -v Running | sed 's/^/PROBE-LOG pods: /'
        kubectl get node "${host}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}' 2>&1 | sed 's/^/PROBE-LOG ready: /'; echo
        kubectl -n kube-system get events --field-selector reason=Failed --no-headers 2>&1 | tail -n 3 | cut -c1-600 | sed 's/^/PROBE-LOG events: /'
        if [ "${i}" = 40 ]; then
            img="$(kubectl -n kube-system get ds cilium -o jsonpath='{.spec.template.spec.initContainers[0].image}')"
            timeout 120 crictl pull "${img}" 2>&1 | tail -n 3 | sed 's/^/PROBE-LOG crictl-pull: /'
            cat /etc/resolv.conf | sed 's/^/PROBE-LOG resolv: /'
            resolvectl query quay.io 2>&1 | head -n 4 | sed 's/^/PROBE-LOG quay: /'
        fi
    fi
    sleep 6
done
for _ in $(seq 120); do journalctl -b -o cat -u bluefin-cluster-serve.service | grep -q 'did not prove the passphrase' && break; sleep 5; done
kubectl get nodes -o wide --no-headers | sed 's/^/PROBE-LOG node: /'
echo "PROBE cp-nodes-ready=$(ready) nodes=$(kubectl get nodes --no-headers | wc -l)"
journalctl -b -o cat -u bluefin-cluster-serve.service | sed 's/^/PROBE-LOG serve: /' | tail -n 20
echo "PROBE cp-issued=$(journalctl -b -o cat -u bluefin-cluster-serve.service | grep -c 'issued a join token') denied=$(journalctl -b -o cat -u bluefin-cluster-serve.service | grep -c 'did not prove the passphrase') leaked=$(journalctl -b -o cat --no-pager | grep -c -e orbit-maple -e 'riverbank')"
echo "PROBE cp-tokens=$(kubectl -n kube-system get secrets --field-selector type=bootstrap.kubernetes.io/token -o jsonpath='{range .items[*]}{.data.description}{"\n"}{end}' | base64 -d 2>/dev/null | grep -c 'bluefin-cluster join')"
# Keep the API server up until the joined node has had time to report Ready.
sleep 600
EOF

cat > "${state}/node.probe" <<'EOF'
journalctl -f -n all -o cat -u 'bluefin-cluster-*' -u kubeadm-init.service | sed -u 's/^/PROBE-LOG live: /' &
(sleep 420; for i in $(ip -o link show up | sed -n 's/^\([0-9]*\): \([^:@]*\).*/\1 \2/p' | grep -v ' lo$' | cut -d' ' -f1); do
    timeout 15 varlinkctl call --more --timeout=12 /run/systemd/resolve/io.systemd.Resolve io.systemd.Resolve.BrowseServices \
        "{\"domain\":\"local\",\"type\":\"_bluefin-cluster._tcp\",\"ifindex\":${i},\"flags\":24}" 2>&1 | tr -d '\n' | sed "s/^/PROBE-LOG browse ${i}: /"; echo
done; resolvectl status 2>&1 | grep -E 'Link|Protocols' | sed 's/^/PROBE-LOG resolved: /') &
for _ in $(seq 600); do [ -e /var/lib/bluefin-cluster/joined ] && break; sleep 5; done
journalctl -b -o cat -u bluefin-cluster-join.service | sed 's/^/PROBE-LOG join: /' | tail -n 20
cp="$(cat /var/lib/bluefin-cluster/joined 2>/dev/null)"
echo "PROBE node-joined=$([ -e /var/lib/bluefin-cluster/joined ] && echo yes || echo no) hostname=$(hostname) kubelet=$(systemctl is-active kubelet.service) enabled=$(systemctl is-enabled containerd.service kubelet.service | tr '\n' ',')"
echo "PROBE node-passphrase-left=$(grep -c HOMELAB_JOIN_PASSPHRASE /etc/bluefin/homelab.conf) server=$(sed -n 's/^ *server: //p' /etc/kubernetes/kubelet.conf)"
cpname="$(sed -n 's|^ *server: https://\([^:]*\):.*|\1|p' /etc/kubernetes/kubelet.conf)"
first_addr() { resolvectl query -4 --legend=no "$1" 2>/dev/null | sed -n '1s/^[^ ]* \([0-9.]*\).*/\1/p'; }
pinned() { sed -n "s/^\([0-9a-f.:]*\) $1\$/\1/p" /etc/hosts; }
echo "PROBE node-resolves-cp=$(first_addr "${cpname}") pinned=$(pinned "${cpname}") cluster=${cp}"
for _ in $(seq 120); do [ "$(systemctl show -P NRestarts kubelet.service)" -ge 0 ] && crictl ps 2>/dev/null | grep -q cilium-agent && break; sleep 5; done
echo "PROBE node-cilium=$(crictl ps 2>/dev/null | grep -c cilium-agent)"
systemctl restart bluefin-cluster-join.service
echo "PROBE node-rerun=$(systemctl show -P ConditionResult bluefin-cluster-join.service)"
# Stay up while the control plane checks that this node is Ready.
k() { kubectl --request-timeout=10s --kubeconfig /etc/kubernetes/kubelet.conf "$@"; }
for _ in $(seq 180); do
    [ "$(k get node "$(hostname)" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)" = True ] && break
    sleep 5
done
echo "PROBE node-ready=$(k get node "$(hostname)" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
sleep 240
EOF

cat > "${state}/bad.probe" <<'EOF'
journalctl -f -n all -o cat -u 'bluefin-cluster-*' -u kubeadm-init.service | sed -u 's/^/PROBE-LOG live: /' &
(sleep 420; for i in $(ip -o link show up | sed -n 's/^\([0-9]*\): \([^:@]*\).*/\1 \2/p' | grep -v ' lo$' | cut -d' ' -f1); do
    timeout 15 varlinkctl call --more --timeout=12 /run/systemd/resolve/io.systemd.Resolve io.systemd.Resolve.BrowseServices \
        "{\"domain\":\"local\",\"type\":\"_bluefin-cluster._tcp\",\"ifindex\":${i},\"flags\":24}" 2>&1 | tr -d '\n' | sed "s/^/PROBE-LOG browse ${i}: /"; echo
done; resolvectl status 2>&1 | grep -E 'Link|Protocols' | sed 's/^/PROBE-LOG resolved: /') &
for _ in $(seq 240); do
    [ "$(journalctl -b -o cat -u bluefin-cluster-join.service | grep -c 'could not prove the passphrase')" -ge 2 ] && break
    sleep 5
done
journalctl -b -o cat -u bluefin-cluster-join.service | sed 's/^/PROBE-LOG bad: /' | tail -n 6
echo "PROBE bad-refused=$(journalctl -b -o cat -u bluefin-cluster-join.service | grep -c 'could not prove the passphrase') joined=$([ -e /var/lib/bluefin-cluster/joined ] && echo yes || echo no) kubelet-conf=$([ -e /etc/kubernetes/kubelet.conf ] && echo yes || echo no) passphrase-kept=$(grep -c HOMELAB_JOIN_PASSPHRASE /etc/bluefin/homelab.conf)"
EOF

# One L2 segment for the three guests (scripts/dogfood-lan.sh).
# shellcheck source=scripts/dogfood-lan.sh
. "${here}/dogfood-lan.sh"
lan_start "${state}" "${link_port}"
trap lan_stop EXIT
cp_net="$(nic 01)"
node_net="$(nic 02)"
bad_net="$(nic 03)"

# boot <role> <port> <mem> <timeout> <net> <conf>
boot() {
    local role=$1 port=$2
    mkdir -p "${state}/${role}-set"
    for f in "${dir}"/*; do ln -sf "${f}" "${state}/${role}-set/"; done
    ignition "${role}" "$6" "${port}" > "${state}/${role}.ign"
    # Copy what the units under test log to the serial console.
    mkdir -p "${state}/${role}-creds"
    if [ -n "${DOGFOOD_DNS:-}" ]; then printf '%s\n' "${DOGFOOD_DNS}" > "${state}/${role}-creds/network.dns"; fi
    for u in kubeadm-init.service bluefin-cluster-prepare.service bluefin-cluster-serve.service bluefin-cluster-join.service; do
        printf '[Service]\nStandardOutput=journal+console\nStandardError=journal+console\n' \
            > "${state}/${role}-creds/systemd.unit-dropin.${u}"
    done
    DOGFOOD_PORT="${port}" DOGFOOD_MEM="$3" DOGFOOD_TIMEOUT="$4" DOGFOOD_NET="$5" \
    DOGFOOD_IGNITION="${state}/${role}.ign" DOGFOOD_SERVE_EXTRA="${state}/serve" \
    DOGFOOD_EXTRA_PROBE="${state}/${role}.probe" DOGFOOD_CREDS="${state}/${role}-creds" \
        bash "${here}/dogfood-diskless.sh" "${state}/${role}-set" --check > "${state}/${role}.log" 2>&1
}

echo "==> control plane, node and wrong-passphrase node on one L2 segment (logs: ${state}/{cp,node,bad}.log)"
boot cp "${base_port}" "${DOGFOOD_CP_MEM:-6144}" 4200 "${cp_net}" "${cp_conf}" & cp_pid=$!
sleep "${DOGFOOD_NODE_DELAY:-10}"
boot node "$((base_port + 1))" "${DOGFOOD_NODE_MEM:-4096}" 3300 "${node_net}" \
    "$(printf 'HOMELAB_ROLE=node\nHOMELAB_JOIN_PASSPHRASE=%s\n' "${pass}")" & node_pid=$!
boot bad "$((base_port + 2))" 4096 1800 "${bad_net}" \
    "$(printf 'HOMELAB_ROLE=node\nHOMELAB_JOIN_PASSPHRASE=%s\n' "${wrong}")" & bad_pid=$!
rc=0
wait "${bad_pid}" || rc=1
wait "${node_pid}" || rc=1
wait "${cp_pid}" || rc=1
for role in cp node bad; do grep -aoE 'PROBE[ -].*' "${state}/${role}.log" | sed "s/^/${role}: /" || true; done

check() { grep -aqE "$2" "${state}/$1.log" || { echo "FAIL: $1: no match for: $2" >&2; rc=1; }; }
check cp 'PROBE cp-init=active hostname=bluefin-[0-9a-f]{8} endpoint=bluefin-[0-9a-f]{8}\.local:6443 server=https://bluefin-[0-9a-f]{8}\.local:6443'
check cp 'PROBE cp-mdns=[1-9] resolve-self=10\.0\.2\.[0-9]+ pinned=10\.0\.2\.[0-9]+'
check cp 'PROBE cp-serve=active dnssd-txt=v=1,cluster=dogfood,runtime=kubeadm dnssd-secret=0'
check cp 'PROBE cp-passphrase-mode=600 issue-mode=600 '
check cp 'PROBE cp-nodes-ready=2 nodes=2'
check cp 'PROBE cp-issued=1 denied=[1-9][0-9]* leaked=0'
check cp 'PROBE cp-tokens=1'
check node 'PROBE node-joined=yes hostname=bluefin-[0-9a-f]{8} kubelet=active enabled=enabled,enabled,'
check node 'PROBE node-passphrase-left=0 server=https://bluefin-[0-9a-f]{8}\.local:6443'
check node 'PROBE node-resolves-cp=10\.0\.2\.[0-9]+ pinned=10\.0\.2\.[0-9]+ cluster=dogfood'
check node 'PROBE node-cilium=1'
check node 'PROBE node-ready=True'
check node 'PROBE node-rerun=no'
check bad 'PROBE bad-refused=[2-9][0-9]* joined=no kubelet-conf=no passphrase-kept=1'
for role in cp node bad; do check "${role}" 'PROBE failed=0'; done
[ "${rc}" = 0 ] || exit 1
echo "PASS: node discovered the control plane over mDNS and joined with only the passphrase; both nodes Ready; wrong passphrase refused, no token issued to it"
