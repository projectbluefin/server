"""The initrd ships systemd-resolved but, without this symlink, no /etc/resolv.conf,
so libc (and importd/curl) cannot resolve a hostname: only IP-literal pull URLs
worked. Found booting the netboot UKI on Akamai Cloud, where the pull URL is
github.com. tmpfiles.d rules for it exist but are not applied in the initrd,
so the link is shipped directly."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK = ROOT / "files" / "initrd" / "etc" / "resolv.conf"


def test_initrd_points_libc_at_the_resolved_stub() -> None:
    assert LINK.is_symlink()
    assert os.readlink(LINK) == "../run/systemd/resolve/stub-resolv.conf"
