> **Historical document.** This is the first design spec. Several decisions changed during development (top-bar dropdown instead of a floating window, hold-to-record keys, projects, Settings tabs). The [README](../README.md) describes how FloatNote works today.

# FloatNote — Version 1 Specification

Companion to `FloatNote Project Plan.md`. The plan says *why*; this file says *exactly what to build*. Decisions here were confirmed with the user on 2026-11-12.

> **Changes after first test (2026-11-12):** one window with Bugs/Ideas tabs replaces the separate panel and home screen; "Paste all" renamed "Copy all"; note editing uses a wrapping multi-line box; default model is now `small.en` beam 5 (base.en was too inaccurate); the last 20 recordings are kept for model comparison; new `floatnote model` command.

## 1. Target environment (verified)

| Item | Value |
|---|---|
| OS | Ubuntu 24.04 LTS |
| Desktop | GNOME 46, **Wayland** session |
| CPU / RAM / GPU | Intel i5-10400 (6C/12T), 15 GB, **no GPU** (Intel UHD 630) → CPU inference, int8 |
| Audio | PipeWire (+ pipewire-pulse), default mic: PCM2902 USB codec |
| Python | 3.12 |
| Available | GTK3 + GTK4 via PyGObject, `wl-copy`, `xclip`, AppIndicator extension enabled |

## 2. Confirmed decisions

| Topic | Decision |
|---|---|
| Window | Small always-on-top floating panel, run under XWayland (`GDK_BACKEND=x11`) so keep-above works. Must **not** steal focus. |
| Toolkit | GTK3 (PyGObject). |
| Hotkeys | Two record keys (bug, idea) + copy-all + show/hide, set in GNOME Settings → Keyboard → Custom Shortcuts. |
| Model | faster-whisper, CPU int8. Benchmark `small.en` vs `base.en` in build step 2; user picks; stored in config. |
| Copy all | Copies to clipboard, **archives** session notes (not deleted), offers undo. |
| Paste format | Intro line + numbered list (see §6). |
| Data | `~/.local/share/floatnote/` (DB, exports), `~/.config/floatnote/config.toml`. |
| V1 extras | Custom vocabulary, `floatnote list` CLI, start/stop sounds, login home screen. |

## 3. Components

```
GNOME shortcut ──► floatnote <cmd>  (thin CLI client)
                        │  Unix socket: $XDG_RUNTIME_DIR/floatnote.sock
                        ▼
                floatnoted (daemon, autostart)
                 ├─ Recorder   (sounddevice, 16 kHz mono)
                 ├─ Transcriber (faster-whisper, model loaded once, worker thread)
                 ├─ Store      (SQLite)
                 ├─ UI         (GTK3 floating panel + home screen)
                 └─ Feedback   (sounds via paplay/pw-play)
```

- One daemon process. The CLI only sends a JSON line over the socket and prints the reply. If the daemon isn't running, the CLI says so (exit code 1).
- Transcription runs off the GTK main thread; results are posted back with `GLib.idle_add`.
- A single instance is enforced by the socket.

## 4. CLI commands

| Command | Action |
|---|---|
| `floatnote toggle-bug` | Start/stop recording a session (bug) note |
| `floatnote toggle-idea` | Start/stop recording an idea note |
| `floatnote copy-all` | Copy session notes in paste format → clipboard, archive them (`paste-all` still accepted) |
| `floatnote undo` | Restore the last archived batch |
| `floatnote show` | Toggle floating panel visibility |
| `floatnote home` | Open the ideas home screen |
| `floatnote list [--ideas] [--json]` | Print current session notes (or open ideas) to stdout. **Works without the daemon** (reads SQLite directly) so Claude Code can run it. |
| `floatnote daemon` | Run the daemon (used by autostart) |

Suggested default shortcuts (user sets them in GNOME): `Super+Alt+B` bug, `Super+Alt+I` idea, `Super+Alt+P` copy-all, `Super+Alt+N` show.

## 5. Recording & transcription behaviour

- Toggle: first press starts, second press (of the same key) stops. Pressing the *other* record key while recording stops the current one and keeps its kind.
- Start: play start sound, panel shows a red "● Recording bug…" state with a timer.
- Stop: play stop sound, note appears immediately as "Transcribing…" placeholder, then fills with text.
- Discard recordings < 0.5 s (no note, short "cancelled" cue).
- Hard cap: 3 minutes (configurable), then auto-stop.
- faster-whisper settings: `language="en"`, `vad_filter=True`, `beam_size` default from benchmark, `initial_prompt` built from the vocabulary list.
- Empty result after VAD → no note, show "Nothing heard" briefly.
- Failure (no mic, model error) → error sound + message in panel, logged to `~/.local/share/floatnote/floatnote.log`.

## 6. Paste-all format

```
I tested the app and found these issues. Please fix them:

1. The navbar overlaps the hero image on mobile.
2. Submit button does nothing when the email is empty.
```

- Intro line is configurable in config.
- Order: oldest first.
- Empty list → nothing copied, panel shows "No notes".
- Clipboard: `wl-copy` (Wayland); fall back to `xclip -selection clipboard`.
- After copy: notes get `archived_at` + a shared `batch_id`; panel shows "Copied 5 notes · Undo" for ~10 s.

