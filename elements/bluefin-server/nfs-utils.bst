kind: manual
description: |
  NFS client from nfs-utils: mount.nfs / mount.nfs4 / umount.nfs (the
  helpers util-linux mount(8) execs for -t nfs), rpc.statd and sm-notify
  (NFSv3 locking), nfsidmap (NFSv4 id mapping through request-key),
  nfsstat, showmount, rpcdebug, nfsconf and nfsrahead, with upstream's
  nfs-client.target, rpc-statd*.service and udev rules.

  Without mount.nfs, util-linux mount(8) hands "-t nfs" straight to the new
  mount API and the kernel refuses it: "fsconfig() failed: NFS: mount
  program didn't pass remote address", which fails every kubelet NFS volume.
  FSDK 26.08 has libtirpc and keyutils but no nfs-utils element, so it is
  built here from the upstream tarball.

  Client only: the server (rpc.nfsd, rpc.mountd, exportfs, fsidd,
  rpc.idmapd, nfs-server.service and friends, rpc_pipefs, the generators)
  is dropped after install. Not built: GSS/Kerberos (no krb5 in the image),
  nfsdcld/nfsdcltrack/nfsdctl (server-side), junctions (libxml2), LDAP,
  tcp-wrappers. The python tools (mountstats, nfsiostat, rpcctl,
  nfsdclnts) are dropped as the image has no python.

  Runtime state: /usr is read-only and /var starts empty (tmpfs on diskless
  nodes), so the statd state directory comes from tmpfiles.d, owned by the
  rpcuser account (sysusers.d) that rpc.statd and sm-notify drop to.
  rpc.statd registers with rpcbind (bluefin-server/rpcbind.bst).

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst
# configure hard-requires libevent and sqlite3 even though only the dropped
# fsidd/idmapd/nfsdcld link them.
- freedesktop-sdk.bst:components/libevent.bst
- freedesktop-sdk.bst:components/sqlite.bst

depends:
- freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
- freedesktop-sdk.bst:components/libtirpc.bst
- freedesktop-sdk.bst:components/keyutils.bst
- freedesktop-sdk.bst:components/libcap.bst
# libmount for mount.nfs and nfsrahead, libuuid/libblkid headers for configure.
- freedesktop-sdk.bst:components/util-linux-libs.bst
# start-statd runs systemctl and flock; the kernel calls request-key for
# nfsidmap (keyutils, in depends above).
- freedesktop-sdk.bst:components/systemd.bst
- freedesktop-sdk.bst:components/util-linux.bst
- bluefin-server/rpcbind.bst

variables:
  nfs-utils-version: 2.8.7
  statd-statedir: "%{localstatedir}/lib/nfs/statd"

