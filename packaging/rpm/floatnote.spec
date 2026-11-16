# Built by packaging/build-rpm.sh (which passes version and the source files).
# One package for Fedora and openSUSE: the "or" dependencies cover both names.
Name:           floatnote
Version:        %{fn_version}
Release:        1
Summary:        Hold a key, talk, get a bug list for Claude Code
License:        MIT
URL:            https://github.com/akashmony01/FloatNote
BuildArch:      noarch
Source0:        floatnote-%{version}-py3-none-any.whl
Source1:        LICENSE

# The wheel is only shipped; %%post installs it into a venv. No automatic deps.
AutoReqProv:    no
Requires:       python3 >= 3.11
Requires:       python3-gobject
Requires:       (python3-gobject-Gdk if typelib-1_0-Gtk-3_0)
Requires:       (gtk3 or typelib-1_0-Gtk-3_0)
Requires:       (portaudio or libportaudio2)
Requires:       wl-clipboard
Requires:       xclip
Requires:       (pipewire-utils or pipewire-tools or pulseaudio-utils)
Requires:       polkit

%description
FloatNote records short voice notes while you test an app: hold Ctrl+Super,
describe the problem, let go. Speech is transcribed on your computer with
faster-whisper. When you're done, one key copies all notes as a numbered list
to paste into Claude Code, or Claude Code reads them with `floatnote list`.

Installing downloads FloatNote's Python libraries from PyPI into
/usr/lib/floatnote/venv and the speech models (~600 MB) into
/usr/lib/floatnote/models. Works with GNOME, KDE Plasma, Cinnamon and XFCE.

%prep

%build

%install
install -d %{buildroot}/usr/lib/floatnote %{buildroot}%{_bindir} \
    %{buildroot}%{_datadir}/applications %{buildroot}%{_sysconfdir}/xdg/autostart
install -m 644 %{SOURCE0} %{buildroot}/usr/lib/floatnote/

cat > %{buildroot}%{_bindir}/floatnote <<'EOF2'
#!/bin/sh
APP=/usr/lib/floatnote/venv/bin/floatnote
if [ ! -x "$APP" ]; then  # the install script couldn't finish (e.g. offline): say so, don't fail silently
    # Installed from a URL, so dnf has no copy of its own: reinstall from the URL.
    msg="FloatNote isn't set up completely. Run: sudo dnf reinstall https://github.com/akashmony01/FloatNote/releases/latest/download/floatnote.rpm"
    echo "$msg" >&2
    command -v notify-send >/dev/null && notify-send -i dialog-error FloatNote "$msg"
    exit 1
fi
exec "$APP" "$@"
EOF2
chmod 755 %{buildroot}%{_bindir}/floatnote

cat > %{buildroot}%{_datadir}/applications/floatnote.desktop <<'EOF2'
[Desktop Entry]
Type=Application
Name=FloatNote
Comment=Hold a key, talk, get a bug list for Claude Code
Exec=/usr/bin/floatnote show
Icon=audio-input-microphone
Categories=Utility;Development;
Keywords=voice;notes;bugs;dictation;claude;
StartupNotify=false
EOF2

cat > %{buildroot}%{_sysconfdir}/xdg/autostart/floatnote.desktop <<'EOF2'
[Desktop Entry]
Type=Application
Name=FloatNote
Comment=Hold a key, talk, get a bug list for Claude Code
Exec=/usr/bin/floatnote daemon --login
Icon=audio-input-microphone
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF2

install -d %{buildroot}%{_licensedir}/%{name}
install -m 644 %{SOURCE1} %{buildroot}%{_licensedir}/%{name}/LICENSE

%post
APP=/usr/lib/floatnote
echo "FloatNote: installing its Python libraries (about 250 MB to download)..."
rm -rf "$APP/venv"
# --system-site-packages: GTK comes from the system's python3-gobject.
python3 -m venv --system-site-packages "$APP/venv"
# --only-binary: ready-made wheels only, never compile anything here.
# faster-whisper --no-deps: its onnxruntime isn't built for every Python yet
# (e.g. Fedora 45's 3.15; see pyproject.toml); a no-op where it's installed.
FASTER_WHISPER="faster-whisper>=1.1,<2"  # same range as pyproject.toml
PIP="$APP/venv/bin/pip install --quiet --disable-pip-version-check --no-input --only-binary=:all:"
# This version's wheel by name: on an upgrade %%post runs before the old
# version's files are removed, so a wildcard would match both wheels.
if ! $PIP "$APP/floatnote-%{version}-py3-none-any.whl" || ! $PIP --no-deps "$FASTER_WHISPER"; then
    rm -rf "$APP/venv"
    echo "FloatNote: couldn't install its Python libraries (see the error above)." >&2
    echo "If it was a network problem: sudo dnf reinstall https://github.com/akashmony01/FloatNote/releases/latest/download/floatnote.rpm" >&2
    echo "Otherwise please report it: https://github.com/akashmony01/FloatNote/issues" >&2
    exit 0
fi
echo "FloatNote: downloading the speech models (small.en and base.en, about 600 MB)..."
# Shared by every user. If it fails (offline), FloatNote downloads on first start.
"$APP/venv/bin/floatnote" download-models --system || true
echo
echo "FloatNote is installed. Open FloatNote from your apps: a microphone appears in your panel."

%postun
# $1 = 0: removed (not upgraded). The venv and models were made by %%post.
# Your notes (~/.local/share/floatnote) and settings (~/.config/floatnote) are kept.
if [ "$1" -eq 0 ]; then
    rm -rf /usr/lib/floatnote/venv /usr/lib/floatnote/models
    rmdir /usr/lib/floatnote 2>/dev/null || true
fi

%files
%license %{_licensedir}/%{name}/LICENSE
%dir /usr/lib/floatnote
/usr/lib/floatnote/floatnote-%{version}-py3-none-any.whl
%{_bindir}/floatnote
%{_datadir}/applications/floatnote.desktop
%config(noreplace) %{_sysconfdir}/xdg/autostart/floatnote.desktop

%changelog
* Mon Nov 16 2026 akashmony01 <akashmony01@users.noreply.github.com> - 1.1.0-1
- See CHANGELOG.md in the source: GNOME, KDE, Cinnamon and XFCE support, first RPM.
