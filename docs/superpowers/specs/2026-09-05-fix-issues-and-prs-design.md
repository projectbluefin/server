# Fix Issues and PRs Design

## Problem & Context

Multiple PRs were recently merged to `main` (#29, #34, #36, #37, #38, #40, #41) addressing various security and architectural issues, but several issues remain open that have already been resolved. In addition, an unparseable heredoc in `files/os/justfile` renders `just k8s` broken on shipped images (#44), while PR #45 adds a 20-case BATS test suite reproducing it. Furthermore, unit tests in `tests/unit/` lack a CI runner (#42, #33), and PR #18 (least-privilege build workflow, closing #15) is ready to merge.

## Goals

1. **Close already-resolved issues**: Cleanly close issues #19, #28, #31, and #39 with explanatory comments citing the commits that fixed them.
2. **Fix `files/os/justfile` k8s recipe**:
   - Fix syntax defect (#44): replace column-0 heredoc with indentation-safe config writer.
   - Harden permissions (#43): ensure `/etc/rancher/k3s/config.yaml` is created with mode 0600.
3. **Incorporate PR #45 tests**:
   - Merge or apply `tests/unit/os-justfile_test.bats` and verify that all 20 BATS tests pass against the fixed recipe.
4. **Implement Unit Test CI (#42, #33)**:
   - Add `.github/workflows/unit-tests.yml` running both pytest and bats.
   - Add `just test-unit` recipe to `Justfile` for local parity.
5. **Merge PR #18 (closes #15)**:
   - Merge `ci/scope-workflow-permissions` into `main`.
   - Ensure all workflow and docs checks pass.

## Technical Details

### 1. `files/os/justfile` Fix

Replace:
```bash
    # 2. Setup Rancher configuration directory
    mkdir -p /etc/rancher/k3s

    # 3. Create config.yaml if it does not exist
    if [ ! -f /etc/rancher/k3s/config.yaml ]; then
        echo "==> Seeding neutral defaults for k3s role: {{ROLE}}"
        cat <<EOF > /etc/rancher/k3s/config.yaml
# Seeded by just k8s
write-kubeconfig-mode: "0600"
EOF
        if [ -n "{{TOKEN}}" ]; then
            echo "token: \"{{TOKEN}}\"" >> /etc/rancher/k3s/config.yaml
        fi
    fi
```

With indentation-safe, permission-hardened writing:
```bash
    # 2. Setup Rancher configuration directory
    install -d -m 0700 /etc/rancher/k3s

    # 3. Create config.yaml if it does not exist
    if [ ! -f /etc/rancher/k3s/config.yaml ]; then
        echo "==> Seeding neutral defaults for k3s role: {{ROLE}}"
        (
            umask 077
            printf '%s\n' '# Seeded by just k8s' 'write-kubeconfig-mode: "0600"' > /etc/rancher/k3s/config.yaml
            if [ -n "{{TOKEN}}" ]; then
                printf '%s\n' "token: \"{{TOKEN}}\"" >> /etc/rancher/k3s/config.yaml
            fi
        )
    fi
```

### 2. Unit Test CI Workflow (`.github/workflows/unit-tests.yml`)

Runs on `pull_request` and `push: [main]` with `contents: read`:
- Action checkout: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`
- Set up python: `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7`
- Install dependencies: `pytest pyyaml`
- Install `bats`: apt-get install -y bats
- Set up `just`: `taiki-e/install-action@b6b84cf49ebfe0176417bdce007c624f0db37f20 # v2`
- Run: `just test-unit`

### 3. Justfile `test-unit` Recipe

```just
# Run the unit test suite (pytest + bats)
[group('development')]
test-unit:
    python3 -m pytest tests/unit -q
    bats tests/unit
```

## Verification

1. `just --justfile files/os/justfile --summary` parses without errors.
2. `bats tests/unit/os-justfile_test.bats` runs and all 20 tests pass.
3. `just test-unit` runs pytest and bats cleanly.
4. `just validate` passes.
5. `python3 .github/scripts/docs-checks.py` passes.
