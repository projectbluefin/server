kind: manual
description: Build a custom modern server-optimized Linux kernel with KubeVirt, container, and virtualization support.

build-depends:
  - freedesktop-sdk.bst:components/bison.bst
  - freedesktop-sdk.bst:components/flex.bst
  - freedesktop-sdk.bst:components/elfutils.bst
  - freedesktop-sdk.bst:components/gcc.bst
  - freedesktop-sdk.bst:components/openssl.bst
  - freedesktop-sdk.bst:components/bc.bst
  - freedesktop-sdk.bst:components/kmod.bst
  - freedesktop-sdk.bst:components/make.bst
  - freedesktop-sdk.bst:components/sed.bst
  - freedesktop-sdk.bst:components/grep.bst
  - freedesktop-sdk.bst:components/gawk.bst
  - freedesktop-sdk.bst:components/tar.bst
  - freedesktop-sdk.bst:components/gzip.bst
  - freedesktop-sdk.bst:components/stripper.bst

sources:
  - kind: git_repo
    url: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
    track: refs/heads/linux-7.1.y
    ref: c9acdc466e9aa96352f658b9276aa8a45b8e817d

variables:
  strip-binaries: ""

config:
  build-commands:
    - |
      cat <<EOF > flatcar-k8s.fragment
      # --- Flatcar Container Performance Tuning ---
      CONFIG_PREEMPT_NONE=y
      CONFIG_HZ_250=y
      CONFIG_NO_HZ_FULL=y
      CONFIG_CGROUPS=y
      CONFIG_MEMCG=y
      CONFIG_NAMESPACES=y
      CONFIG_USER_NS=y
      CONFIG_OVERLAY_FS=y

      # --- Flatcar CNI / Netfilter Defaults ---
      CONFIG_BRIDGE=y
      CONFIG_BRIDGE_NETFILTER=m
      CONFIG_NF_CONNTRACK=y
      CONFIG_NETFILTER_XT_MATCH_COMMENT=m

      # --- Custom Server / KubeVirt Overrides ---
      CONFIG_HYPERVISOR=y
      CONFIG_KVM=y
      CONFIG_KVM_INTEL=y
      CONFIG_KVM_AMD=y
      CONFIG_VIRTIO=y
      CONFIG_VIRTIO_PCI=y
      CONFIG_VIRTIO_BLK=y
      CONFIG_VIRTIO_NET=y
      CONFIG_VIRTIO_BALLOON=y
      CONFIG_VIRTIO_CONSOLE=y
      CONFIG_VIRTIO_VSOCKETS=y
      CONFIG_VIRTIO_VSOCKETS_COMMON=y

      # Container technologies / systemd
      CONFIG_CGROUP_SCHED=y
      CONFIG_FAIR_GROUP_SCHED=y
      CONFIG_RT_GROUP_SCHED=y
      CONFIG_CGROUP_FREEZER=y
      CONFIG_CGROUP_PIDS=y
      CONFIG_CGROUP_DEVICE=y
      CONFIG_CPUSETS=y
      CONFIG_PROC_PID_CPUSET=y
      CONFIG_CGROUP_CPUACCT=y
      CONFIG_PAGE_COUNTER=y
      CONFIG_CGROUP_HUGETLB=y
      CONFIG_CGROUP_PERF=y
      CONFIG_CGROUP_BPF=y
      CONFIG_UTS_NS=y
      CONFIG_IPC_NS=y
      CONFIG_PID_NS=y
      CONFIG_NET_NS=y
      CONFIG_BTRFS_FS=y
      CONFIG_FUSE_FS=y

      # Integrity / Security
      CONFIG_FS_VERITY=y
      CONFIG_FS_VERITY_BUILTIN_SIGNATURES=y
      CONFIG_SECURITY=y
      CONFIG_SECURITY_SELINUX=y
      CONFIG_SECURITY_APPARMOR=y
      EOF
    - make defconfig
    - scripts/kconfig/merge_config.sh -m .config flatcar-k8s.fragment
    - make olddefconfig
    - make -j%{max-jobs}

  install-commands:
    - |
      mkdir -p "%{install-root}/usr/lib/modules"
      make INSTALL_MOD_PATH="%{install-root}/usr" modules_install

      # Determine kernel release version
      KVER=$(make -s kernelrelease)
      mkdir -p "%{install-root}/usr/lib/modules/${KVER}"

      # Copy bzImage to the standard modules location
      cp arch/x86/boot/bzImage "%{install-root}/usr/lib/modules/${KVER}/vmlinuz"

      # Clean up unneeded build symlinks to keep image size small
      rm -f "%{install-root}/usr/lib/modules/${KVER}/build"
      rm -f "%{install-root}/usr/lib/modules/${KVER}/source"
