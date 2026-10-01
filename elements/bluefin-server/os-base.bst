kind: stack
description: |
  freedesktop-sdk userspace for the Bluefin Server OS payload: systemd
  (v261 in FSDK 26.08), core tools, networking, SSH, and update/verity
  plumbing. The kernel comes from bluefin-server/kernel-modules.bst.

depends:
- freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- freedesktop-sdk.bst:components/ca-certificates.bst
- freedesktop-sdk.bst:components/tzdata.bst
- freedesktop-sdk.bst:components/hosts.bst
- freedesktop-sdk.bst:components/nsswitch-config.bst
# /etc/protocols and /etc/services (IANA registries) for getprotobyname()
# and getservbyname(); libtirpc needs them, e.g. mount.nfs for NFSv3.
- freedesktop-sdk.bst:components/iana-config.bst
- freedesktop-sdk.bst:components/bash-config.bst
- freedesktop-sdk.bst:integration/extra-fs.bst
- freedesktop-sdk.bst:integration/ldconfig.bst

- freedesktop-sdk.bst:components/systemd.bst
- freedesktop-sdk.bst:components/dbus.bst
- freedesktop-sdk.bst:components/dbus-broker.bst
- freedesktop-sdk.bst:components/kmod.bst
- freedesktop-sdk.bst:components/shadow.bst
- freedesktop-sdk.bst:components/util-linux-full.bst
- freedesktop-sdk.bst:components/procps.bst
- freedesktop-sdk.bst:components/less.bst
- freedesktop-sdk.bst:components/sudo.bst

- freedesktop-sdk.bst:components/iproute2.bst
- freedesktop-sdk.bst:components/openssh-systemd.bst
- freedesktop-sdk.bst:components/curl.bst

- freedesktop-sdk.bst:components/cryptsetup.bst
- freedesktop-sdk.bst:components/lvm2.bst
- freedesktop-sdk.bst:components/tpm2-tss.bst
- freedesktop-sdk.bst:components/gnupg.bst
- freedesktop-sdk.bst:components/xfsprogs.bst
- freedesktop-sdk.bst:components/e2fsprogs.bst
- freedesktop-sdk.bst:components/dosfstools.bst

# iSCSI initiator (iscsiadm, iscsid; socket-activated) for iSCSI CSI volumes.
- freedesktop-sdk.bst:components/open-iscsi.bst

# NFS client (mount.nfs, rpc.statd; nfs-client.target) for NFS CSI/PV volumes.
# Built from source: FSDK 26.08 has no nfs-utils or rpcbind element.
- bluefin-server/nfs-utils.bst
- bluefin-server/rpcbind.bst

- bluefin-server/kernel-modules.bst
