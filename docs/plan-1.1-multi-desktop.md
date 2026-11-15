# FloatNote 1.1.0: works on every mainstream Linux desktop

Status: **implemented, waiting for manual testing** (2026-11-16). Checklist:
[desktop-test-checklist.md](desktop-test-checklist.md).

Findings during implementation:
- KDE spike: registering a `.desktop` command with kglobalaccel over D-Bus (`doRegister` +
  `setShortcutKeys`, component `<file>.desktop`, action `_launch`) works without logout and
  `unregister` cleans up. KDE refuses a registration for a moment after a new `.desktop` file
  appears (empty reply), so all files are written first and a refused key is retried unless
  `globalShortcutsByKey` shows another owner.
- Placement: a work area can be cut on two sides (e.g. top panel + left dock), so the panel is
  taken from where the click landed; without a click a horizontal panel wins.

## Why

FloatNote 1.0 was built for Ubuntu GNOME. On Fedora KDE Plasma 6 (Wayland):

- Ctrl+Super+Alt+N (open/close) and Ctrl+Super+Alt+P (next project) do nothing.
- Changing any shortcut in Settings fails ("Couldn't change the GNOME shortcut").
- Recording and copying work.

Cause: open/close and next project are registered as **GNOME custom shortcuts via
gsettings** (`shortcuts.py`). The schema `org.gnome.settings-daemon.plugins.media-keys`
doesn't exist on KDE, so `gsettings` fails; `installed()` treats the failure as
"already set up", and `Daemon.set_keys()` aborts the save when `shortcuts.install()` raises.
Recording works because `hotkeys.py` reads `/dev/input` directly, independent of the desktop.

## Decisions

| Topic | Decision |
|---|---|
| Desktops supported | GNOME, KDE Plasma, Cinnamon (Mint), XFCE. Wayland and X11. |
| Open/close + next project | **Keyboard-direct** (read from `/dev/input` like recording) whenever FloatNote has keyboard access. |
| Without keyboard access | **Native fallback**: register the two shortcuts with the desktop (GNOME, KDE, Cinnamon, XFCE). |
| Switching between the two | **Automatic**, never both at once (double fire). Checked at every start and right after "Turn on…". |
| Old GNOME shortcuts on upgrade | Removed automatically when keyboard access is on. |
| Changing shortcuts without access | Open/close and next project: capture keys in the Settings window (GTK). Hold keys: locked with a "Turn on…" hint. |
| Dropdown position | Near the tray icon: use the click position and the panel's side. Opened by a shortcut, it goes to the corner next to the panel. |
| Project name in the panel | Next to the icon where supported (GNOME); always in the tooltip ("FloatNote: <project>"). |
| Install methods | `install.sh` for apt, dnf, pacman, zypper. Packages: `.deb` (keep) and new `.rpm`. Others use `install.sh`. |
| Speech models | Download **small.en and base.en at install time**. |
| Model location | Packages: `/usr/lib/floatnote/models` (shared, removed on uninstall). `install.sh`: `~/.local/share/floatnote/models`. Load order: system folder, user folder, Hugging Face cache (old installs). |
| Model download fails | Install succeeds with a warning; FloatNote downloads on first start with a visible progress message. |
| Testing | Unit tests with mocked desktop backends; live test on Fedora KDE; manual checklist for GNOME, Mint Cinnamon, XFCE (VMs / live USB). |
| Docs | Desktop-neutral wording; per-desktop requirements table; per-distro install commands. |
| Release | One release, **1.1.0**. |

## Plan

### 1. Keyboard-direct open/close and next project (`hotkeys.py`, `daemon.py`)

- Extend `ChordTracker` with **key gestures**: modifiers + one key (letter, digit, F-key,
  arrow). Fires on the key's *press* when exactly that combo's modifiers are held and no
  other key is down. Auto-repeat ignored. Pressing the key spoils the copy tap (already true).
- New actions `("key", "toggle")` / `("key", "next")`; the daemon handles them on the GTK
  main loop the same way the `floatnote show` / `next-project` commands do today.
- Track the extra key codes only for configured combos (keep the privacy rule: no logging).
- `set_keys("toggle"/"next")` updates the tracker instead of calling gsettings.
- Tests: key gesture fires once, not on repeat, not with extra modifiers, doesn't trigger
  copy, doesn't start a recording, works after a recording stops.

### 2. Shortcut backends for the fallback (`shortcuts.py` → `shortcuts/` package)

- `detect_desktop()` from `XDG_CURRENT_DESKTOP` (`GNOME`, `ubuntu:GNOME`, `KDE`,
  `X-Cinnamon`, `XFCE`), with `DESKTOP_SESSION` as backup.
- One small backend per desktop with `install(keys)`, `remove()`, `installed()`:
  - **GNOME**: existing gsettings media-keys code.
  - **Cinnamon**: gsettings `org.cinnamon.desktop.keybindings` `custom-list` plus
    `.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/<id>/`
    (`binding` is a string array).
  - **XFCE**: `xfconf-query -c xfce4-keyboard-shortcuts -p /commands/custom/<accel> -n -t string -s <cmd>`.
  - **KDE Plasma 6**: a `.desktop` file per command in `~/.local/share/applications/`,
    shortcut in `kglobalshortcutsrc` `[services][<file>.desktop] _launch=...`, then tell
    kglobalaccel over D-Bus. *Spike first*: confirm the exact registration path that
    takes effect without logging out.
