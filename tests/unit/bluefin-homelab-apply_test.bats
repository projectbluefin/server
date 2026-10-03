#!/usr/bin/env bats
#
# Unit tests for files/homelab/sysext/bluefin-homelab-apply.
#
# The applier runs against a fake host root (HOMELAB_ROOT) with stub kubectl,
# k0s and systemctl on PATH. The kubectl stub logs every call, keeps a copy of
# each file it is asked to apply (in apply order) and answers the readiness
# queries; most tests use the real vendored manifests.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    SCRIPT="${REPO_ROOT}/files/homelab/sysext/bluefin-homelab-apply"
    STUBS="${BATS_TEST_TMPDIR}/bin"
    FAKE_ROOT="${BATS_TEST_TMPDIR}/root"
    LOG="${BATS_TEST_TMPDIR}/kubectl.log"
    APPLIED="${BATS_TEST_TMPDIR}/applied"
    mkdir -p "${STUBS}" "${FAKE_ROOT}" "${APPLIED}"
    # Only the tools the applier uses, never the host's own kubectl or k0s
    # (CI runners ship a real kubectl in /usr/local/bin).
    TOOLS="${BATS_TEST_TMPDIR}/tools"
    mkdir -p "${TOOLS}"
    for t in awk base64 basename bash cat chmod cp env grep head id ln mkdir mktemp mv od printf rm sed sha1sum sleep sort tail timeout touch tr; do
        p=$(command -v "$t") && ln -sf "$p" "${TOOLS}/$t"
    done
    : >"${LOG}"

    cat >"${STUBS}/kubectl" <<EOF
#!/usr/bin/env bash
echo "kubectl \$*" >>"${LOG}"
args=" \$* "
last=\${@: -1}
case \${args} in
*" get --raw /readyz "*) exit \${READYZ_RC:-0} ;;
*" apply "*" -f - "*) cat >>"${APPLIED}/stdin.yaml"; exit 0 ;;
*" apply "*)
    n=\$(ls "${APPLIED}" | wc -l)
    cp "\${last}" "${APPLIED}/\$(printf %03d "\${n}")-\$(basename "\${last}")"
    exit \${APPLY_RC:-0} ;;
*" wait "*)
    c=\$(cat "${BATS_TEST_TMPDIR}/waits" 2>/dev/null || echo 0)
    echo \$((c + 1)) >"${BATS_TEST_TMPDIR}/waits"
    [ "\${c}" -ge "\${WAIT_FAILS:-0}" ]; exit \$? ;;
*" get secret "*"jsonpath={.data.password}"*) printf %s "\${LOGIN_PASSWORD:-}" | base64; exit 0 ;;
*" get secret "*) exit \${SECRET_RC:-1} ;;
*" create secret "*) printf 'kind: Secret\n' ; exit 0 ;;
*" get -f "*)
    f=\$(sed -n 's/.* -f \([^ ]*\) .*/\1/p' <<<"\${args}")
    if grep -q '^kind: Deployment' "\${f}"; then echo "Deployment demo web"; fi
    exit 0 ;;
*" rollout status "*) exit \${ROLLOUT_RC:-0} ;;
esac
exit 0
EOF
    cat >"${STUBS}/systemctl" <<EOF
#!/usr/bin/env bash
echo "systemctl \$*" >>"${LOG}"
case " \$* " in *" is-enabled "*) [ -n "\${ENABLED_UNIT:-}" ] && [[ " \$* " == *" \${ENABLED_UNIT} "* ]] ;; esac
EOF
    chmod +x "${STUBS}/kubectl" "${STUBS}/systemctl"
}

kubeadm_node() {
    mkdir -p "${FAKE_ROOT}/etc/kubernetes"
    printf 'apiVersion: v1\nclusters:\n- cluster:\n    server: https://192.0.2.10:6443\n  name: kubernetes\n' \
        >"${FAKE_ROOT}/etc/kubernetes/admin.conf"
}

