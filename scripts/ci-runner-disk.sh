#!/usr/bin/env bash
# Put podman's container storage and BuildStream's cache on the GitHub
# runner's large /mnt disk; the root disk cannot hold a kernel build (15 GB)
# next to the bst2 image.
#
#   bash scripts/ci-runner-disk.sh
#
# CI_RUNNER_MNT overrides /mnt (tests). Safe to run more than once: `ln -sfn`
# replaces the cache symlink instead of creating a link inside the directory
# it points to.
set -euo pipefail

mnt="${CI_RUNNER_MNT:-/mnt}"
uid="$(id -u)"

sudo mkdir -p "${mnt}/podman" "${mnt}/buildstream"
sudo chown -R "${uid}:$(id -g)" "${mnt}/podman" "${mnt}/buildstream"

mkdir -p "${HOME}/.config/containers"
cat > "${HOME}/.config/containers/storage.conf" <<EOF
[storage]
driver = "overlay"
runroot = "/run/user/${uid}"
graphroot = "${mnt}/podman"
EOF

mkdir -p "${HOME}/.cache"
ln -sfn "${mnt}/buildstream" "${HOME}/.cache/buildstream"
