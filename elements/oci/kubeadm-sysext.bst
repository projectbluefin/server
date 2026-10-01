kind: manual
description: |
  Opt-in systemd-sysext that turns a Bluefin Server node into a kubeadm
  worker: kubelet, kubeadm, kubectl, crictl, containerd, runc and the CNI
  plugins from kubeadm/kubeadm-bin.bst, plus containerd.service,
  kubelet.service with kubeadm's 10-kubeadm.conf drop-in, and the default
  containerd config, crictl config, module and sysctl drop-ins. No preset
  enables anything; Ignition enables containerd.service and kubelet.service
  per node.

  Output: kubeadm_<image-version>.raw, .raw.zst and SHA256SUMS. Locked to
  one image version like the ZFS sysext (extension-release.kubeadm_<ver>,
  ID=bluefin-server, VERSION_ID=<image-version>) and updated in lock-step
  with the OS through the `kubeadm` sysupdate feature.

(@):
- include/arch.yml
- include/image.yml
- include/kubeadm.yml
- include/sysext.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:components/erofs-utils.bst
- freedesktop-sdk.bst:components/zstd.bst
- filename: kubeadm/kubeadm-bin.bst
  config:
    location: /kubeadm

sources:
- kind: local
  path: files/kubeadm/sysext
  directory: sysext-src

variables:
  strip-binaries: ""
  sysext-name: "kubeadm"
  sysext-image: "kubeadm_%{image-version}"
  sysext-release: "kubeadm_%{image-version}"
  sysext-version: "%{image-version}"
  sysext-architecture: "%{systemd-arch}"

config:
  install-commands:
  - |
    set -euo pipefail
    src=sysext-src
    lib="sysext%{indep-libdir}"
    unitdir="${lib}/systemd/system"

    mkdir -p sysext
    cp -a /kubeadm%{prefix} sysext%{prefix}

    install -D -m 0644 -t "${unitdir}" "${src}/containerd.service" "${src}/kubelet.service"
    install -D -m 0644 "${src}/10-kubeadm.conf" "${unitdir}/kubelet.service.d/10-kubeadm.conf"
    install -D -m 0644 "${src}/80-kubeadm.preset" "${lib}/systemd/system-preset/80-kubeadm.preset"
    install -D -m 0644 "${src}/tmpfiles-kubeadm.conf" "${lib}/tmpfiles.d/kubeadm.conf"
    install -D -m 0644 "${src}/modules-load-kubeadm.conf" "${lib}/modules-load.d/kubeadm.conf"
    install -D -m 0644 "${src}/sysctl-90-kubeadm.conf" "${lib}/sysctl.d/90-kubeadm.conf"
    install -D -m 0644 "${src}/config.toml" "sysext%{datadir}/bluefin/containerd/config.toml"
    install -D -m 0644 "${src}/crictl.yaml" "sysext%{datadir}/bluefin/kubeadm/crictl.yaml"

    case "$(cat "sysext%{datadir}/bluefin/containerd/config.toml")" in
      *'sandbox = "%{pause-image}"'*) ;;
      *) echo "ERROR: config.toml sandbox image is not %{pause-image} (include/kubeadm.yml)" >&2; exit 1 ;;
    esac

    # A sysext may only carry /usr (and /opt, which must stay a plain
    # writable host directory for /opt/cni/bin).
    for entry in sysext/* sysext/.[!.]*; do
      [ -e "${entry}" ] || [ -L "${entry}" ] || continue
      [ "${entry}" = "sysext%{prefix}" ] || { echo "ERROR: sysext ships ${entry#sysext}" >&2; exit 1; }
    done

  - "%{sysext-pack}"
