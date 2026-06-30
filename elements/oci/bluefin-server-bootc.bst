kind: script
description: Package the Bluefin Server stack into a bootc-compatible OCI image.

build-depends:
  - freedesktop-sdk.bst:components/oci-builder.bst
  - filename: bluefin-server/os-stack.bst
    config:
      location: /layer

config:
  commands:
    # Set up standard bootc folder structure
    - |
      set -eu
      L=/layer

      # bootc expects specific mounts and state layouts
      mkdir -p "$L"/sysroot
      mkdir -p "$L"/run
      mkdir -p "$L"/var
      mkdir -p "$L"/etc

      # Target standard multi-user system boot
      mkdir -p "$L"/etc/systemd/system
      ln -sf /usr/lib/systemd/system/multi-user.target "$L"/etc/systemd/system/default.target

      # Create systemd-sysext folder
      mkdir -p "$L"/usr/lib/extension-images

    - |
      cd "%{install-root}"
      build-oci <<EOF
      mode: oci
      gzip: disabled
      images:
      - os: linux
        architecture: "%{go-arch}"
        layer: /layer
        comment: "FSDK Bluefin Server bootc image"
        config:
          Entrypoint: ["/usr/lib/systemd/systemd"]
          Cmd: ["--system"]
          Labels:
            'org.opencontainers.image.title': 'bluefin-server-bootc'
            'org.opencontainers.image.description': 'An FSDK-built server bootc image designed for Flatcar sysext compatibility'
            'org.opencontainers.image.vendor': 'Project Bluefin'
            'org.opencontainers.image.licenses': 'Apache-2.0'
            'org.opencontainers.image.url': 'https://github.com/castrojo/bluefin-server'
            'org.opencontainers.image.source': 'https://github.com/castrojo/bluefin-server'
            'io.projectbluefin.bootc.sysext': 'compatible-with-flatcar'
        index-annotations:
          'org.opencontainers.image.ref.name': 'ghcr.io/castrojo/bluefin-server-bootc:latest'
      EOF