- `sync(has_keyboard_access)` called at start and after "Turn on…":
  access → `remove()` everywhere it applies; no access → `install()` for the current desktop.
- Unknown desktop + no access: no global shortcuts; the dropdown says so.
- Every backend failure is logged and shown as a message; it never blocks saving a shortcut.
- `floatnote setup-shortcuts` keeps working (uses the detected backend).
- Tests: each backend's command lines with `subprocess` mocked; `sync` switching both ways.

### 3. Shortcut capture without keyboard access (`ui.py`)

- When the listener isn't available, Settings captures open/close and next project from
  the window's own `key-press-event`s (GTK). Esc cancels, same validation as now.
- Hold-key rows are disabled with "Turn on keyboard access to change these".

### 4. Keyboard access setup per distro (`ui.py`, `doctor.py`, `install.sh`)

- Same pkexec `usermod -aG input` flow. If the `input` group is only in `/usr/lib/group`
  (Fedora atomic), copy its line to `/etc/group` first.
- Messages name the right command for the detected distro.

### 5. Dropdown near the icon (`ui.py`, `tray.py`)

- Keep the last `Activate(x, y)`; find the panel side by comparing the monitor geometry
  with its work area (top/bottom/left/right).
- Click: open next to the click point, clamped to the work area, on the panel side.
- Shortcut: the corner on the panel side (top-right for a top panel, bottom-right for a bottom one).
- Re-snap logic (`_snap_right`) follows the chosen anchor instead of always the top-right.
- *Spike*: check what x/y KDE sends under XWayland with scaling.

### 6. Tray tooltip and messages (`tray.py`, `ui.py`)

- Tooltip title "FloatNote: <project>".
- "No icon host" warning names the right fix per desktop (GNOME: AppIndicator extension;
  XFCE: status notifier plugin).

### 7. Models at install time (`transcriber.py`, `config.py`, new `models.py`)

- `models.py`: `system_dir()`, `user_dir()`, `resolve(name)` → local path or the name
  (Hugging Face cache fallback); `download(names, dest)`.
- `Transcriber` loads from `resolve(name)`.
- New CLI `floatnote download-models [--dest DIR] [names…]` (default small.en, base.en).
- `.deb` postinst / `.rpm` %post: download into `/usr/lib/floatnote/models`; on failure warn,
  don't fail. postrm / %postun: remove the folder.
- `install.sh`: download both into `~/.local/share/floatnote/models`.
- First start with a missing model: download it with a visible progress message.
- Tests: `resolve` order, missing-model fallback.

### 8. Installer for apt, dnf, pacman, zypper (`install.sh`)

- Detect the package manager; map packages:

  | Need | apt | dnf | pacman | zypper |
  |---|---|---|---|---|
  | PortAudio | libportaudio2 | portaudio | portaudio | libportaudio2 |
  | venv | python3-venv | (built in) | (built in) | (built in) |
  | GObject | python3-gi | python3-gobject | python-gobject | python3-gobject |
  | GTK 3 typelib | gir1.2-gtk-3.0 | gtk3 | gtk3 | typelib-1_0-Gtk-3_0 |
  | Clipboard | wl-clipboard xclip | wl-clipboard xclip | wl-clipboard xclip | wl-clipboard xclip |
  | Sound | pipewire-bin | pipewire-utils | pipewire | pipewire-tools |

  (Verify each name during implementation.)
- Unknown package manager: print the list and continue.
- Desktop entries stay standard (`X-GNOME-Autostart-enabled` is harmless elsewhere).

### 9. `.rpm` package (`packaging/rpm/`, `.github/workflows/release.yml`)

- `floatnote.spec` mirroring the `.deb`: wheel in `/usr/lib/floatnote`, venv + models in `%post`.
- Built in a Fedora container in the release workflow; attached as `floatnote.rpm`.

### 10. Docs and wording

- README: requirements per desktop, install per distro, shortcut behaviour (keyboard-direct
  vs. fallback), dropdown placement.
- Replace "GNOME"/"top bar" in UI, doctor, CLI help with neutral wording.
- `doctor`: show desktop, session type, shortcut method in use, model location.
- CHANGELOG entry, version 1.1.0.

### 11. Verification

- `pytest` green; new tests above.
- Live on Fedora KDE Wayland: all five shortcuts, changing each, with and without input
  group (fallback), dropdown placement on a bottom panel, install.sh from scratch, rpm install.
- Manual checklist for GNOME (Ubuntu), Cinnamon (Mint), XFCE: written as
  `docs/desktop-test-checklist.md`.

## Order of work

1 → 2 (with the KDE spike) → 3 → 4 → 7 → 8 → 5 (with its spike) → 6 → 9 → 10 → 11.
Step 1 alone already fixes the bugs on this machine.

## Local note (this machine)

`~/.local/bin/floatnote` points to the old checkout in `~/Documents/FloatNote`, which no
longer exists. Re-run `./install.sh` after step 8, or re-point the link.
