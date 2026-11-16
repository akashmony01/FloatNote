# Changelog

All notable changes to FloatNote. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-11-16

### Added
- **The active project is shown on the panel icon on every desktop.** KDE, Cinnamon and XFCE can't show text next to tray icons, so there the project's first two letters (e.g. "CW" for *Client website*) are drawn in purple next to a slimmer mic inside the icon; the mic keeps its state colours. GNOME keeps the name next to the icon. Settings → General → "Show the project on the panel icon" turns it off.

### Fixed
- The empty Bugs and Ideas lists and the Copy all tooltip named the default keys (Ctrl+Super, Super+Alt, Ctrl+Super+Alt) even after you changed them; they now show your keys, like the guide.
- The "install didn't finish" messages now give a reinstall command that works (with the download URL).
- **Upgrading the .rpm failed** ("Cannot install floatnote 1.1.0 … and floatnote 1.1.1"): on an upgrade the new install script runs while the old version's files are still there, and it picked up both versions' wheels. The packages now install their own version by exact name. (After a failed upgrade, `sudo dnf reinstall https://github.com/akashmony01/FloatNote/releases/latest/download/floatnote.rpm` finishes the install; plain `dnf reinstall floatnote` can't, because the package came from a URL, not a repository.)

## [1.1.1] - 2026-11-16

### Fixed
- **Installing failed on Fedora 45** (Python 3.15): the package tried to compile PyAV and gave up, leaving FloatNote in the app menu but unable to start. PyAV is no longer held back to an old version (FloatNote now reads its own recordings, so any version works), and onnxruntime, which has no Python 3.15 build yet, is no longer required. Without it, faster-whisper's silence filter is simply off; `floatnote doctor` says so.
- Installing never compiles anything any more: the packages only use ready-made Python wheels, so a missing build tool can't break an install halfway.
- If an install couldn't finish, opening FloatNote now shows a notification saying how to fix it, instead of doing nothing. The install error no longer blames your internet connection when the network was fine.

## [1.1.0] - 2026-11-16

FloatNote now works on **GNOME, KDE Plasma, Cinnamon (Linux Mint) and XFCE**, and installs on Fedora, Arch and openSUSE as well as Ubuntu/Debian/Mint.

### Fixed
- **Open/close (Ctrl+Super+Alt+N) and next project (Ctrl+Super+Alt+P) didn't work outside GNOME**, and changing any shortcut in Settings failed with "Couldn't change the GNOME shortcut". They were GNOME custom shortcuts, which other desktops ignore.

### Changed
- **All shortcuts are read from the keyboard**, the same way hold-to-record already was, so they work identically on every desktop. FloatNote 1.0's GNOME shortcuts are removed automatically so nothing fires twice.
- **Without keyboard access**, open/close and next project are registered with the desktop instead (GNOME, KDE, Cinnamon or XFCE shortcut settings). FloatNote picks the right way by itself at every start. In Settings → Keys those two can then be changed by pressing the keys in the dropdown; the hold keys wait for keyboard access.
- **The dropdown opens next to the panel icon**, on whichever side the panel is (KDE and Mint have it at the bottom), instead of always in the top-right corner. Opened with the shortcut, it goes to the corner by the panel.
- **Both speech models (`small.en` and `base.en`) are downloaded during installation**, so FloatNote is ready on first start and switching models is instant. Packages keep them in `/usr/lib/floatnote/models` (removed on uninstall), `install.sh` in `~/.local/share/floatnote/models`. If the download fails, FloatNote downloads on first start. New command: `floatnote download-models`.
- The panel icon's tooltip names the active project (KDE and XFCE don't show text next to tray icons).
- Messages, the guide, `floatnote doctor` and the README no longer assume GNOME or Ubuntu; `doctor` shows the desktop and how open/close is handled, and names install commands for your distribution.
- The `.deb` no longer pulls in the GNOME AppIndicator extension on other desktops (it's suggested instead).

### Added
- **`.rpm` package** for Fedora and openSUSE.
- **`install.sh` supports dnf, pacman and zypper** besides apt, and tells Fedora Silverblue/Kinoite users what to add with `rpm-ostree`.
- "Turn on…" (keyboard access) also works on Fedora Silverblue/Kinoite, where the `input` group isn't in `/etc/group`.

## [1.0.1] - 2026-11-14

### Fixed
- **"Make smaller" now shrinks the width too.** After the dropdown had been large, text in the "Type a bug" box, a note being edited, or the Copy heading kept it wide, so only the height shrank and the dropdown could hang past the right edge of the screen.
- The dropdown also stays flush with the top-right corner after changing size.

## [1.0.0] - 2026-11-13

First public release.

### Added
- **Hold-to-record**: hold Ctrl+Super to record a bug, Super+Alt to record an idea; let go to stop. Pressing any other key while holding throws the recording away, so normal shortcuts never record by accident.
- **Offline speech to text** with faster-whisper (`small.en` by default, `base.en` for speed). Nothing leaves your computer.
- **Top-bar icon** that shows what's happening (grey ready, red bug, blue idea, yellow transcribing, green copied) and the active project's name.
- **Dropdown** under the icon (double-click the icon or Ctrl+Super+Alt+N) with **Bugs**, **Ideas** and **Projects** tabs, a compact and a large size.
- **Copy all** (press Ctrl+Super+Alt and let go): copies the active project's bugs as a numbered list with your own heading, ready to paste into Claude Code. Undo brings a copied batch back.
- **Projects**: a separate bug list per app you test; switch from the dropdown or with Ctrl+Super+Alt+P; link a code folder so `floatnote list` there picks the right project.
- **Claude Code integration**: `floatnote list` / `floatnote list --take` print (and optionally clear) a project's bugs for Claude Code to read.
- **Word fixes**: teach FloatNote names it mishears ("whitetail" → "Wagtail"); it offers a fix when you correct a note.
- **Settings** with Keys (change any shortcut by pressing it), Copy (heading with live preview), Speech, Words and General tabs, plus a short built-in guide.
- Type notes by hand, edit notes in place, move bugs to ideas, tick ideas done; ideas are also exported to `ideas.md`.
- **Ubuntu package** (`floatnote_1.0.0_all.deb`): `sudo apt install ./floatnote_1.0.0_all.deb`, then open FloatNote; shortcuts are set up on first start and hold-to-record is turned on from the app with a password prompt.
- `install.sh` as an alternative (per-user install from the source bundle); `floatnote doctor` checks the setup.
- Privacy by default: notes stay on your computer, files are private to your user, the log never contains note text, and recordings are not kept.

[1.2.0]: https://github.com/akashmony01/FloatNote/releases/tag/v1.2.0
[1.1.1]: https://github.com/akashmony01/FloatNote/releases/tag/v1.1.1
[1.1.0]: https://github.com/akashmony01/FloatNote/releases/tag/v1.1.0
[1.0.1]: https://github.com/akashmony01/FloatNote/releases/tag/v1.0.1
[1.0.0]: https://github.com/akashmony01/FloatNote/releases/tag/v1.0.0
