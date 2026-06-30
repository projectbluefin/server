kind: manual
description: Compile qemu-img from source.

sources:
  - kind: tar
    url: https://download.qemu.org/qemu-8.2.2.tar.xz
    ref: 847346c1b82c1a54b2c38f6edbd85549edeb17430b7d4d3da12620e2962bc4f3

build-depends:
  - freedesktop-sdk.bst:components/pkg-config.bst
  - freedesktop-sdk.bst:components/python3.bst
  - freedesktop-sdk.bst:components/python3-distlib.bst
  - freedesktop-sdk.bst:components/python3-setuptools.bst
  - freedesktop-sdk.bst:components/python3-packaging.bst
  - freedesktop-sdk.bst:components/ninja.bst
  - freedesktop-sdk.bst:components/meson.bst
  - freedesktop-sdk.bst:components/grep.bst
  - freedesktop-sdk.bst:components/sed.bst
  - freedesktop-sdk.bst:components/gcc.bst
  - freedesktop-sdk.bst:components/diffutils.bst
  - freedesktop-sdk.bst:components/make.bst
  - freedesktop-sdk.bst:components/which.bst

depends:
  - freedesktop-sdk.bst:components/glib.bst
  - freedesktop-sdk.bst:components/pixman.bst

variables:
  strip-binaries: ""

config:
  configure-commands:
    - |
      ./configure \
        --prefix=/usr \
        --disable-system \
        --disable-user \
        --enable-tools \
        --disable-docs \
        --disable-guest-agent \
        --disable-werror \
        --disable-sdl \
        --disable-gtk \
        --disable-vnc \
        --disable-virtfs \
        --disable-vde \
        --disable-brlapi \
        --disable-cap-ng \
        --disable-curl \
        --disable-fdt \
        --disable-kvm \
        --disable-libiscsi \
        --disable-libnfs \
        --disable-mpath \
        --disable-numa \
        --disable-opengl \
        --disable-rbd \
        --disable-rdma \
        --disable-spice \
        --disable-usb-redir \
        --disable-vhost-net \
        --disable-vte \
        --disable-xen

  build-commands:
    - |
      ninja -C build qemu-img

  install-commands:
    - |
      install -D -m 755 build/qemu-img "%{install-root}/usr/bin/qemu-img"
