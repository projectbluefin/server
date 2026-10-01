kind: manual
description: |
  rpcbind, the ONC RPC portmapper, for the NFS client. rpc.statd (NFSv3
  locking, bluefin-server/nfs-utils.bst) registers its listener with the
  local rpcbind and exits when there is none, and NFS servers look statd up
  through it (port 111) to send SM_NOTIFY after they reboot. FSDK 26.08 has
  libtirpc but no rpcbind element, so it is built here from the upstream
  tarball.

  Socket-activated: 80-bluefin-nfs.preset enables rpcbind.socket and keeps
  rpcbind.service off, so the daemon starts on the first RPC registration.
  It runs as the "rpc" user (sysusers.d) and keeps its warm-start state in
  /run/rpcbind, which it creates itself. The service unit depends on
  rpcbind.target from systemd.

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst

depends:
- freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
- freedesktop-sdk.bst:components/libtirpc.bst
- freedesktop-sdk.bst:components/systemd-libs.bst

variables:
  rpcbind-version: 1.3.1

config:
  configure-commands:
  - |
    ./configure \
      --prefix="%{prefix}" \
      --bindir="%{bindir}" \
      --sbindir="%{sbindir}" \
      --sysconfdir="%{sysconfdir}" \
      --mandir="%{mandir}" \
      --enable-warmstarts \
      --with-statedir=/run/rpcbind \
      --with-rpcuser=rpc \
      --with-systemdsystemunitdir="%{indep-libdir}/systemd/system"

  build-commands:
  - make -j%{max-jobs}

  install-commands:
  - make -j1 install DESTDIR="%{install-root}"

  # Same fixed uid as Fedora; systemd-sysusers applies this at image build
  # (oci/bluefin-server-usr.bst), so the account is in the factory /etc.
  - |
    install -d "%{install-root}%{indep-libdir}/sysusers.d"
    printf 'u rpc 32 "Rpcbind Daemon" -\n' \
      > "%{install-root}%{indep-libdir}/sysusers.d/rpcbind.conf"

  - |
    %{install-extra}

sources:
- kind: tar
  url: sourceforge_download:project/rpcbind/rpcbind/%{rpcbind-version}/rpcbind-%{rpcbind-version}.tar.bz2
  ref: 8e551b445f5172f8ef218845af342fb2a2d741b57ce8c777c781a01ea92f92a5
