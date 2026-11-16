# FloatNote 1.3 plan: Dictation, To-do, safety net

Agreed in the interview on 2026-11-16. FloatNote has one user, so upgrades may change
names and files freely (but existing notes are migrated, never lost).

## 1. Dictation (new, off by default)

- **Hold Ctrl+Alt**, talk, let go. The text is transcribed and **copied to the clipboard
  automatically**. A desktop notification says *"Copied, paste it anywhere"* with the first
  ~80 characters, and **closes itself after ~4 s** (marked transient, and it replaces the
  previous one, so notifications never pile up).
- No text-field detection, no simulated typing or auto-paste (maybe later).
- **History**: a *Dictation* tab with one shared list (not per project). It keeps the last
  **100** entries; older ones are deleted. Each row: edit in place, copy, delete. The footer
  has *Clear history*.
- Settings → General → *Dictation* switch (default **off**). Off: the Ctrl+Alt key does
  nothing and the tab is hidden. Settings → Keys gets a *Dictate* row.
- The panel icon turns **purple** while dictating.

## 2. Ideas → To-do (renamed everywhere)

- Tab, guide, Settings, messages, panel tooltip: *To-do*.
- Inside: note kind `idea` → `todo` (database migration), config `hold_idea` → `hold_todo`
  (old key read once and moved), CLI `toggle-idea` → `toggle-todo`, `floatnote list --ideas`
  → `--todos`, `ideas.md` → `todo.md` (old file removed), icon `floatnote-idea` →
  `floatnote-todo`.
- Settings → General → *To-do list* switch (default **on**). Off: its key does nothing and the
  tab is hidden. Bugs are always on.
- Each to-do keeps the copy button from 1.2.

## 3. Safety net: no note is ever lost

- Every recording waiting to be transcribed is saved in FloatNote's private data folder
  (`queue/`), and deleted once its note is saved. At start, FloatNote transcribes anything
  left there (after a crash, a restart, Quit with notes waiting, or the watchdog below).
- **Watchdog**: if one transcription takes longer than 60 s + 3× the recording's length,
  FloatNote says so, restarts itself, and picks the queue up again.
- The ⏻ menu no longer warns that notes will be lost; it says they'll finish after restart.

## 4. Waiting notes are visible

- Each waiting recording shows its own row in its own tab (Bugs, To-do or Dictation):
  *"Transcribing…"* for the one in progress, *"Waiting…"* for the others. Recording is
  never blocked.

## 5. Open/close works after Quit

- On **Quit** (not restart), when FloatNote reads the keyboard, it registers the open/close
  keys with the desktop (KDE, GNOME, Cinnamon, XFCE) to run `floatnote show`, which starts
  FloatNote and opens the dropdown. At the next start, the usual shortcut sync removes
  that registration again, so the keys never fire twice.
- Autostart at login already works (`/etc/xdg/autostart/floatnote.desktop`); no change.

## Tests

- Store migration idea → todo (and the CHECK constraint), dictation trimming to 100.
- Config migration `hold_idea` → `hold_todo`; key validation with four hold keys.
- Daemon: dictation copies + notifies, disabled kinds ignored, queue files written and
  removed, recovery at start, watchdog deadline.
- Quit registers the desktop shortcut only in keyboard mode.
- Manual: `docs/desktop-test-checklist.md` gets a Dictation / To-do section.

## Release

Version **1.3.0**. Local RPM first for testing; push and tag only after the user's go-ahead.