config:
  configure-commands:
  - |
    ./configure \
      --prefix="%{prefix}" \
      --bindir="%{bindir}" \
      --sbindir="%{sbindir}" \
      --libdir="%{libdir}" \
      --libexecdir="%{libexecdir}" \
      --includedir="%{includedir}" \
      --datadir="%{datadir}" \
      --mandir="%{mandir}" \
      --sysconfdir="%{sysconfdir}" \
      --localstatedir="%{localstatedir}" \
      --enable-shared \
      --disable-static \
      --disable-sbin-override \
      --enable-libmount-mount \
      --enable-mountconfig \
      --enable-ipv6 \
      --with-rpcgen=internal \
      --with-systemd="%{indep-libdir}/systemd/system" \
      --with-statdpath="%{statd-statedir}" \
      --with-statduser=rpcuser \
      --with-start-statd="%{sbindir}/start-statd" \
      --with-pluginpath="%{libdir}/libnfsidmap" \
      --disable-gss \
      --disable-svcgss \
      --disable-nfsv4server \
      --disable-nfsdcld \
      --disable-nfsdcltrack \
      --disable-nfsdctl \
      --disable-junction \
      --disable-ldap \
      --without-tcp-wrappers

  build-commands:
  - make -j%{max-jobs}

  install-commands:
  - |
    set -eu
    make -j1 install DESTDIR="%{install-root}"
    find "%{install-root}" -name '*.la' -delete

  # Client only: drop the server daemons, their units and generators, the
  # python tools, the internal rpcgen (a build tool), and the /var state the
  # install hook seeds (etab/rmtab are server files; statd's directory is
  # created at boot by tmpfiles.d below).
  - |
    set -eu
    root="%{install-root}"
    for p in rpc.mountd rpc.nfsd exportfs fsidd rpc.idmapd \
             mountstats nfsiostat rpcctl nfsdclnts rpcgen; do
      rm -f "${root}%{sbindir}/${p}"
    done
    for u in nfs-server.service nfs-mountd.service nfs-idmapd.service \
             fsidd.service proc-fs-nfsd.mount \
             var-lib-nfs-rpc_pipefs.mount rpc_pipefs.target; do
      rm -f "${root}%{indep-libdir}/systemd/system/${u}"
    done
    rm -rf "${root}%{indep-libdir}/systemd/system-generators"
    rm -rf "${root}%{localstatedir}"
    for p in mount.nfs mount.nfs4 umount.nfs umount.nfs4 rpc.statd sm-notify \
             start-statd nfsidmap nfsstat showmount rpcdebug nfsconf; do
      [ -e "${root}%{sbindir}/${p}" ] || { echo "ERROR: ${p} missing" >&2; exit 1; }
    done
    for u in nfs-client.target nfs-utils.service rpc-statd.service rpc-statd-notify.service; do
      [ -e "${root}%{indep-libdir}/systemd/system/${u}" ] || { echo "ERROR: ${u} missing" >&2; exit 1; }
    done

  # rpc.statd and sm-notify drop privileges to the owner of the sm/
  # directory; a fixed uid (Fedora's) keeps installed nodes' /var/lib/nfs
  # valid across image updates. systemd-sysusers runs at image build
  # (oci/bluefin-server-usr.bst), so the account is in the factory /etc.
  - |
    set -eu
    root="%{install-root}"
    install -d "${root}%{indep-libdir}/sysusers.d" "${root}%{indep-libdir}/tmpfiles.d"
    printf 'u rpcuser 29 "RPC Service User" %{localstatedir}/lib/nfs\n' \
      > "${root}%{indep-libdir}/sysusers.d/nfs-utils.conf"
    cat > "${root}%{indep-libdir}/tmpfiles.d/nfs-utils.conf" <<EOF
    d %{localstatedir}/lib/nfs 0755 root root -
    d %{statd-statedir} 0700 rpcuser rpcuser -
    d %{statd-statedir}/sm 0700 rpcuser rpcuser -
    d %{statd-statedir}/sm.bak 0700 rpcuser rpcuser -
    EOF

  # Both units have DefaultDependencies=no; order them after the tmpfiles
  # run that creates the state directory.
  - |
    set -eu
    for u in rpc-statd.service rpc-statd-notify.service; do
      d="%{install-root}%{indep-libdir}/systemd/system/${u}.d"
      install -d "${d}"
      cat > "${d}/10-bluefin-statedir.conf" <<EOF
    [Unit]
    After=systemd-tmpfiles-setup.service
    RequiresMountsFor=%{statd-statedir}
    EOF
    done

  # NFSv4 id mapping: the kernel's request-key upcall runs nfsidmap. Lands
  # in the factory /etc with the rest of %{sysconfdir}.
  - |
    install -Dm644 utils/nfsidmap/id_resolver.conf \
      "%{install-root}%{sysconfdir}/request-key.d/id_resolver.conf"

  - |
    %{install-extra}

public:
  bst:
    split-rules:
      devel:
        (>):
        - '%{libdir}/libnfsidmap.so'

sources:
- kind: tar
  url: kernel_pub:linux/utils/nfs-utils/%{nfs-utils-version}/nfs-utils-%{nfs-utils-version}.tar.xz
  ref: 59d0f1e17b18efaa60ea3ccf89a9cad3217f8d3b23c18d2fe34b25c8969d60ae
