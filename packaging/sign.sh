#!/usr/bin/env bash
# Podepíše SHA256SUMS vydání (dist/release/SHA256SUMS.asc) klíčem vydání.
# `repo-doctor update` podle tohoto podpisu ověřuje tarball před samoaktualizací.
#
# Volání: GNUPGHOME=<klíčenka s klíčem vydání> packaging/sign.sh
set -euo pipefail
cd "$(dirname "$0")/.."
fpr=$(sed -n 's/^FINGERPRINT = "\(.*\)"/\1/p' src/repo_doctor/update.py)
gpg --batch --yes --local-user "$fpr" --armor --detach-sign \
    --output dist/release/SHA256SUMS.asc dist/release/SHA256SUMS
gpg --batch --verify dist/release/SHA256SUMS.asc dist/release/SHA256SUMS