k0s_node() {
    mkdir -p "${FAKE_ROOT}/var/lib/k0s/pki"
    printf 'clusters:\n- cluster:\n    server: https://localhost:6443\n' >"${FAKE_ROOT}/var/lib/k0s/pki/admin.conf"
}

run_applier() {
    run env -i PATH="${STUBS}:${TOOLS}" HOMELAB_ROOT="${FAKE_ROOT}" \
        HOMELAB_MANIFESTS="${MANIFESTS:-${REPO_ROOT}/files/homelab/manifests}" \
        HOMELAB_ADDONS="${ADDONS:-${BATS_TEST_TMPDIR}/no-addons}" \
        HOMELAB_API_TIMEOUT=1 HOMELAB_WAIT_TIMEOUT=1 HOMELAB_POLL_INTERVAL=0 "$@" \
        bash "${SCRIPT}"
}

# Component directories in the order their first file was applied.
applied_components() {
    grep -o '^<5>[a-z0-9-]*: applying$' <<<"${output}" | sed 's/^<5>//; s/: applying$//' | paste -sd' '
}

@test "a node without a control plane has nothing to apply" {
    run_applier
    [ "$status" -eq 0 ]
    [[ "$output" == *"no control plane on this node"* ]]
    ! grep -q '^kubectl' "${LOG}"
}

@test "a control plane that never writes its kubeconfig fails the run" {
    mkdir -p "${FAKE_ROOT}/etc/kubernetes/bluefin"
    : >"${FAKE_ROOT}/etc/kubernetes/bluefin/init.yaml"
    run_applier
    [ "$status" -eq 1 ]
    [[ "$output" == *"no admin kubeconfig after 1s"* ]]
}

@test "k0scontroller.service being enabled means a kubeconfig is coming" {
    run_applier ENABLED_UNIT=k0scontroller.service
    [ "$status" -eq 1 ]
    [[ "$output" == *"no admin kubeconfig"* ]]
}

@test "an API server that never gets ready fails the run" {
    kubeadm_node
    run_applier READYZ_RC=1
    [ "$status" -eq 1 ]
    [[ "$output" == *"API server not ready"* ]]
}

@test "kubeadm: the default set applies in index order, Cilium first" {
    kubeadm_node
    run_applier
    [ "$status" -eq 0 ]
    [[ "$output" == *"runtime kubeadm, kubeconfig ${FAKE_ROOT}/etc/kubernetes/admin.conf"* ]]
    [ "$(applied_components)" = "cilium local-path-provisioner metallb envoy-gateway cert-manager argocd metrics-server reloader kured" ]
    [[ "$output" == *"nfs: disabled (HOMELAB_NFS)"* ]]
    [[ "$output" == *"kube-prometheus-stack: disabled (HOMELAB_KUBE_PROMETHEUS_STACK)"* ]]
    [[ "$output" == *"gpu-operator: disabled (HOMELAB_GPU_OPERATOR)"* ]]
    grep -q -- '--kubeconfig .*/etc/kubernetes/admin.conf apply --server-side --force-conflicts --field-manager=bluefin-homelab' "${LOG}"
    ! grep -qw delete "${LOG}"
}

