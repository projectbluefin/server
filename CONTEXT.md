# Bluefin Server

An immutable, Freedesktop-SDK-based Linux server operating system providing native systemd update and extension mechanisms.

## Language

**OS DDI**:
The immutable raw disk image payload containing the base operating system root filesystem.
_Avoid_: base image, OS rootfs, root tarball

**Installer**:
A bootable GPT raw disk image executing systemd-repart to partition and install Bluefin Server onto target media.
_Avoid_: live ISO, installation media, setup script

**Sysext**:
A systemd-sysext extension raw image merged into `/usr` to deliver decoupled server runtimes such as k0s.
_Avoid_: addon, plugin, package, sidecar

**Transfer**:
A systemd-sysupdate definition mapping a remote release asset to a local target file or partition.
_Avoid_: update manifest, download job, sync rule

**countme**:
Privacy-preserving counting mechanism for measuring adoption and system installations.
_Avoid_: telemetry, tracking, spyware, metrics
