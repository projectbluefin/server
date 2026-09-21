"""An installer-seeded sysext must keep the stem its extension-release names.

systemd-sysext resolves an extension's metadata by filename stem. An image
merged as ``<name>.raw`` is required to carry
``/usr/lib/extension-release.d/extension-release.<name>``; if it does not, the
extension is refused. The refusal is silent from the build's point of view —
the element builds, ``just validate`` resolves, the installer writes a bootable
disk, and the failure only appears as a missing service on a running machine.

``tests/unit/test_sysupdate_transfers.py`` already enforces this for the
Kubernetes sysext on the *sysupdate* path, where the name is fixed by the
transfer's ``CurrentSymlink``. This module covers the other path: the images
``files/installer/repart.d/30-var.conf`` seeds onto ``/var/lib/extensions`` at
install time, whose names are fixed by ``CopyFiles=`` and by the element that
stages them.

The concrete hazard is the Flatcar containerd import. Upstream names it
``containerd-flatcar.raw`` and ships ``extension-release.containerd-flatcar``.
Shortening it to ``containerd.raw`` anywhere in the chain — the element's
install target, the installer's ``cp`` into the initrd, or the ``CopyFiles=``
here — makes systemd-sysext look for ``extension-release.containerd``, find
nothing, and drop containerd.service. ``kubeadm-init.service`` then has an
unresolvable hard requirement and the control plane never starts.

The chain is asserted end to end so a rename in any one link fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VAR_REPART = ROOT / "files" / "installer" / "repart.d" / "30-var.conf"
INSTALLER = ROOT / "elements" / "oci" / "bluefin-server-installer.bst"
CONTAINERD_ELEMENT = ROOT / "elements" / "flatcar" / "containerd-sysext.bst"
KUBEADM_INIT = ROOT / "files" / "os" / "systemd" / "system" / "kubeadm-init.service"

# Units that only a seeded sysext can provide, mapped to the image that ships
# them. Derived from the image contents, not from configuration: Flatcar's
# containerd-flatcar.raw carries usr/lib/systemd/system/containerd.service.
SYSEXT_PROVIDED_UNITS = {
    "containerd.service": "containerd-flatcar.raw",
}

COPY_FILES_RE = re.compile(r"^CopyFiles=([^:]+):(.+)$", re.MULTILINE)


def seeded_extensions() -> dict[str, str]:
    """``{staged source path: destination path}`` for every seeded sysext."""
    return {
        src: dst
        for src, dst in COPY_FILES_RE.findall(VAR_REPART.read_text(encoding="utf-8"))
        if "/lib/extensions/" in dst
    }


def test_seeded_sysexts_are_decoupled_from_the_host_os_release_version() -> None:
    """A seeded sysext must survive an OS update, so its ID must be ``_any``.

    ``/var`` persists across an A/B root update, so an image sitting in
    ``/var/lib/extensions`` outlives the os-release it was installed against.
    systemd-sysext refuses an extension whose ``ID``/``VERSION_ID`` disagree with
    the host, so an extension pinned to a specific version stops merging the
    first time the OS is updated — taking containerd.service, and therefore
    kubeadm-init.service and the whole cluster, down on an otherwise routine
    reboot.

    ``files/kubernetes/sysext/extension-release.kubernetes`` already uses
    ``ID=_any`` for this reason. Flatcar's containerd image ships
    ``ID=flatcar VERSION_ID=4593.2.5`` instead, which is correct for Flatcar and
    wrong here, so ``elements/flatcar/containerd-sysext.bst`` repacks it. This
    asserts the repack is still happening: dropping it to "import verbatim" is a
    tempting simplification that reintroduces the failure.
    """
    element = CONTAINERD_ELEMENT.read_text(encoding="utf-8")

    assert "unsquashfs" in element and "mksquashfs" in element, (
        f"{CONTAINERD_ELEMENT.relative_to(ROOT)} no longer repacks the upstream "
        "image. Imported verbatim it carries ID=flatcar with a fixed VERSION_ID, "
        "so the merge breaks on the first OS update that bumps flatcar-version."
    )
    assert "ID=_any" in element, (
        f"{CONTAINERD_ELEMENT.relative_to(ROOT)} must rewrite the "
        "extension-release with ID=_any so the sysext is independent of the "
        "host os-release version, matching "
        "files/kubernetes/sysext/extension-release.kubernetes"
    )


def test_every_sysext_provided_unit_a_host_unit_depends_on_is_actually_seeded() -> None:
    """Depending on a sysext-provided unit obliges the installer to seed it.

    Deleting the ``CopyFiles=`` line for containerd would restore exactly the
    failure this whole arrangement exists to fix: kubeadm-init.service depends
    on ``containerd.service``, nothing provides it, and
    bluefin-cluster-bootstrap.service never runs because it declares
    ``Requires=kubeadm-init.service``. The machine boots to multi-user.target
    with no control plane.

    Both ``Requires=`` and ``Wants=`` count. The unit deliberately uses ``Wants=``
    — see ``test_sysext_provided_units_are_not_hard_required`` — so matching only
    ``Requires=`` here would make this gate silently vacuous.
    """
    unit = without_comments(KUBEADM_INIT.read_text(encoding="utf-8"))
    seeded_names = {Path(dst).name for dst in seeded_extensions().values()}

    for dep_unit, image in SYSEXT_PROVIDED_UNITS.items():
        if not any(f"{kw}={dep_unit}" in unit for kw in ("Requires", "Wants")):
            continue
        assert image in seeded_names, (
            f"{KUBEADM_INIT.relative_to(ROOT)} depends on {dep_unit}, which "
            f"only {image} provides, but {VAR_REPART.relative_to(ROOT)} does "
            f"not seed it into /lib/extensions. Seeded images: "
            f"{sorted(seeded_names) or 'none'}. The control plane will not start."
        )


def test_sysext_provided_units_are_not_hard_required() -> None:
    """A unit that only exists after the merge cannot be a ``Requires=``.

    systemd resolves dependencies when it computes the boot transaction, which
    happens before systemd-sysext merges ``/usr``. Observed on a real first boot
    of this image::

        12:06:10.283  Applying preset policy
        12:06:11.751  Merged extensions into '/usr'   <- containerd.service appears
        12:06:13.141  Reached target Multi-User System

    With ``Requires=containerd.service`` the unresolvable dependency made systemd
    drop kubeadm-init.service's job from the transaction entirely. It was never
    re-enqueued after the merge, so its conditions were never evaluated, kubeadm
    never ran, and nothing appeared in ``systemctl list-units --failed``.
    kubelet.service survived the same boot because it only declares
    ``After=containerd.service``; a pure ordering edge on a missing unit is
    ignored rather than fatal.

    ``Wants=`` is ignored the same way, and ``After=`` still orders correctly once
    the merge makes the unit real.
    """
    unit = without_comments(KUBEADM_INIT.read_text(encoding="utf-8"))

    for dep_unit in SYSEXT_PROVIDED_UNITS:
        assert f"Requires={dep_unit}" not in unit, (
            f"{KUBEADM_INIT.relative_to(ROOT)} hard-requires {dep_unit}, which "
            f"does not exist when systemd computes the boot transaction — it "
            f"arrives with the sysext merge. systemd will drop this unit's job "
            f"and never re-enqueue it, so kubeadm never runs and the failure is "
            f"invisible to `systemctl list-units --failed`. Use Wants= plus "
            f"After=."
        )
        assert f"After={dep_unit}" in unit, (
            f"{KUBEADM_INIT.relative_to(ROOT)} must still order itself "
            f"After={dep_unit}, or kubeadm can run before the CRI socket exists."
        )


def test_seeded_images_land_in_the_sysext_scan_directory() -> None:
    seeded = seeded_extensions()

    assert seeded, (
        f"{VAR_REPART.relative_to(ROOT)} seeds no sysext into /lib/extensions; "
        "the installer's offline-merge path has regressed"
    )

    for src, dst in seeded.items():
        assert dst.startswith("/lib/extensions/"), (
            f"{dst} is not under /lib/extensions, so systemd-sysext will not "
            f"scan it (/var is mounted at /var, making this /var/lib/extensions)"
        )
        assert dst.endswith(".raw"), f"{dst} is not a .raw sysext image"
        assert Path(src).name == Path(dst).name, (
            f"{VAR_REPART.relative_to(ROOT)} renames {src} to {dst} in flight. "
            "The seeded name is what systemd-sysext resolves "
            "extension-release.<name> against; renaming here breaks the merge."
        )


def test_installer_stages_every_seeded_image_under_its_seeded_name() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")

    for src in seeded_extensions():
        # repart reads CopyFiles= sources from the installer's own root, which
        # is the staged /layer tree.
        staged = f"/layer{src}"
        assert staged in installer, (
            f"{VAR_REPART.relative_to(ROOT)} seeds {src}, but "
            f"{INSTALLER.relative_to(ROOT)} never stages {staged} into the "
            "initrd, so repart has nothing to copy at install time"
        )


def without_comments(text: str) -> str:
    """Effective directives only, for ``#``-commented formats.

    The prose in these files deliberately names the wrong spelling in order to
    warn against it, so scanning raw text would flag the warning as the defect.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_containerd_keeps_its_upstream_extension_release_stem() -> None:
    """The specific rename that would silently drop containerd.service.

    Flatcar's image carries extension-release.containerd-flatcar, so every link
    in the chain must say ``containerd-flatcar.raw``, never ``containerd.raw``.
    """
    element = CONTAINERD_ELEMENT.read_text(encoding="utf-8")

    assert '"%{install-root}/containerd-flatcar.raw"' in element, (
        f"{CONTAINERD_ELEMENT.relative_to(ROOT)} must install the image as "
        "containerd-flatcar.raw to match extension-release.containerd-flatcar"
    )

    # Only the two `#`-commented files are scanned for the forbidden spelling.
    # The element's `description: |` is a YAML block scalar, not a comment, and
    # it names containerd.raw on purpose to explain the hazard. The element is
    # pinned by the positive assertion above instead, which is the stronger
    # check: it fails if the install target is anything but containerd-flatcar.raw.
    for path in (INSTALLER, VAR_REPART):
        # `containerd.raw` as a whole token — `containerd-flatcar.raw` must not
        # trip this.
        match = re.search(
            r"(?<![\w-])containerd\.raw", without_comments(path.read_text(encoding="utf-8"))
        )
        assert match is None, (
            f"{path.relative_to(ROOT)} refers to containerd.raw. "
            "systemd-sysext would look for extension-release.containerd, which "
            "the Flatcar image does not ship, and refuse to merge it — dropping "
            "containerd.service and leaving kubeadm-init.service with an "
            "unresolvable requirement."
        )
