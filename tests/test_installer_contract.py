"""Static contracts for the native installer assembly."""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ELEMENT = ROOT / "elements/oci/bluefin-server-installer.bst"
INSTALLER_STACK = ROOT / "elements/installer/installer-stack.bst"
JUSTFILE = ROOT / "Justfile"
HARNESS = ROOT / "tests/installer-smoke-test"


def test_sysinstall_uses_the_staged_partition_recipes():
    assert ELEMENT.read_text().count("--definitions=/usr/lib/repart.d") == 2


def test_26_08_uki_builds_use_the_module_tree_kernel_and_loader_cache():
    element = ELEMENT.read_text()
    assert 'KERNEL="/target-root/usr/lib/modules/${KVER}/vmlinuz"' in element
    assert 'KERNEL="/layer/usr/lib/modules/${KVER}/vmlinuz"' in element
    assert (
        "printf '/usr/lib/x86_64-linux-gnu\\n"
        "/usr/lib/x86_64-linux-gnu/systemd\\n"
        "include /etc/ld.so.conf.d/*.conf\\n'"
    ) in element
    assert "ldconfig -r /target-root -f /tmp/ld.so.conf" in element
    assert "--install /etc/ld.so.cache" in element
    assert "--install /usr/lib/x86_64-linux-gnu/libc.so.6" in element
    assert "--install /usr/lib/x86_64-linux-gnu/libm.so.6" in element
    assert "--install /usr/bin/mount" in element
    assert "--install /usr/lib/x86_64-linux-gnu/libmount.so.1" in element
    assert "--install /usr/lib/x86_64-linux-gnu/libblkid.so.1" in element
    assert "--install /usr/lib/x86_64-linux-gnu/libeconf.so.0" in element
    assert "--install /usr/lib/x86_64-linux-gnu/libreadline.so.8" in element
    assert "--install /usr/lib/x86_64-linux-gnu/libtinfo.so.6" in element
    assert "--install /usr/lib/x86_64-linux-gnu/libncursesw.so.6" in element
    assert "--install /usr/lib/x86_64-linux-gnu/libtinfow.so.6" in element
    assert "/usr/bin/mount -t devtmpfs -o mode=0755 devtmpfs /dev" in element
    assert "ldconfig -r /tmp/bluefin-server-target-initrd -C /etc/ld.so.cache -f /tmp/ld.so.conf" in element
    assert element.count('"rw console=tty0 console=ttyS0,115200"') == 2


def test_qemu_test_stages_uefi_firmware_from_the_pinned_bst2_image():
    assert './tests/installer-smoke-test "{{bst2_image}}"' in JUSTFILE.read_text()

    harness = HARNESS.read_text()
    assert '"${podman_cmd[@]}" cp "${firmware_container}:/usr/share/qemu/edk2-x86_64-code.fd"' in harness
    assert '"${podman_cmd[@]}" cp "${firmware_container}:/usr/share/qemu/edk2-i386-vars.fd"' in harness


def test_live_installer_includes_the_wrapper_interpreter():
    assert "- freedesktop-sdk.bst:public-stacks/runtime-gnu.bst" in INSTALLER_STACK.read_text()