@test "kubeadm: Cilium gets the API server address from the kubeconfig" {
    kubeadm_node
    run_applier
    cilium=$(ls "${APPLIED}"/*-10-cilium.yaml)
    grep -q 'value: "192.0.2.10"' "${cilium}"
    grep -q 'value: "6443"' "${cilium}"
    ! grep -q 'HOMELAB_' "${cilium}"
}

@test "HOMELAB_ROLE=node: the control plane applies, never a node" {
    kubeadm_node
    run_applier HOMELAB_ROLE=node
    [ "$status" -eq 0 ]
    [[ "$output" == *"HOMELAB_ROLE=node"* ]]
    ! grep -q '^kubectl' "${LOG}"
}

@test "multi-node: Cilium gets the address of the control plane's mDNS name" {
    kubeadm_node
    sed -i 's|https://192.0.2.10:6443|https://cp1.local:6443|' "${FAKE_ROOT}/etc/kubernetes/admin.conf"
    cat >"${STUBS}/resolvectl" <<'EOF'
#!/usr/bin/env bash
[ "$*" = "query -4 --legend=no cp1.local" ] && printf 'cp1.local: 192.0.2.20                        -- link: enp0s2\n'
EOF
    chmod +x "${STUBS}/resolvectl"
    run_applier HOMELAB_ROLE=control-plane
    [ "$status" -eq 0 ]
    cilium=$(ls "${APPLIED}"/*-10-cilium.yaml)
    grep -q 'value: "192.0.2.20"' "${cilium}"
    ! grep -q 'cp1.local' "${cilium}"
}

@test "k0s: no Cilium, no metrics-server, and k0s kubectl without kubectl" {
    k0s_node
    mv "${STUBS}/kubectl" "${BATS_TEST_TMPDIR}/kubectl-real"
    printf '#!/usr/bin/env bash\n[ "$1" = kubectl ] || exit 64\nshift\nexec %s "$@"\n' "${BATS_TEST_TMPDIR}/kubectl-real" >"${STUBS}/k0s"
    chmod +x "${STUBS}/k0s"
    run_applier
    [ "$status" -eq 0 ]
    [[ "$output" == *"runtime k0s"* ]]
    [[ "$output" == *"cilium: not used with k0s"* ]]
    [[ "$output" == *"metrics-server: not used with k0s"* ]]
    [ "$(applied_components)" = "local-path-provisioner metallb envoy-gateway cert-manager argocd reloader kured" ]
    grep -q -- "--kubeconfig ${FAKE_ROOT}/var/lib/k0s/pki/admin.conf" "${LOG}"
}

@test "k0s: Argo CD is left to the kubestellar sysext when it seeded it" {
    k0s_node
    mkdir -p "${FAKE_ROOT}/var/lib/k0s/manifests/argocd"
    run_applier
    [ "$status" -eq 0 ]
    [[ "$output" == *"argocd: managed by the kubestellar sysext"* ]]
    [[ "$(applied_components)" != *argocd* ]]
}

@test "homelab.conf switches components on and off" {
    kubeadm_node
    run_applier HOMELAB_GPU_OPERATOR=yes HOMELAB_KUBE_PROMETHEUS_STACK=yes HOMELAB_LOKI=no HOMELAB_ALLOY=off HOMELAB_KURED=maybe
    [ "$status" -eq 0 ]
    [ "$(applied_components)" = "cilium local-path-provisioner metallb envoy-gateway cert-manager argocd metrics-server reloader kured kube-prometheus-stack gpu-operator" ]
    [[ "$output" == *"ignoring HOMELAB_KURED=maybe: expected yes or no"* ]]
    [[ "$output" == *"loki: disabled (HOMELAB_LOKI)"* ]]
}

@test "the MetalLB pool is skipped until addresses are configured" {
    kubeadm_node
    run_applier
    [[ "$output" == *"metallb: skipping 20-pool.yaml: HOMELAB_METALLB_ADDRESSES not set"* ]]
    ! ls "${APPLIED}"/*-20-pool.yaml
    [[ "$output" == *"cert-manager: skipping 21-acme-issuer.yaml: HOMELAB_ACME_EMAIL not set"* ]]
    [[ "$output" == *"argocd: skipping 20-root-app.yaml: HOMELAB_ARGOCD_ROOT_REPO not set"* ]]
}

@test "configured inputs are validated and substituted" {
    kubeadm_node
    run_applier HOMELAB_METALLB_ADDRESSES="192.0.2.240-192.0.2.250, 198.51.100.0/28" \
        HOMELAB_ACME_EMAIL='bad"email' HOMELAB_ARGOCD_ROOT_REPO=https://example.com/me/homelab.git
    [ "$status" -eq 0 ]
    grep -q 'addresses: \["192.0.2.240-192.0.2.250", "198.51.100.0/28"\]' "${APPLIED}"/*-20-pool.yaml
    [[ "$output" == *'ignoring HOMELAB_ACME_EMAIL=bad"email'* ]]
    ! ls "${APPLIED}"/*-21-acme-issuer.yaml
    grep -q 'repoURL: "https://example.com/me/homelab.git"' "${APPLIED}"/*-20-root-app.yaml
    grep -q 'targetRevision: "HEAD"' "${APPLIED}"/*-20-root-app.yaml
    grep -q -- '--time-zone=UTC"' "${APPLIED}"/*-10-kured.yaml
}

@test "Grafana's admin Secret is generated once, never rotated, never logged" {
    kubeadm_node
    run_applier HOMELAB_KUBE_PROMETHEUS_STACK=yes
    line=$(grep 'create secret generic grafana-admin' "${LOG}")
    [[ "${line}" == *"--from-literal=admin-user=admin"* ]]
    [[ "${line}" =~ --from-literal=admin-password=[0-9a-f]{48} ]]
    password=$(sed 's/.*admin-password=\([0-9a-f]*\).*/\1/' <<<"${line}")
    [[ "$output" != *"${password}"* ]]
    : >"${LOG}"
    run_applier SECRET_RC=0 HOMELAB_KUBE_PROMETHEUS_STACK=yes
    ! grep -q 'create secret generic grafana-admin' "${LOG}"
}

@test "democratic-csi is skipped until its driver config exists, then applied every run" {
    kubeadm_node
    run_applier HOMELAB_DEMOCRATIC_CSI=yes
    [ "$status" -eq 0 ]
    [[ "$output" == *"democratic-csi: skipped, missing /etc/bluefin/homelab.d/democratic-csi/driver-config-file.yaml"* ]]
    ! ls "${APPLIED}"/*-10-democratic-csi.yaml
    mkdir -p "${FAKE_ROOT}/etc/bluefin/homelab.d/democratic-csi"
    echo 'driver: zfs-generic-iscsi' >"${FAKE_ROOT}/etc/bluefin/homelab.d/democratic-csi/driver-config-file.yaml"
    run_applier HOMELAB_DEMOCRATIC_CSI=yes SECRET_RC=0
    grep -q -- "create secret generic democratic-csi-driver-config --from-file=driver-config-file.yaml=${FAKE_ROOT}/etc/bluefin/homelab.d/democratic-csi/driver-config-file.yaml" "${LOG}"
    ls "${APPLIED}"/*-10-democratic-csi.yaml
}

@test "within a component: CRDs, namespace, Secrets, workloads, then config" {
    MANIFESTS="${BATS_TEST_TMPDIR}/manifests"
    mkdir -p "${MANIFESTS}/10-demo"
    echo '10-demo on kubeadm,k0s' >"${MANIFESTS}/components"
    printf 'apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\nmetadata:\n  name: x\n' >"${MANIFESTS}/10-demo/00-crds.yaml"
    printf 'apiVersion: v1\nkind: Namespace\nmetadata:\n  name: demo\n' >"${MANIFESTS}/10-demo/01-namespace.yaml"
    printf 'apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\n' >"${MANIFESTS}/10-demo/10-demo.yaml"
    printf 'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: c\n' >"${MANIFESTS}/10-demo/20-config.yaml"
    echo 'demo s key=@random' >"${MANIFESTS}/10-demo/secrets"
    kubeadm_node
    run_applier
    [ "$status" -eq 0 ]
    sequence=$(grep -oE 'wait --for=condition=Established|apply .* -f [^ ]*/[0-9]+-[a-z-]+\.yaml|create secret generic s|rollout status deployment/web' "${LOG}" |
        sed -E 's#apply .* -f [^ ]*/##' | paste -sd' ')
    [ "${sequence}" = "00-crds.yaml wait --for=condition=Established 01-namespace.yaml create secret generic s 10-demo.yaml rollout status deployment/web 20-config.yaml" ]
}

