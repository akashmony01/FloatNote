#!/usr/bin/env bash
# Install FloatNote for the current user.
#
#   ./install.sh              install or update
#   ./install.sh --uninstall  remove the app (keeps your notes)
#
# Installs into ~/.local/share/floatnote/venv, adds ~/.local/bin/floatnote,
# a login autostart entry, an app-menu entry and GNOME keyboard shortcuts.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/floatnote"
VENV="$DATA/venv"
BIN="$HOME/.local/bin"
LAUNCHER="$BIN/floatnote"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/floatnote.desktop"
APPENTRY="${XDG_DATA_HOME:-$HOME/.local/share}/applications/floatnote.desktop"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }

# The VS Code snap terminal leaks its own GTK/GIO paths; undo that for every
# command this script runs (gsettings and GTK break otherwise).
for var in $(env | sed -n 's/^\([A-Z_]*\)_VSCODE_SNAP_ORIG=.*/\1/p'); do
    orig="${var}_VSCODE_SNAP_ORIG"
    if [ -n "${!orig}" ]; then export "$var=${!orig}"; else unset "$var"; fi
    unset "$orig"
done

if [ "${1:-}" = "--uninstall" ]; then
    say "Stopping FloatNote"
    [ -x "$LAUNCHER" ] && "$LAUNCHER" quit >/dev/null 2>&1 || true
    [ -x "$LAUNCHER" ] && "$LAUNCHER" setup-shortcuts --remove || true
    rm -f "$LAUNCHER" "$AUTOSTART" "$APPENTRY"
    rm -rf "$VENV"
    say "Removed. Your notes are still in $DATA (delete that folder to remove them)."
    exit 0
fi

say "Checking system packages"
missing=()
for pkg in libportaudio2 python3-venv python3-gi gir1.2-gtk-3.0 wl-clipboard xclip pipewire-bin; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if [ ${#missing[@]} -gt 0 ] && [ -z "${FLOATNOTE_SKIP_APT:-}" ]; then
    echo "Need: ${missing[*]}"
    sudo apt-get install -y "${missing[@]}"
fi

say "Installing FloatNote into $VENV"
mkdir -p "$DATA" "$BIN"
[ -d "$VENV" ] || python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "$SRC"

cat > "$LAUNCHER" <<EOF
#!/bin/sh
exec "$VENV/bin/floatnote" "\$@"
EOF
chmod +x "$LAUNCHER"

say "Adding login autostart and app-menu entry"
mkdir -p "$(dirname "$AUTOSTART")" "$(dirname "$APPENTRY")"
cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=FloatNote
Comment=Hotkey voice notes for Claude Code
Exec="$LAUNCHER" daemon --login
Icon=audio-input-microphone
X-GNOME-Autostart-enabled=true
NoDisplay=true
EOF
cat > "$APPENTRY" <<EOF
[Desktop Entry]
Type=Application
Name=FloatNote
Comment=Hotkey voice notes for Claude Code
Exec="$LAUNCHER" show
Icon=audio-input-microphone
Categories=Utility;
StartupNotify=false
EOF

say "Setting up keyboard shortcuts"
"$LAUNCHER" setup-shortcuts --launcher "$LAUNCHER"

say "Hold-to-record"
if id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
    echo "You're in the 'input' group: hold Ctrl+Super (bug) or Super+Alt (idea) to record."
elif [ -t 0 ]; then
    echo "Hold-to-record reads the keyboard directly, which needs your user in the 'input' group."
    echo "(Any program you run could then read keystrokes. FloatNote only tracks modifier keys.)"
    read -r -p "Add $USER to the 'input' group now? [Y/n] " answer
    if [ -z "$answer" ] || [ "${answer,,}" = "y" ]; then
        sudo usermod -aG input "$USER"
        echo "Done. Log out and back in to turn hold-to-record on."
    fi
else
    echo "To turn on hold-to-record: sudo usermod -aG input $USER  (then log out and back in)"
fi

say "Downloading the speech model (first time only)"
"$VENV/bin/python" -c "
from floatnote import config
from faster_whisper.utils import download_model
download_model(config.load().model)
" 2>&1 | grep -v HF_TOKEN || true

say "Starting FloatNote"
"$LAUNCHER" quit >/dev/null 2>&1 || true
sleep 1
nohup "$LAUNCHER" daemon >/dev/null 2>&1 &
sleep 2

say "Checking"
"$LAUNCHER" doctor || true

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo; echo "Note: $BIN is not on your PATH; log out and in again, or use $LAUNCHER." ;;
esac
echo
echo "Done. Hold Ctrl+Super, describe a bug, let go. Press Ctrl+Super+Alt and let go to copy your bugs."
echo "Click the microphone in the top bar (or Ctrl+Super+Alt+N) to see your notes."
