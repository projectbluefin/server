# patches/

`patch_queue` sources apply every file in a directory, in file name order,
on top of the junction they belong to. `just validate` fails if one no longer
applies.

## freedesktop-sdk/

Applied to the freedesktop-sdk junction (`elements/freedesktop-sdk.bst`).
Every patch that edits an FSDK element (0006) changes that element's cache
key and the keys of everything that depends on it, so those artifacts come
from the Bluefin cache or a local build, never from FSDK's cache. Keep the
queue short.

| Patch | Why | Upstream status | Drop when |
|---|---|---|---|
| `0001-project.conf-Add-GNOME-CAS-servers.patch` | Adds the GNOME artifact and source cache to FSDK's own `project.conf`, so the junction pulls from it without per-user BuildStream config. Taken from gnome-build-meta. | Downstream by design (GNOME carries it too). | GNOME's cache stops serving FSDK 26.08 artifacts. gnome-50 builds on FSDK 25.08, so check the hit rate before the next FSDK minor. |
| `0006-linux-kubernetes-cilium-networking.patch` | Builds VXLAN, GENEVE, the tc BPF classifier/action, ingress qdisc, INET_DIAG (+TCP/UDP, DIAG_DESTROY) and `NOTRACK` for Cilium and the kubeadm/k0s sysexts. Written into `fdsdk-config.sh`, so FSDK's expected-config check fails the build if Kconfig drops one. | Not proposed upstream. | FSDK's kernel config enables them. |

`0002`–`0005` (glib-stage1 tests off; SONAME symlinks for
gobject-introspection-base, gdk-pixbuf and appstream) were removed with FSDK's
`components/os-release.bst` from `elements/base/base-stack.bst`: that element
was the only path that pulled those four components into the graph. If a new
dependency brings them back, recover the patches from git history.
