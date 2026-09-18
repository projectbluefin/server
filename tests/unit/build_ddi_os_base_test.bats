#!/usr/bin/env bats
#
# Unit tests for the `os-base` option in the `build-ddi` recipe of the
# top-level Justfile (projectbluefin/server#129).
#
# `build-ddi` composes the shipped Bluefin Server OS payload. The `os-base`
# option selects the payload base for the FSDK-vs-Flatcar parity harness:
# `fsdk` (default) builds the FSDK-composed payload, and `flatcar-reference`
# builds the imported Flatcar reference tree once the #126 element lands.
#
# The recipe never builds a real payload in the test. It delegates to the
# `bst` recipe, which runs `podman`. `podman` is replaced by a logging stub on
# PATH that records its arguments and exits 0, so the recipe that routes
# `os-base` to the right element runs to completion and the chosen element is
# recorded in the call log instead of being composed.

setup() {
    if ! command -v just >/dev/null 2>&1; then
        skip "just is not installed"
    fi

    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    JUSTFILE="${REPO_ROOT}/Justfile"
    SANDBOX="${BATS_TEST_TMPDIR}/sandbox"
    BIN_DIR="${BATS_TEST_TMPDIR}/bin"
    ELEMENTS="${SANDBOX}/elements"
    OCI="${SANDBOX}/oci"
    LOG="${BATS_TEST_TMPDIR}/podman.log"
    REF_ELEMENT="oci/bluefin-server-ddi-flatcar-reference.bst"

    mkdir -p "$BIN_DIR" "$ELEMENTS" "$OCI"
    : > "$LOG"

    # The Justfile's top-level backtick assignments inspect
    # elements/freedesktop-sdk.bst. Copy it so loading the sandbox Justfile
    # behaves exactly like the real one.
    cp "${REPO_ROOT}/elements/freedesktop-sdk.bst" "${ELEMENTS}/"

    make_stub podman 0
}

# make_stub <name> <exit-code>
make_stub() {
    cat > "${BIN_DIR}/$1" <<EOF
#!/usr/bin/env bash
echo "$1 \$*" >> "${LOG}"
exit $2
EOF
    chmod +x "${BIN_DIR}/$1"
}

# run_build [os-base] -- invoke `just build-ddi` with the given base.
run_build() {
    local base="${1:-}"
    if [ -n "${base}" ]; then
        run env PATH="${BIN_DIR}:${PATH}" \
            just --justfile "${JUSTFILE}" \
                 --working-directory "${REPO_ROOT}" \
                 build-ddi "${base}"
    else
        run env PATH="${BIN_DIR}:${PATH}" \
            just --justfile "${JUSTFILE}" \
                 --working-directory "${REPO_ROOT}" \
                 build-ddi
    fi
}

# The fsdk element is the shipped base; the flatcar-reference route must never
# select it, and vice versa.
assert_builds() {
    local element="$1"
    if ! grep -qF "${element}" "${LOG}"; then
        echo "expected podman call to build ${element}" >&2
        echo "---- podman log ----" >&2
        cat "${LOG}" >&2
        return 1
    fi
}

assert_does_not_build() {
    local element="$1"
    if grep -qF "${element}" "${LOG}"; then
        echo "expected podman call NOT to build ${element}" >&2
        cat "${LOG}" >&2
        return 1
    fi
}

assert_no_build() {
    refute_log "bst"
}

refute_log() {
    if grep -qF -- "$1" "${LOG}" 2>/dev/null; then
        echo "expected log NOT to contain: $1" >&2
        cat "${LOG}" >&2
        return 1
    fi
}

# --- guard shape ------------------------------------------------------------

@test "build-ddi still declares the OS_BASE parameter defaulting to fsdk" {
    grep -qF 'build-ddi OS_BASE="fsdk"' "${JUSTFILE}"
}

@test "build-ddi still validates os-base against fsdk and flatcar-reference" {
    grep -qF "expected 'fsdk' or 'flatcar-reference'" "${JUSTFILE}"
}

@test "build-ddi still guards the flatcar-reference element's existence" {
    grep -qF "os-base=flatcar-reference requires the imported Flatcar reference tree" "${JUSTFILE}"
}

# --- routing ----------------------------------------------------------------

@test "build-ddi with no argument builds the fsdk payload" {
    run_build
    [ "$status" -eq 0 ]
    assert_builds "oci/bluefin-server-ddi.bst"
    assert_does_not_build "${REF_ELEMENT}"
}

@test "build-ddi os-base=fsdk builds the fsdk payload" {
    run_build "fsdk"
    [ "$status" -eq 0 ]
    assert_builds "oci/bluefin-server-ddi.bst"
    assert_does_not_build "${REF_ELEMENT}"
}

@test "build-ddi os-base=flatcar-reference refuses before the element exists" {
    # The guard must resolve the element against the project's element-path
    # (project.conf: element-path: elements), so a stray copy at a bare
    # oci/ path must not satisfy it. Run against a sandbox that has the
    # decoy but not elements/oci/, so this stays a refusal test after the
    # #126 element lands in the repo.
    touch "${OCI}/bluefin-server-ddi-flatcar-reference.bst"
    run env PATH="${BIN_DIR}:${PATH}" \
        just --justfile "${JUSTFILE}" \
             --working-directory "${SANDBOX}" \
             build-ddi flatcar-reference
    [ "$status" -ne 0 ]
    [[ "$output" == *"projectbluefin/server#126"* ]]
    assert_no_build
}

@test "build-ddi rejects an unknown os-base" {
    run_build "not-a-base"
    [ "$status" -ne 0 ]
    [[ "$output" == *"unknown os-base"* ]]
    assert_no_build
}