## 7. Data model (SQLite, `~/.local/share/floatnote/floatnote.db`)

```sql
CREATE TABLE notes (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('bug','idea')),
  text        TEXT NOT NULL,
  created_at  TEXT NOT NULL,          -- ISO 8601 local time
  updated_at  TEXT,
  done        INTEGER NOT NULL DEFAULT 0,   -- ideas
  archived_at TEXT,                   -- bugs: set by paste-all
  batch_id    TEXT,                   -- bugs: groups one paste-all
  duration_s  REAL                    -- audio length, for stats/debug
);
```

- Session notes = `kind='bug' AND archived_at IS NULL`.
- Open ideas = `kind='idea' AND done=0`.
- Audio is not stored in V1.
- After every idea change, also write `~/.local/share/floatnote/ideas.md` (plain readable export).
- WAL mode; schema version in `PRAGMA user_version` for later migrations.

## 8. Floating panel (GTK3)

- Size ~360×420, resizable, remembers position. Undecorated with a small drag handle, or a normal title bar if keep-above needs it.
- `set_keep_above(True)`, `set_accept_focus(False)` until the user clicks inside it (so the browser keeps focus while recording).
- Contents: status row (idle / recording / transcribing), list of session notes, footer buttons **Paste all**, **Clear**, **Ideas**.
- Each note: text; double-click to edit inline (Enter saves, Esc cancels); delete (✕) button; "→ Idea" to move it.
- Hidden by default on login; `floatnote show` toggles it. It auto-shows when recording starts (option, default on).

## 9. Home screen (ideas)

- Centered normal window, opened on login (option, default on) and by `floatnote home`.
- Lists open ideas, newest first, with date; checkbox marks done; edit/delete per item; "Show done" toggle.
- Only shown on login if there is at least one open idea.

## 10. Config (`~/.config/floatnote/config.toml`)

```toml
model = "base.en"            # set after benchmark
compute_type = "int8"
beam_size = 1               # set after benchmark
copy_intro = "I tested the app and found these issues. Please fix them:"
max_record_seconds = 180
sounds = true
show_panel_on_record = true
home_on_login = true
vocabulary = ["Claude Code", "Tailwind", "Supabase", "navbar", "useEffect", "API", "404"]
```

Created with defaults on first run. Read at daemon start (restart to apply in V1).

## 11. Install & autostart

- Install into a venv at `~/.local/share/floatnote/venv`; a `floatnote` launcher in `~/.local/bin`.
- Python deps: `faster-whisper`, `sounddevice`, `numpy`, `PyGObject` (use system `python3-gi` via `--system-site-packages` to avoid building it).
- System package needed: `sudo apt install libportaudio2` (not installed yet; `sounddevice` needs it).
- The user runs Claude Code inside the **VS Code snap** terminal, which leaks `GTK_PATH`, `GSETTINGS_SCHEMA_DIR`, `GIO_MODULE_DIR`, etc. Started from there, GTK crashes (`Settings schema ... does not contain a key named 'antialiasing'`). The `~/.local/bin/floatnote` launcher must clear these variables (restore the `*_VSCODE_SNAP_ORIG` values or unset them) before starting the daemon. Autostart at login is not affected.
- Autostart: `~/.config/autostart/floatnote.desktop` → `floatnote daemon`.
- Model download happens on first run (~75 MB base.en / ~250 MB small.en) with a visible "Downloading model…" status.
- `install.sh` does all of the above and prints the GNOME shortcut setup steps (optionally sets them via `gsettings`).

## 12. Build order & acceptance per step

1. **Environment + skeleton** — repo layout, venv, `floatnote --help`.
2. **Core proof + benchmark** — daemon + socket; `toggle-bug` records and prints text to the terminal. Benchmark script times `base.en` vs `small.en` on 3 real recordings; user picks model. ✅ when a 10 s note returns text and timings are reported.
3. **Session list + paste-all** — SQLite store, `paste-all`, `undo`, `list`. ✅ when pasting into Claude Code gives the §6 format.
4. **Floating panel** — keep-above, no focus steal, edit/delete/move. ✅ when it stays above Chrome/Firefox on GNOME Wayland while typing in the browser.
5. **Ideas** — `toggle-idea`, done flag, `ideas.md` export. ✅ when ideas survive a reboot.
6. **Autostart + home screen + install.sh.**
7. **Polish** — sounds, error messages, vocabulary, README.

## 13. Success criteria (from plan, made measurable)

- One key press records from any window (verified in browser + terminal).
- 10 s note → text in ≤ 3 s with the chosen model (measured in step 2).
- Idle: RAM < 1 GB, CPU ≈ 0 % (check with `ps`/`top` after 5 min idle).
- Session and idea notes survive daemon crash and reboot.
- Starts on login with no manual action.

## 14. Out of scope for V1

Typing into the focused window, AI cleanup, tags/search, sync, multi-language, screenshots, MCP server (the `list` command covers the basic need), live config reload.
