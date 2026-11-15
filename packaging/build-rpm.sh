#!/usr/bin/env bash
# Build floatnote-<version>-1.noarch.rpm from a built wheel (Fedora, openSUSE).
#
#   packaging/build-rpm.sh VERSION path/to/floatnote-VERSION-py3-none-any.whl OUT_DIR
#
# Needs rpmbuild (Fedora: sudo dnf install rpm-build). Like the .deb, the
# package ships the wheel; its %post creates /usr/lib/floatnote/venv and
# downloads the speech models.
set -euo pipefail

VERSION=$1
WHEEL=$2
OUT=$3
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOP="$(mktemp -d)"
trap 'rm -rf "$TOP"' EXIT

mkdir -p "$TOP/SOURCES" "$OUT"
cp "$WHEEL" "$HERE/../LICENSE" "$TOP/SOURCES/"
rpmbuild -bb --quiet \
    --define "_topdir $TOP" \
    --define "fn_version $VERSION" \
    "$HERE/rpm/floatnote.spec"
cp "$TOP"/RPMS/noarch/floatnote-"$VERSION"-1.noarch.rpm "$OUT/"
