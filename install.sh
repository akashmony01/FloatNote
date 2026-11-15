#!/usr/bin/env bash
# Install FloatNote for the current user.
#
#   ./install.sh              install or update
#   ./install.sh --uninstall  remove the app (keeps your notes)
#
# Installs into ~/.local/share/floatnote/venv, adds ~/.local/bin/floatnote,
# a login autostart entry and an app-menu entry, and downloads the speech
# models. Works with apt (Ubuntu, Debian, Mint), dnf (Fedora), pacman (Arch)
# and zypper (openSUSE); on GNOME, KDE Plasma, Cinnamon and XFCE.
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
    rm -rf "$VENV" "$DATA/models"
    say "Removed. Your notes are still in $DATA (delete that folder to remove them)."
    exit 0
fi

# What FloatNote needs, per package manager (keep in sync with distro.py).
if command -v apt-get >/dev/null; then
    PM=apt;    PKGS=(libportaudio2 python3-venv python3-gi gir1.2-gtk-3.0 wl-clipboard xclip pipewire-bin)
elif command -v dnf >/dev/null || [ -e /run/ostree-booted ]; then
    PM=dnf;    PKGS=(portaudio python3-gobject gtk3 wl-clipboard xclip pipewire-utils)
elif command -v pacman >/dev/null; then
    PM=pacman; PKGS=(portaudio python-gobject gtk3 wl-clipboard xclip pipewire)
elif command -v zypper >/dev/null; then
    PM=zypper; PKGS=(libportaudio2 python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-3_0 wl-clipboard xclip pipewire-tools)
else
    PM=""; PKGS=()
fi

installed() {
    case "$PM" in
        apt) dpkg -s "$1" >/dev/null 2>&1 ;;
        dnf|zypper) rpm -q "$1" >/dev/null 2>&1 ;;
        pacman) pacman -Q "$1" >/dev/null 2>&1 ;;
    esac
}

say "Checking system packages"
if [ -z "$PM" ]; then
    echo "Unknown package manager. Make sure these are installed: PortAudio, PyGObject with GTK 3,"
    echo "python3 venv, wl-clipboard, xclip and pw-play (PipeWire). Continuing."
else
    missing=()
    for pkg in "${PKGS[@]}"; do installed "$pkg" || missing+=("$pkg"); done
    if [ ${#missing[@]} -gt 0 ] && [ -z "${FLOATNOTE_SKIP_PACKAGES:-${FLOATNOTE_SKIP_APT:-}}" ]; then
        echo "Need: ${missing[*]}"
        if [ -e /run/ostree-booted ]; then
            echo "This is an image-based system (e.g. Fedora Silverblue/Kinoite). Run:"
            echo "  sudo rpm-ostree install ${missing[*]}"
            echo "then reboot and run ./install.sh again."
            exit 1
        fi
        case "$PM" in
            apt) sudo apt-get install -y "${missing[@]}" ;;
            dnf) sudo dnf install -y "${missing[@]}" ;;
            pacman) sudo pacman -S --needed --noconfirm "${missing[@]}" ;;
            zypper) sudo zypper --non-interactive install "${missing[@]}" ;;
        esac
    fi
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

say "Keyboard access"
# On Fedora Silverblue/Kinoite the 'input' group is only in /usr/lib/group.
ADD_TO_INPUT_GROUP='if ! grep -q "^input:" /etc/group && [ -f /usr/lib/group ]; then grep "^input:" /usr/lib/group >> /etc/group; fi; usermod -aG input "$1"'
if id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
    echo "You're in the 'input' group: all of FloatNote's shortcuts work."
elif [ -t 0 ]; then
    echo "FloatNote reads its shortcuts straight from the keyboard (the same way on every desktop),"
    echo "which needs your user in the 'input' group. Any program you run could then read"
    echo "keystrokes; FloatNote only looks at its own shortcut keys and stores nothing you type."
    read -r -p "Add $USER to the 'input' group now? [Y/n] " answer
    if [ -z "$answer" ] || [ "${answer,,}" = "y" ]; then
        sudo sh -c "$ADD_TO_INPUT_GROUP" sh "$USER"
        echo "Done. FloatNote picks it up when it starts."
    else
        echo "Skipped. Open/close and next project still work through your desktop's shortcuts;"
        echo "turn the rest on later with 'Turn on…' in the FloatNote dropdown."
    fi
else
    echo "To turn on all shortcuts: sudo usermod -aG input $USER  (or 'Turn on…' in the dropdown)"
fi

say "Downloading the speech models (small.en and base.en, about 600 MB)"
if ! "$LAUNCHER" download-models 2>&1 | { grep -v HF_TOKEN || true; }; then  # pipefail: download's status
    echo "Couldn't download them now; FloatNote downloads them on first start (needs internet)."
fi

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
echo "Click the microphone in your panel (or press Ctrl+Super+Alt+N) to see your notes."
