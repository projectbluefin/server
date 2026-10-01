#!/usr/bin/env bats
#
# Unit tests for files/os/libexec/bluefin-sysext-modules.
#
# The helper runs against a fake /usr/lib/modules/<kver> tree in
# BATS_TEST_TMPDIR. depmod and modprobe are logging stubs on PATH: the depmod
# stub writes a modules.dep listing every module it can reach through the
# linked tree (following symlinks, like kmod's depmod), so the tests see what
# the real one would index without real ELF modules.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    SCRIPT="${REPO_ROOT}/files/os/libexec/bluefin-sysext-modules"
    STUB_DIR="${BATS_TEST_TMPDIR}/bin"
    LOG="${BATS_TEST_TMPDIR}/calls.log"
    FAKE_USR="${BATS_TEST_TMPDIR}/usr"
    BASEDIR="${BATS_TEST_TMPDIR}/run/bluefin/kmods"
    KVER=7.2.2
    SRC="${FAKE_USR}/lib/modules/${KVER}"
    mkdir -p "$STUB_DIR" "${SRC}/kernel/drivers/gpu/drm" "${FAKE_USR}/lib/extension-release.d"
    : > "$LOG"

    # The base image: its modules, depmod inputs and its own index.
    : > "${SRC}/kernel/drivers/gpu/drm/drm.ko.zst"
    echo kernel/drivers/gpu/drm/drm.ko.zst > "${SRC}/modules.order"
    : > "${SRC}/modules.builtin"
    : > "${SRC}/modules.builtin.modinfo"
    echo "kernel/drivers/gpu/drm/drm.ko.zst:" > "${SRC}/modules.dep"
    : > "${SRC}/modules.alias"

    cat > "${STUB_DIR}/depmod" <<EOF
#!/usr/bin/env bash
echo "depmod \$*" >> "${LOG}"
[ "\$1" = -b ] || exit 64
dir="\$2/lib/modules/\$3"
(cd "\${dir}" && find -L . -name '*.ko*' | sed 's|^\./||; s|\$|:|' | sort) > "\${dir}/modules.dep"
EOF
    cat > "${STUB_DIR}/modprobe" <<EOF
#!/usr/bin/env bash
echo "modprobe \$*" >> "${LOG}"
exit \${MODPROBE_RC:-0}
EOF
    chmod +x "${STUB_DIR}/depmod" "${STUB_DIR}/modprobe"
}

# add_sysext <name> <module...>: merge a fake module sysext into the tree.
add_sysext() {
    local name="$1" m
    shift
    mkdir -p "${SRC}/extra/${name}"
    for m in "$@"; do
        : > "${SRC}/extra/${name}/${m}.ko.zst"
    done
    echo ID=bluefin-server > "${FAKE_USR}/lib/extension-release.d/extension-release.${name}"
}

run_helper() {
    run env PATH="${STUB_DIR}:${PATH}" BLUEFIN_KMOD_USR="${FAKE_USR}" \
        BLUEFIN_KMOD_BASEDIR="${BASEDIR}" BLUEFIN_KVER="${KVER}" \
        bash "$SCRIPT" "$@"
}

depmod_runs() {
    grep -c '^depmod ' "$LOG" || true
}

@test "without arguments it prints usage and exits 2" {
    run_helper
    [ "$status" -eq 2 ]
    [[ "$output" == *"usage:"* ]]
    [ "$(depmod_runs)" = 0 ]
}

@test "an option other than --basedir is refused before any work" {
    run_helper -r zfs
    [ "$status" -eq 2 ]
    [ ! -e "$LOG" ] || [ "$(depmod_runs)" = 0 ]
}

@test "a kernel without a module tree fails" {
    rm -rf "${SRC}"
    run_helper zfs
    [ "$status" -eq 1 ]
    [[ "$output" == *"no modules for kernel ${KVER}"* ]]
}

