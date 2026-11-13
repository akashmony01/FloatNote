# Changelog

All notable changes to FloatNote. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

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

[1.0.1]: https://github.com/akashmony01/FloatNote/releases/tag/v1.0.1
[1.0.0]: https://github.com/akashmony01/FloatNote/releases/tag/v1.0.0