@test "a CRD wait that fails before the API server fills in its status is retried" {
    MANIFESTS="${BATS_TEST_TMPDIR}/manifests"
    mkdir -p "${MANIFESTS}/10-demo"
    echo '10-demo on kubeadm,k0s' >"${MANIFESTS}/components"
    printf 'apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\nmetadata:\n  name: x\n' >"${MANIFESTS}/10-demo/00-crds.yaml"
    kubeadm_node
    run_applier HOMELAB_WAIT_TIMEOUT=30 WAIT_FAILS=2
    [ "$status" -eq 0 ]
    [ "$(grep -c 'wait --for=condition=Established' "${LOG}")" -eq 3 ]
}

@test "CRDs that never become Established fail the run" {
    MANIFESTS="${BATS_TEST_TMPDIR}/manifests"
    mkdir -p "${MANIFESTS}/10-demo"
    echo '10-demo on kubeadm,k0s' >"${MANIFESTS}/components"
    printf 'apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\nmetadata:\n  name: x\n' >"${MANIFESTS}/10-demo/00-crds.yaml"
    kubeadm_node
    run_applier WAIT_FAILS=1000000
    [ "$status" -ne 0 ]
    [[ "${output}" == *"CRDs in 00-crds.yaml not Established"* ]]
}

