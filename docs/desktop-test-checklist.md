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

- [ ] Hold Ctrl+Super, talk, let go: a bug appears. Hold Super+Alt: an idea.
- [ ] Press Ctrl+Super+Alt, let go: bugs copied (icon flashes green).
- [ ] **Ctrl+Super+Alt+N** opens the dropdown; again closes it. It does *not* copy the bugs.
- [ ] **Ctrl+Super+Alt+P** switches project (tooltip / dropdown show the new one).
- [ ] Settings → Keys → change Open/close to e.g. Ctrl+Super+Alt+J: saved, J works, N doesn't.
- [ ] Same for Next project, and for one hold key. Put them back afterwards.
- [ ] The desktop's own shortcut settings do **not** list FloatNote (see README, "How shortcuts work").
- [ ] GNOME only, upgrading from 1.0: the old *FloatNote: open/close* custom shortcut is gone and
      Ctrl+Super+Alt+N opens the dropdown once (not open-then-close).

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
- [ ] GNOME: the project name shows next to the icon (Settings → General switch hides it).

## 6. Uninstall

- [ ] `floatnote setup-shortcuts --remove`, then `sudo apt remove floatnote` / `sudo dnf remove floatnote`,
      or `./install.sh --uninstall`:
      `/usr/lib/floatnote` (packages) or `~/.local/share/floatnote/models` (script) is gone;
      notes in `~/.local/share/floatnote/floatnote.db` are kept.
- [ ] No FloatNote entries left in the desktop's shortcut settings.
