# patches/

`patch_queue` sources apply every file in a directory, in file name order,
on top of the junction they belong to. `just validate` fails if one no longer
applies.

## freedesktop-sdk/

Applied to the freedesktop-sdk junction (`elements/freedesktop-sdk.bst`).
Every patch that edits an FSDK element (0006, 0007 and 0009) changes that element's cache
key and the keys of everything that depends on it, so those artifacts come
from the Bluefin cache or a local build, never from FSDK's cache. Keep the
queue short.

| Patch | Why | Upstream status | Drop when |
|---|---|---|---|
| `0001-project.conf-Add-GNOME-CAS-servers.patch` | Adds the GNOME and Bluefin artifact and source caches to FSDK's own `project.conf`, so the junction pulls from them without per-user BuildStream config. Taken from gnome-build-meta and extended with Bluefin CAS. | Downstream by design (GNOME carries it too). | GNOME/Bluefin caches stop serving FSDK 26.08 artifacts. gnome-50 builds on FSDK 25.08, so check the hit rate before the next FSDK minor. |
| `0006-linux-kubernetes-cilium-networking.patch` | Builds VXLAN, GENEVE, the tc BPF classifier/action, ingress qdisc, INET_DIAG (+TCP/UDP, DIAG_DESTROY) and `NOTRACK` for Cilium and the kubeadm/k0s sysexts. Written into `fdsdk-config.sh`, so FSDK's expected-config check fails the build if Kconfig drops one. | Not proposed upstream. | FSDK's kernel config enables them. |
| `0007-linux-watchdog.patch` | Builds in `WATCHDOG`/`WATCHDOG_CORE` and builds the common x86 server / BMC / Super-I/O watchdog drivers (`i6300esb`, `iTCO_wdt`, `sp5100_tco`, `it87`, `w83627hf_wdt` — which also covers the Nuvoton NCT6775/6776/6779/6791/6792 Super-I/O family — `softdog`, `ipmi_watchdog`) as modules. `/dev/watchdog` (which systemd's `RuntimeWatchdogSec=` needs) only appears once a driver binds: `i6300esb`/`iTCO_wdt`/`sp5100_tco` autoload via modalias; the Super-I/O, IPMI and `softdog` drivers have no modalias and must be loaded via `modules-load.d` or `modprobe`. `softdog` is not autoloaded so it never claims `watchdog0` ahead of a hardware driver.  The x86-only Kconfig symbols are wrapped in `case "$arch" in x86_64)` so the aarch64 build (declared in `project.conf`) does not fail "Missing XYZ" at olddefconfig time (issue #377). | Not proposed upstream. | FSDK's kernel config enables `WATCHDOG` and builds these drivers. |
| `0009-linux-server-no-firmware-hw.patch` | The image ships no `/usr/lib/firmware`, so it turns off Wi-Fi (`WLAN`, `CFG80211`, `MAC80211`), Bluetooth (`BT`) and the `amdgpu`, `radeon`, `nouveau` and `xe` GPU drivers, which need firmware for all or nearly all of their hardware (~24 MB of modules in `/usr`, plus cfg80211, mac80211 and the Bluetooth core built into vmlinux), and on x86_64 compresses vmlinuz with zstd instead of gzip (~3 MB per UKI; arm64 has no Kconfig compression choice, so the switch is arch-guarded). Because FSDK's lines put those drivers in expected-configs, the appended block removes from that check exactly the options that go from set to unset (listed in the kernel build log; `CEC_CORE`/`MEDIA_CEC_RC` go too, since only amdgpu's display code selected them) and leaves every other check in place. Appended after `0007`. | Downstream by design: FSDK's kernel also serves desktops and VMs. | The image ships firmware, or FSDK builds without these drivers and with zstd. |

`0002`–`0005` (glib-stage1 tests off; SONAME symlinks for
gobject-introspection-base, gdk-pixbuf and appstream) were removed with FSDK's
`components/os-release.bst` from `elements/base/base-stack.bst`: that element
was the only path that pulled those four components into the graph. If a new
dependency brings them back, recover the patches from git history.
