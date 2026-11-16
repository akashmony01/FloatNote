#!/usr/bin/env bash
# Build floatnote_<version>_all.deb from a built wheel.
#
#   packaging/build-deb.sh VERSION path/to/floatnote-VERSION-py3-none-any.whl OUT_DIR
#
# The package ships the wheel; its postinst creates /usr/lib/floatnote/venv
# (using Ubuntu's python3-gi for GTK) and installs FloatNote's Python libraries
# into it from PyPI. Per-user setup (shortcuts, guide) happens on first start.
set -euo pipefail

VERSION=$1
WHEEL=$2
OUT=$3
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(mktemp -d)"
chmod 755 "$ROOT"   # mktemp makes it 0700; the package root must be 0755
trap 'rm -rf "$ROOT"' EXIT

install -d "$ROOT/DEBIAN" "$ROOT/usr/lib/floatnote" "$ROOT/usr/bin" \
    "$ROOT/usr/share/applications" "$ROOT/etc/xdg/autostart" "$ROOT/usr/share/doc/floatnote"

install -m 644 "$WHEEL" "$ROOT/usr/lib/floatnote/"

cat > "$ROOT/usr/bin/floatnote" <<'EOF'
#!/bin/sh
APP=/usr/lib/floatnote/venv/bin/floatnote
if [ ! -x "$APP" ]; then  # postinst couldn't finish (e.g. offline): say so instead of failing silently
    msg="FloatNote isn't set up completely. Run: sudo dpkg --configure -a"
    echo "$msg" >&2
    command -v notify-send >/dev/null && notify-send -i dialog-error FloatNote "$msg"
    exit 1
fi
exec "$APP" "$@"
EOF
chmod 755 "$ROOT/usr/bin/floatnote"

cat > "$ROOT/usr/share/applications/floatnote.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=FloatNote
Comment=Hold a key, talk, get a bug list for Claude Code
Exec=/usr/bin/floatnote show
Icon=audio-input-microphone
Categories=Utility;Development;
Keywords=voice;notes;bugs;dictation;claude;
StartupNotify=false
EOF

cat > "$ROOT/etc/xdg/autostart/floatnote.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=FloatNote
Comment=Hold a key, talk, get a bug list for Claude Code
Exec=/usr/bin/floatnote daemon --login
Icon=audio-input-microphone
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
chmod 644 "$ROOT"/usr/share/applications/*.desktop "$ROOT"/etc/xdg/autostart/*.desktop

install -m 644 "$HERE/../LICENSE" "$ROOT/usr/share/doc/floatnote/copyright"

install -m 755 "$HERE/debian/postinst" "$HERE/debian/postrm" "$ROOT/DEBIAN/"
echo "/etc/xdg/autostart/floatnote.desktop" > "$ROOT/DEBIAN/conffiles"

SIZE_KB=$(du -sk --exclude=DEBIAN "$ROOT" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE_KB/" "$HERE/debian/control" > "$ROOT/DEBIAN/control"

mkdir -p "$OUT"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT/floatnote_${VERSION}_all.deb"