@test "a component that does not roll out fails the run, later ones still apply" {
    kubeadm_node
    run_applier ROLLOUT_RC=1
    [ "$status" -eq 1 ]
    [[ "$output" == *"did not roll out"* ]]
    [[ "$output" == *"<3>failed: "* ]]
    [[ "$(applied_components)" == *"kured"* ]]
}

@test "a second run applies the same files again (idempotent, no deletes)" {
    kubeadm_node
    run_applier
    first=$(ls "${APPLIED}" | grep -v stdin.yaml | sed 's/^[0-9]*-//' | paste -sd' ')
    rm -f "${APPLIED}"/*
    run_applier SECRET_RC=0
    second=$(ls "${APPLIED}" | grep -v stdin.yaml | sed 's/^[0-9]*-//' | paste -sd' ')
    [ "${first}" = "${second}" ]
    ! grep -qw delete "${LOG}"
}

# Add-ons: the add-on sysexts' directories, merged into addons.d.
with_addons() {
    ADDONS="${REPO_ROOT}/files/homelab/addons"
}

@test "add-ons apply after the base set, in name order, with their defaults" {
    kubeadm_node
    with_addons
    run_applier
    [ "$status" -eq 0 ]
    [ "$(applied_components)" = "cilium local-path-provisioner metallb envoy-gateway cert-manager argocd metrics-server reloader kured argo-workflows mcp kubestellar-console" ]
    [[ "$output" == *"kubestellar-full: disabled (HOMELAB_KUBESTELLAR_FULL)"* ]]
    grep -q 'argo-server' "${APPLIED}"/*-10-argo-workflows.yaml
}

@test "add-ons follow HOMELAB_<ID> and their runtimes" {
    k0s_node
    with_addons
    run_applier HOMELAB_ARGO_WORKFLOWS=no HOMELAB_KUBESTELLAR_FULL=yes
    [ "$status" -eq 0 ]
    [[ "$output" == *"argo-workflows: disabled (HOMELAB_ARGO_WORKFLOWS)"* ]]
    [[ "$(applied_components)" == *"mcp kubestellar-console kubestellar-full" ]]
    grep -q 'create secret generic postgres-postgresql --from-literal=postgres-password=' "${LOG}"
}

@test "add-ons: nothing is applied on a node" {
    kubeadm_node
    with_addons
    run_applier HOMELAB_ROLE=node
    [ "$status" -eq 0 ]
    ! grep -q '^kubectl' "${LOG}"
}

@test "a directory without an addon file is not an add-on" {
    kubeadm_node
    ADDONS="${BATS_TEST_TMPDIR}/addons"
    mkdir -p "${ADDONS}/10-demo" "${ADDONS}/20-other"
    printf 'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: c\n' >"${ADDONS}/10-demo/10-demo.yaml"
    cp "${ADDONS}/10-demo/10-demo.yaml" "${ADDONS}/20-other/10-other.yaml"
    printf '# comment\n\non kubeadm\n' >"${ADDONS}/20-other/addon"
    run_applier
    [ "$status" -eq 0 ]
    [[ "$(applied_components)" == *"kured other" ]]
}

console_issue() {
    echo "${FAKE_ROOT}/run/issue.d/51-kubestellar-console.issue"
}

@test "KubeStellar Console: deployed without OAuth, its sign-in behind a generated login" {
    kubeadm_node
    with_addons
    run_applier LOGIN_PASSWORD=0123456789abcdef0123456789abcdef
    [ "$status" -eq 0 ]
    [[ "$output" == *"kubestellar-console: ready"* ]]
    # The NetworkPolicy before the Console runs, the gate before its route.
    order=$(ls "${APPLIED}" | sed -n 's/^[0-9]*-\(05-networkpolicy\|10-kubestellar-console\|11-login-gate\|20-httproute\)\.yaml$/\1/p' | paste -sd' ')
    [[ "${order}" == *"05-networkpolicy 10-kubestellar-console 11-login-gate 20-httproute" ]]
    console=$(ls "${APPLIED}"/*-10-kubestellar-console.yaml)
    grep -q 'homelab.bluefin.dev/console-sign-in: "password"' "${console}"
    grep -A1 'name: AUTH_ALLOWED_GITHUB_LOGINS' "${console}" | grep -q 'value: ""'
    grep -q 'value: "https://kubestellar.home.arpa"' "${console}"
    ! grep -q 'HOMELAB_' "${console}"
    grep -q '"kubestellar.home.arpa"' "${APPLIED}"/*-11-login-gate.yaml
    ! grep -q 'create secret generic kubestellar-console-github-oauth' "${LOG}"
    [[ "$(grep 'create secret generic kubestellar-console-bootstrap' "${LOG}")" =~ --from-literal=bootstrap-token=[0-9a-f]{48} ]]
    line=$(grep 'create secret generic kubestellar-console-login' "${LOG}")
    [[ "${line}" =~ --from-literal=\.htpasswd=admin:\{SHA\}([A-Za-z0-9+/]{27}=)\ --from-literal=password=([0-9a-f]{32})\  ]]
    hash=${BASH_REMATCH[1]} password=${BASH_REMATCH[2]}
    # Envoy's {SHA}: base64 of the binary SHA-1 of the password.
    [ "$(printf %s "${hash}" | base64 -d | od -An -tx1 | tr -d ' \n')" = "$(printf %s "${password}" | sha1sum | sed 's/ .*//')" ]
    [[ "$output" != *"${password}"* ]] && [[ "$output" != *"${hash}"* ]]
    for secret in jwt-secret bootstrap-token; do
        value=$(grep -o -- "--from-literal=${secret}=[0-9a-f]*" "${LOG}" | cut -d= -f3)
        [[ "$output" != *"${value}"* ]]
    done
    # The login on the local consoles (like the join passphrase), not the journal.
    [ "$(stat -c %a "$(console_issue)")" = 600 ]
    grep -qx 'KubeStellar Console: https://kubestellar.home.arpa (user admin, password 0123456789abcdef0123456789abcdef)' "$(console_issue)"
    grep -q "get secret kubestellar-console-login -o jsonpath='{.data.password}' | base64 -d" "$(console_issue)"
    [[ "$output" != *0123456789abcdef0123456789abcdef* ]]
    [[ "$output" != *"without HOMELAB_KUBESTELLAR_CONSOLE_ALLOWED_LOGINS"* ]]
}

