kind: compose
description: Chisel linux-firmware down to server-essential blobs only for extreme efficiency.

build-depends:
  - freedesktop-sdk.bst:components/linux-firmware.bst

config:
  # Only include CPU microcode, virtual, net, and amdgpu/APU firmware needed for servers
  include:
    # CPU Microcodes (intel & amd)
    - /usr/lib/firmware/intel-ucode/**
    - /usr/lib/firmware/amd-ucode/**
    
    # APU / APU Graphics (Ryzen AI MAX+ 395 and Strix Halo support on ghost)
    - /usr/lib/firmware/amdgpu/**
    - /usr/lib/firmware/amd/**
    
    # VirtIO / KubeVirt guest hardware support
    - /usr/lib/firmware/virtio/**
    
    # Standard Ethernet & Storage controllers
    - /usr/lib/firmware/intel/e1000/**
    - /usr/lib/firmware/intel/e810/**
    - /usr/lib/firmware/realtek/**
    
    # Regulatory database
    - /usr/lib/firmware/regulatory.db*