@test "indexes the base and every sysext's modules, then modprobes from the run tree" {
    add_sysext zfs spl zfs
    add_sysext nvidia nvidia nvidia-uvm
    run_helper zfs
    [ "$status" -eq 0 ]

    tree="${BASEDIR}/usr/lib/modules/${KVER}"
    grep -qx "depmod -b ${BASEDIR}\.[A-Za-z0-9]* ${KVER}" "$LOG"
    grep -qx "modprobe -d ${BASEDIR} -S ${KVER} -a -- zfs" "$LOG"
    [ "$(readlink "${BASEDIR}/lib")" = usr/lib ]
    for entry in kernel extra modules.order modules.builtin modules.builtin.modinfo; do
        [ "$(readlink "${tree}/${entry}")" = "${SRC}/${entry}" ]
    done
    # The base image's own index is never reused: depmod writes a new one.
    [ ! -L "${tree}/modules.dep" ] && [ ! -e "${tree}/modules.alias" ]
    [ "$(cat "${tree}/modules.dep")" = "$(printf '%s\n' \
        extra/nvidia/nvidia-uvm.ko.zst: extra/nvidia/nvidia.ko.zst: \
        extra/zfs/spl.ko.zst: extra/zfs/zfs.ko.zst: \
        kernel/drivers/gpu/drm/drm.ko.zst:)" ]
    [[ "$output" == *"indexed 5 modules for ${KVER} in ${BASEDIR}"* ]]
}

@test "loads several modules in one modprobe -a call" {
    add_sysext nvidia nvidia nvidia-uvm nvidia-modeset nvidia-drm
    run_helper nvidia nvidia-uvm nvidia-modeset nvidia-drm
    [ "$status" -eq 0 ]
    grep -qx "modprobe -d ${BASEDIR} -S ${KVER} -a -- nvidia nvidia-uvm nvidia-modeset nvidia-drm" "$LOG"
}

@test "an unchanged module set reuses the index" {
    add_sysext zfs spl zfs
    run_helper zfs
    run_helper zfs
    [ "$status" -eq 0 ]
    [ "$(depmod_runs)" = 1 ]
    [ "$(grep -c '^modprobe ' "$LOG")" = 2 ]
}

@test "a newly merged sysext rebuilds the index" {
    add_sysext zfs spl zfs
    run_helper zfs
    add_sysext nvidia nvidia
    run_helper nvidia
    [ "$status" -eq 0 ]
    [ "$(depmod_runs)" = 2 ]
    grep -qx 'extra/nvidia/nvidia.ko.zst:' "${BASEDIR}/usr/lib/modules/${KVER}/modules.dep"
}

@test "an unmerged sysext drops out of the index" {
    add_sysext zfs spl zfs
    add_sysext nvidia nvidia
    run_helper zfs
    rm -rf "${SRC}/extra/nvidia" "${FAKE_USR}/lib/extension-release.d/extension-release.nvidia"
    run_helper zfs
    [ "$(depmod_runs)" = 2 ]
    ! grep -q nvidia "${BASEDIR}/usr/lib/modules/${KVER}/modules.dep"
}

@test "--basedir prints the base directory and loads nothing" {
    add_sysext zfs zfs
    run_helper --basedir
    [ "$status" -eq 0 ]
    [ "${lines[-1]}" = "${BASEDIR}" ]
    [ "$(depmod_runs)" = 1 ]
    ! grep -q '^modprobe ' "$LOG"
}

@test "modprobe's failure is the helper's exit status" {
    add_sysext nvidia nvidia
    MODPROBE_RC=1 run_helper nvidia
    [ "$status" -eq 1 ]
}

@test "a failed depmod leaves no index behind" {
    add_sysext zfs zfs
    printf '#!/usr/bin/env bash\nexit 1\n' > "${STUB_DIR}/depmod"
    run_helper zfs
    [ "$status" -ne 0 ]
    [ ! -e "${BASEDIR}/stamp" ]
    [ -z "$(find "${BASEDIR%/*}" -maxdepth 1 -name 'kmods.*' ! -name kmods.lock)" ]
    ! grep -q '^modprobe ' "$LOG"
}
