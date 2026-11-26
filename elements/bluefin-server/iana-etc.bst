kind: manual
description: |
  /etc/protocols and /etc/services: the IANA protocol-number and
  service-name registries, which glibc's getprotobyname() and
  getservbyname() read (libtirpc needs "tcp", "udp" and "sunrpc" for NFSv3).

  From Mic92/iana-etc, the source Linux From Scratch uses: a weekly job
  regenerates both files from IANA's XML registries and tags a release,
  named for the snapshot date, whenever they change. This replaces FSDK's
  components/iana-config.bst, whose upstream stopped at the 2019-07-16
  snapshot (#318). .github/scripts/track-binaries.py proposes each new
  release, with the sha256 Mic92 publishes next to the tarball.

build-depends:
- base/base-stack.bst

variables:
  # Mic92/iana-etc release tag (YYYYMMDD): the date of the IANA snapshot.
  iana-etc-version: "20261119"
  # Text files only.
  strip-binaries: ''

sources:
- kind: tar
  url: github:Mic92/iana-etc/releases/download/%{iana-etc-version}/iana-etc-%{iana-etc-version}.tar.gz
  ref: e674f0fff7df6b18b3387114b246e184e5413679a874bc28e8bde8ac2cdb2529

config:
  install-commands:
  - install -D -m 0644 -t "%{install-root}%{sysconfdir}" protocols services
