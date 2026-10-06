#!/usr/bin/env bash
# Sign a per-node Ignition config the way a node verifies it: a binary
# detached OpenPGP signature over exactly the bytes served as bluefin-node.ign,
# made with the Ignition config key (never the release key that signs
# SHA256SUMS). Serve the result as bluefin-node.ign.gpg next to the config.
#
#   sign-node-config.sh <secret key (.asc)> <config> [<signature>]
#                                       (default signature: <config>.gpg)
#
# The key is imported into a throwaway GNUPGHOME, so no keyring is touched.
# The rules a node applies: docs/skills/booty-integration.md.
set -euo pipefail

key="${1:?usage: $0 <secret key> <config> [<signature>]}"
config="${2:?usage: $0 <secret key> <config> [<signature>]}"
sig="${3:-${config}.gpg}"

home="$(mktemp -d)"
trap 'rm -rf "${home}"' EXIT
GNUPGHOME="${home}" gpg --batch --quiet --import "${key}"
GNUPGHOME="${home}" gpg --batch --yes --pinentry-mode loopback --passphrase '' \
    --detach-sign --output "${sig}" "${config}"
GNUPGHOME="${home}" gpg --batch --verify "${sig}" "${config}"
