#!/bin/bash
# First-boot generator for the KubeStellar postgres superuser password.
#
# The postgres StatefulSet (20-postgres.yaml) reads its superuser password from
# the kubeflex-postgres Secret via secretKeyRef. This script creates that Secret
# once, with a random password, so no usable credential is committed to git or
# exposed in the pod spec (see projectbluefin/server#98).
#
# Idempotent: the password is generated only if the Secret already exists, so
# the initialized database stays accessible across re-boots. Run once per boot
# by k0s-first-boot.service, before k0s applies the manifests (its 15- name
# sorts before 20-postgres.yaml, so the Secret exists first).
set -euo pipefail

manifest_dir="${KUBEFLEX_MANIFEST_DIR:-/var/lib/k0s/manifests/kubestellar}"
secret_file="$manifest_dir/15-kubeflex-postgres-secret.yaml"

if [ -e "$secret_file" ]; then
  exit 0
fi

mkdir -p "$manifest_dir"
password="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-30)"

cat > "$secret_file" <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: kubeflex-postgres
  namespace: kubeflex-system
type: Opaque
stringData:
  password: "$password"
EOF

chmod 0600 "$secret_file"
