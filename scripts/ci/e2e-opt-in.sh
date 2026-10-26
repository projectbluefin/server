#!/usr/bin/env bash
# The weekly end-to-end checks of the opt-in features that build.yml's boot
# test never boots: mDNS between appliances, the kubeadm and homelab sysexts
# as a cluster (from Ignition, from the published templates and from the USB
# installer's Homelab entries) and the NVIDIA driver sysext. Each scenario is
# one dogfood script call on a published release set;
# .github/workflows/e2e-opt-in.yml runs them as a matrix, one runner each.
#
#   bash scripts/ci/e2e-opt-in.sh <scenario> <dir>   run a scenario on the set in <dir>
#   bash scripts/ci/e2e-opt-in.sh --list <dir>       print every scenario's calls, run nothing
#   bash scripts/ci/e2e-opt-in.sh --scenarios        print the scenario names
#   bash scripts/ci/e2e-opt-in.sh --install-tools    install the host tools beyond
#                                                    scripts/ci/install-qemu-ovmf.sh's (sudo)
#
# The kubeadm and homelab scenarios pull container images, so the guests
# need internet access.
set -euo pipefail

scenarios=(mdns kubeadm nvidia homelab-cluster homelab-templates homelab-installer)

# helm renders Cilium for dogfood-kubeadm.sh. Bumped by hand, with the
# checksum from https://get.helm.sh/helm-<version>-linux-amd64.tar.gz.sha256sum.
HELM_VERSION=v3.22.1
HELM_SHA256=896cf63684a42a723d61c980369d6e588330927deb13676ca0d85006dd6da0ea

usage() {
    echo "usage: $0 <scenario> <dir> | --list <dir> | --scenarios | --install-tools (scenarios: ${scenarios[*]})" >&2
    exit 2
}

# The dogfood script calls of scenario $1 on the set in $2, one per line.
calls() {
    local scenario="$1" dir="$2" sysext found=0
    case "${scenario}" in
        nvidia)
            # Every driver flavour the set ships; the toolkit has a version of its own.
            for sysext in "${dir}"/nvidia-open-[0-9]*_*.raw.zst; do
                [ -e "${sysext}" ] || continue
                printf 'scripts/dogfood-nvidia.sh %s %s\n' "${dir}" "${sysext}"
                found=1
            done
            [ "${found}" = 1 ] || { echo "ERROR: no nvidia-open-*_<version>.raw.zst in ${dir}" >&2; return 1; } ;;
        *)
            printf 'scripts/dogfood-%s.sh %s\n' "${scenario}" "${dir}" ;;
    esac
}

install_tools() {
    local tarball="${RUNNER_TEMP:-/tmp}/helm.tar.gz"
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends swtpm swtpm-tools xfsprogs zstd
    curl -fsSL --retry 3 -o "${tarball}" "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz"
    echo "${HELM_SHA256}  ${tarball}" | sha256sum -c -
    sudo tar -xzf "${tarball}" -C /usr/local/bin --strip-components=1 linux-amd64/helm
    helm version --short
}

case "${1:-}" in
    --scenarios) [ "$#" = 1 ] || usage; printf '%s\n' "${scenarios[@]}"; exit 0 ;;
    --install-tools) [ "$#" = 1 ] || usage; install_tools; exit 0 ;;
    --list)
        [ "$#" = 2 ] || usage
        for scenario in "${scenarios[@]}"; do
            calls "${scenario}" "$2" | sed "s|^|${scenario}: |"
        done
        exit 0 ;;
    ''|-*) usage ;;
esac
[ "$#" = 2 ] || usage
scenario="$1" dir="$2"
[[ " ${scenarios[*]} " == *" ${scenario} "* ]] || usage
[ -d "${dir}" ] || { echo "ERROR: no such directory: ${dir}" >&2; exit 1; }

started=${SECONDS}
mapfile -t commands < <(calls "${scenario}" "${dir}")
[ "${#commands[@]}" -gt 0 ] || exit 1
for command in "${commands[@]}"; do
    read -ra argv <<<"${command}"
    echo "::group::${scenario}: ${command}"
    if ! bash "${argv[@]}"; then
        echo "::endgroup::"
        echo "::error title=e2e (${scenario})::${command} failed after $((SECONDS - started))s"
        exit 1
    fi
    echo "::endgroup::"
done
echo "::notice title=e2e (${scenario})::passed in $((SECONDS - started))s"
