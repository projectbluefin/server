# Fix Issues and PRs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve outstanding bugs and CI gaps across projectbluefin/server: close resolved issues, fix files/os/justfile syntax/permissions (#44, #43), add unit test CI (#42), and merge PR #18 (#15).

**Architecture:** Verify fixes locally using BATS and pytest test suites inside unprivileged user/mount namespaces, add a dedicated GitHub Actions workflow for unit test execution with least-privilege tokens, and merge completed PRs cleanly onto main.

**Tech Stack:** Bash, just, BATS, pytest, Python, GitHub Actions.

## Global Constraints

- Do not ship vendor defaults in `/etc`; `/etc` modifications in scripts are runtime/operator state.
- Keep GitHub Actions workflows pinned to verified immutable SHAs with least-privilege permissions (`contents: read`).
- Run `just validate` and `python3 .github/scripts/docs-checks.py` before every commit.
- Use Conventional Commits with Co-authored-by trailers.

---

### Task 1: Close Already-Resolved Issues (#19, #28, #31, #39)

**Files:**
- GitHub Issues: #19, #28, #31, #39

**Interfaces:**
- Consumes: Merged commits 459afece2 (#36), f78f7fe2 (#29), 5c44d2e4 (#34), f4f76302 (#40)
- Produces: Closed issues with reference comments linking each fix commit

- [ ] **Step 1: Comment and close issue #19**
Add comment linking commit `459afece2` (PR #36) repairing sysupdate keyring filename and shipping gnupg; close as completed.

- [ ] **Step 2: Comment and close issue #28**
Add comment linking commit `f78f7fe2` (PR #29) hardening sshd drop-in; close as completed.

- [ ] **Step 3: Comment and close issue #31**
Add comment linking commit `5c44d2e4` (PR #34) enforcing release-version invariant; close as completed.

- [ ] **Step 4: Comment and close issue #39**
Add comment linking commit `f4f76302` (PR #40) unifying architecture identity; close as completed.

---

### Task 2: Fix `files/os/justfile` Syntax and Permissions (#44, #43) with BATS Coverage (PR #45)

**Files:**
- Create: `tests/unit/os-justfile_test.bats` (from PR #45)
- Modify: `files/os/justfile`
- Test: `tests/unit/os-justfile_test.bats`

**Interfaces:**
- Consumes: BATS test suite from branch `quality/test-os-justfile-k8s`
- Produces: Parseable and secure `k8s` recipe in `files/os/justfile`

- [ ] **Step 1: Check out `tests/unit/os-justfile_test.bats` from PR #45**

```bash
git checkout origin/quality/test-os-justfile-k8s -- tests/unit/os-justfile_test.bats
```

- [ ] **Step 2: Run BATS test to verify parse failure reproduces**

Run: `bats tests/unit/os-justfile_test.bats`
Expected: 1 failure ("just --justfile files/os/justfile --summary parses successfully") and 18 skips.

- [ ] **Step 3: Apply indentation-safe config writer and 0600 permissions to `files/os/justfile`**

Replace lines 20-33 of `files/os/justfile`:
```just
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

- [ ] **Step 4: Run BATS suite to verify all 20 tests pass**

Run: `bats tests/unit/os-justfile_test.bats`
Expected: All 20 tests pass.

- [ ] **Step 5: Verify docs and element graph validation**

Run: `python3 .github/scripts/docs-checks.py && just validate`
Expected: PASS.

- [ ] **Step 6: Commit and close #44 and #43**

```bash
git add files/os/justfile tests/unit/os-justfile_test.bats
git commit -m "fix: repair files/os/justfile k8s recipe parseability and permissions (#44, #43)"
```

---

### Task 3: Add Unit Test CI Workflow and Justfile Target (#42, #33)

**Files:**
- Create: `.github/workflows/unit-tests.yml`
- Modify: `Justfile`

**Interfaces:**
- Consumes: `pytest`, `bats`, `.github/scripts/docs-checks.py`, `tests/unit/*.py`, `tests/unit/*.bats`
- Produces: GitHub Actions CI workflow running unit tests on PRs and main pushes; local `just test-unit` recipe

- [ ] **Step 1: Add `test-unit` recipe to `Justfile`**

In `Justfile`:
```just
# Run unit test suite (pytest + bats)
[group('development')]
test-unit:
    python3 -m pytest tests/unit -q
    bats tests/unit
```

- [ ] **Step 2: Create `.github/workflows/unit-tests.yml`**

Create `.github/workflows/unit-tests.yml` with SHA-pinned actions and `contents: read`:
```yaml
name: Unit tests

on:
  pull_request:
    paths:
      - '.github/scripts/**'
      - '.github/workflows/unit-tests.yml'
      - 'files/**'
      - 'tests/unit/**'
      - 'Justfile'
  push:
    branches: [main]
    paths:
      - '.github/scripts/**'
      - '.github/workflows/unit-tests.yml'
      - 'files/**'
      - 'tests/unit/**'
      - 'Justfile'

permissions:
  contents: read

jobs:
  unit:
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - name: Checkout repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1

      - name: Set up Python
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7
        with:
          python-version: '3.14'

      - name: Install dependencies
        run: |
          sudo apt-get update && sudo apt-get install -y bats
          pip install pytest pyyaml

      - name: Set up just
        uses: taiki-e/install-action@b6b84cf49ebfe0176417bdce007c624f0db37f20 # v2
        with:
          tool: just

      - name: Run unit tests
        run: just test-unit
```

- [ ] **Step 3: Run `just test-unit` locally**

Run: `just test-unit`
Expected: Pytest and all BATS test files pass cleanly.

- [ ] **Step 4: Verify docs and validation**

Run: `python3 .github/scripts/docs-checks.py && just validate`
Expected: PASS.

- [ ] **Step 5: Commit and close #42 and #33**

```bash
git add Justfile .github/workflows/unit-tests.yml
git commit -m "ci: add unit-tests workflow and Justfile test-unit recipe (#42, #33)"
```

---

### Task 4: Merge PR #18 for Least-Privilege CI (Closes #15)

**Files:**
- Modify: `.github/workflows/build.yml`
- Modify: `docs/skills/ci-tooling.md`

**Interfaces:**
- Consumes: Branch `origin/ci/scope-workflow-permissions`
- Produces: Least privilege build workflow with split track-refs, build, and release jobs

- [ ] **Step 1: Merge `origin/ci/scope-workflow-permissions`**

```bash
git merge --no-ff origin/ci/scope-workflow-permissions -m "Merge PR #18: ci: scope build workflow token to least privilege (closes #15)"
```

- [ ] **Step 2: Run validation suite**

Run: `just validate && python3 .github/scripts/docs-checks.py`
Expected: PASS.

- [ ] **Step 3: Close PR #18 and Issue #15**
Comment and close PR #18 as merged into main; close Issue #15 as completed.

---

### Task 5: Status Update on PXE Netboot PRs (#22, #25, #26, #27, #14)**

**Files:**
- GitHub Issues & PRs: #14, #22, #24, #25, #26, #27

- [ ] **Step 1: Comment on superseded PRs (#22, #25, #26)**
Note that standalone PXE artifact export was completed and merged in PR #23. Close superseded PRs if appropriate or label as superseded.