@test "KubeStellar Console: the generated Secrets are never rotated" {
    kubeadm_node
    with_addons
    run_applier SECRET_RC=0
    [ "$status" -eq 0 ]
    ! grep -q 'create secret generic kubestellar-console' "${LOG}"
}

@test "KubeStellar Console: GitHub sign-in once its OAuth app files exist" {
    kubeadm_node
    with_addons
    d="${FAKE_ROOT}/etc/bluefin/homelab.d/kubestellar-console"
    mkdir -p "${d}"
    printf %s dummy-id >"${d}/github-client-id"
    run_applier
    [ "$status" -eq 0 ]
    ! grep -q 'create secret generic kubestellar-console-github-oauth' "${LOG}"
    grep -q 'console-sign-in: "password"' "${APPLIED}"/*-10-kubestellar-console.yaml
    printf %s dummy-secret >"${d}/github-client-secret"
    rm -f "${APPLIED}"/*
    : >"${LOG}"
    run_applier SECRET_RC=0
    [ "$status" -eq 0 ]
    grep -q "create secret generic kubestellar-console-github-oauth --from-file=github-client-id=${d}/github-client-id --from-file=github-client-secret=${d}/github-client-secret" "${LOG}"
    grep -q 'console-sign-in: "github"' "${APPLIED}"/*-10-kubestellar-console.yaml
    # The login password still guards the start of GitHub's sign-in.
    ls "${APPLIED}"/*-11-login-gate.yaml
    [[ "$output" == *"<4>kubestellar-console: GitHub sign-in without HOMELAB_KUBESTELLAR_CONSOLE_ALLOWED_LOGINS"* ]]
    [[ "$output" != *dummy-secret* ]]
    rm -f "${APPLIED}"/*
    run_applier SECRET_RC=0 HOMELAB_KUBESTELLAR_CONSOLE_ALLOWED_LOGINS=alice,bob-2 HOMELAB_KUBESTELLAR_CONSOLE_ADMIN_LOGINS=alice
    [[ "$output" != *"without HOMELAB_KUBESTELLAR_CONSOLE_ALLOWED_LOGINS"* ]]
    grep -A1 'name: AUTH_ALLOWED_GITHUB_LOGINS' "${APPLIED}"/*-10-kubestellar-console.yaml | grep -q 'value: "alice,bob-2"'
    grep -A1 'name: AUTH_ADMIN_GITHUB_LOGINS' "${APPLIED}"/*-10-kubestellar-console.yaml | grep -q 'value: "alice"'
}

@test "KubeStellar Console: an invalid login list holds the Console back" {
    kubeadm_node
    with_addons
    run_applier 'HOMELAB_KUBESTELLAR_CONSOLE_ALLOWED_LOGINS=alice;rm'
    [[ "$output" == *"ignoring HOMELAB_KUBESTELLAR_CONSOLE_ALLOWED_LOGINS=alice;rm"* ]]
    [[ "$output" == *"kubestellar-console: skipping 10-kubestellar-console.yaml: HOMELAB_KUBESTELLAR_CONSOLE_ALLOWED_LOGINS not set"* ]]
    ! ls "${APPLIED}"/*-10-kubestellar-console.yaml
}

@test "MCP: read-only by default, read-write only with HOMELAB_MCP_READ_WRITE=yes" {
    kubeadm_node
    with_addons
    run_applier
    grep -q '^    read_only = true$' "${APPLIED}"/*-10-mcp.yaml
    [[ "$output" == *"mcp: skipping 21-client-read-write.yaml: HOMELAB_MCP_READ_WRITE not set"* ]]
    grep -q 'name: view$' "${APPLIED}"/*-20-client.yaml
    grep -q '"mcp.home.arpa"' "${APPLIED}"/*-22-httproute.yaml
    rm -f "${APPLIED}"/*
    run_applier HOMELAB_MCP_READ_WRITE=yes HOMELAB_DOMAIN=lab.example.com
    grep -q '^    read_only = false$' "${APPLIED}"/*-10-mcp.yaml
    grep -q 'name: edit$' "${APPLIED}"/*-21-client-read-write.yaml
    grep -q '"mcp.lab.example.com"' "${APPLIED}"/*-22-httproute.yaml
    rm -f "${APPLIED}"/*
    run_applier HOMELAB_MCP_READ_WRITE=no
    grep -q '^    read_only = true$' "${APPLIED}"/*-10-mcp.yaml
    ! ls "${APPLIED}"/*-21-client-read-write.yaml
}
