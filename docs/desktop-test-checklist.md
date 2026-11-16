# Desktop test checklist (before a release)

Run this on each desktop: **KDE Plasma** (Fedora KDE), **GNOME** (Ubuntu, and Fedora Workstation
if possible), **Cinnamon** (Linux Mint) and **XFCE** (Xubuntu or Mint XFCE). VMs or live USBs are
fine; a live session needs `./install.sh`. Note the result next to each line, plus the output of
`floatnote doctor`.

## 1. Install

- [ ] Package (`.deb` on Ubuntu/Mint, `.rpm` on Fedora) or `./install.sh` installs without errors.
- [ ] The install output shows both speech models downloading (`small.en`, `base.en`).
- [ ] `floatnote doctor`: no FAIL. "Desktop" names the right desktop; "Model" shows a local folder.
- [ ] Opening FloatNote from the app menu shows the mic in the panel (GNOME: needs the AppIndicator extension).
- [ ] Settings → Speech: switching to `base.en` and back is instant (no "Downloading…").

## 2. With keyboard access (in the `input` group)

`floatnote doctor` → "Open/close: read from the keyboard".

- [ ] Hold Ctrl+Super, talk, let go: a bug appears. Hold Super+Alt: a to-do.
- [ ] Record a second bug while the first still says "Transcribing…": both show as rows ("Transcribing…", "Waiting…") and both become notes.
- [ ] Press Ctrl+Super+Alt, let go: bugs copied (icon flashes green).
- [ ] **Ctrl+Super+Alt+N** opens the dropdown; again closes it. It does *not* copy the bugs.
- [ ] **Ctrl+Super+Alt+P** switches project (tooltip / dropdown show the new one).
- [ ] Settings → Keys → change Open/close to e.g. Ctrl+Super+Alt+J: saved, J works, N doesn't.
- [ ] Same for Next project, and for one hold key. Put them back afterwards.
- [ ] The desktop's own shortcut settings do **not** list FloatNote (see README, "How shortcuts work").
- [ ] GNOME only, upgrading from 1.0: the old *FloatNote: open/close* custom shortcut is gone and
      Ctrl+Super+Alt+N opens the dropdown once (not open-then-close).

## 2b. Dictation and To-do

- [ ] A new install has no Dictation tab; Settings → General → Dictation on: the tab and the Keys row appear.
- [ ] Hold Ctrl+Alt, talk, let go: the icon turns purple, then a notification "Copied, paste it anywhere"
      with the start of the text. Paste into another app (e.g. a browser chat): it's the text.
- [ ] The notification closes by itself and doesn't stay in the desktop's notification history.
- [ ] The Dictation tab lists it with the time; ✎ edits, ⧉ copies again, 🗑 deletes; Clear history empties it.
- [ ] Settings → General → To-do list off: the To-do tab and Super+Alt stop working; on again: back.
- [ ] Upgrading from 1.2: old ideas are in the To-do tab, `todo.md` exists and `ideas.md` is gone.

## 2c. Nothing lost

- [ ] Record a long bug, then ⏻ → Restart while it says "Transcribing…": after the restart the note appears.
- [ ] Same with ⏻ → Quit, then start FloatNote from the menu: the note appears.
- [ ] After ⏻ → Quit, Ctrl+Super+Alt+N starts FloatNote and opens the dropdown (keyboard-access mode).
      After that start the desktop's shortcut settings no longer list FloatNote.

## 3. Without keyboard access

Remove the group (`sudo gpasswd -d $USER input`), log out and in, start FloatNote.
`floatnote doctor` → "Open/close: registered with <desktop>".

- [ ] The dropdown shows the "Turn on…" bar.
- [ ] Ctrl+Super+Alt+N and Ctrl+Super+Alt+P work (through the desktop).
- [ ] The desktop's shortcut settings list *FloatNote: open/close* and *FloatNote: next project*.
- [ ] Settings → Keys: the hold/copy rows are greyed out with a hint; changing Open/close by
      pressing keys in the dropdown works, and the new keys work straight away.
- [ ] Press **Turn on…**, enter the password: FloatNote restarts, doctor says "read from the
      keyboard", and the desktop's shortcut settings no longer list FloatNote.

## 4. Dropdown position

- [ ] Click the panel icon: the dropdown opens next to it, against the panel, fully on screen.
- [ ] Move the panel to another side (KDE: panel edit mode; Cinnamon: panel settings), click again.
- [ ] Ctrl+Super+Alt+N: opens in the corner by the panel.
- [ ] ⤢ (make bigger / smaller): it stays against the panel.
- [ ] Clicking elsewhere or Esc closes it.

## 5. Panel icon

- [ ] Icon colours: red while recording a bug, blue for an idea, yellow while transcribing, green after copy.
- [ ] Hovering shows "FloatNote: <project>".
- [ ] GNOME: the project name shows next to the icon. KDE, Cinnamon, XFCE: the project's two letters
      show as a badge on the mic (in the state's colour) and change when you switch project.
      With General active there's no name or badge.
- [ ] ⏻ → Restart FloatNote: the icon disappears and comes back within a few seconds. ⏻ → Quit FloatNote: it closes.
- [ ] Ideas: the copy button on an idea copies just that idea; it stays in the list.
      Settings → General → "Show the project on the panel icon" hides either.

## 6. Uninstall

- [ ] `floatnote setup-shortcuts --remove`, then `sudo apt remove floatnote` / `sudo dnf remove floatnote`,
      or `./install.sh --uninstall`:
      `/usr/lib/floatnote` (packages) or `~/.local/share/floatnote/models` (script) is gone;
      notes in `~/.local/share/floatnote/floatnote.db` are kept.
- [ ] No FloatNote entries left in the desktop's shortcut settings.
