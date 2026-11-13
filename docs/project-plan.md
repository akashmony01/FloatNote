> **Historical document.** This is the original plan FloatNote started from (November 2026). The shipped behaviour is described in the [README](../README.md); see [design-v1-spec.md](design-v1-spec.md) for the first design.

# FloatNote: Project Plan

A lightweight voice note tool for Linux, built for a developer who tests software and wants to capture many issues by voice, then paste them all at once into Claude Code.

## 1. The Problem

I code mostly with Claude Code. After the code is written, I test it in the browser or app. While testing I find several issues. Today I must write each one down so I do not forget it, and later I speak or type each one again into Claude Code. That is double work and it breaks my focus.

I also get ideas while working that I cannot stop to type. Those ideas get lost.

## 2. The Goal

### Current goal (Version 1)

Build a small, fast, offline tool called FloatNote that:

1. Starts recording when I press a hotkey, from any window.
2. Turns my speech into text locally, with no cloud.
3. Adds each spoken note as one item in a floating list.
4. Lets me copy the whole list at once, as a numbered list, then clears it.
5. Lets me save some notes as long-term ideas, kept for days or weeks.

### Long-term goal

A small, always-ready capture tool for developers: say it once, never lose it, and hand it to an AI coding agent in one step. Later versions may clean up notes with a small local AI model, support search and tags, and possibly type directly into the focused window.

## 3. Who and What

- User: one developer, on Linux, using Claude Code.
- Builder: a single developer working with Claude Code as the coding agent.
- Cost: free, open source libraries only.
- Weight: must stay light. Target about 500 MB to 1 GB of memory while idle with the model loaded, and near zero CPU when idle.

## 4. Two Kinds of Notes

### Session notes (bug list)

- Temporary. Live only until I paste them.
- Each note is one issue found during a test session.
- Paste all copies them as a numbered list and clears the session list.

### Idea notes (long-term)

- Saved in a local SQLite database with date, text, and a done flag.
- Kept until I delete them or mark them done.
- Shown on a home screen so I can see what I wanted to build and have not built yet.

## 5. Version 1 Features

### Must have

1. Two record hotkeys set in the desktop keyboard settings: one for session notes (bugs) and one for idea notes. Press once to start, press again to stop.
2. Local speech to text with faster-whisper, using the small English model as the default.
3. A small floating window listing session notes, always visible when shown.
4. Edit and delete for each note, because speech to text sometimes mishears words.
5. Paste all: a button and a hotkey that copy all session notes to the clipboard as a numbered list, then clear the session list. I paste into Claude Code myself.
6. Idea notes saved in SQLite.
7. Notes file or database stored in a plain, easy to find folder so I can read it later.

### Cheap extras worth including

1. Autostart on login with a desktop entry file.
2. A centered home screen on login showing open idea notes, with a tick to mark done.
3. A sound or tray cue when recording starts and stops, so I know the microphone is live.

### Not in Version 1

- Typing text straight into the focused window.
- Tags, search, sync between devices, phone app.
- AI cleanup of notes.
- Multiple languages. English only keeps the model smaller and more accurate.
- Sending audio files to Claude. Claude Code voice mode is dictation only, and I found no support for audio file input, so the tool keeps its own local transcription.

## 6. Recommended Technology

- Language: Python.
- Speech to text: faster-whisper with the small English model. The base English model is a lighter fallback. Vosk is the lightest option but less accurate on technical words.
- Recording: sounddevice.
- Window: a small GTK or Tkinter window. Qt is an option if the agent prefers it.
- Storage: SQLite, built into Python.
- Clipboard: wl-copy on Wayland, xclip on X11.
- Hotkeys: the desktop environment's own shortcut settings, each calling a command such as floatnote toggle-bug, floatnote toggle-idea, floatnote paste-all, floatnote show. A running background process receives these commands.

## 7. Architecture Sketch

A background process starts at login and loads the speech model once. Shortcut commands talk to it through a small local socket or a command line tool. When a recording stops, the audio goes to the model, the text is added to the right list, and the window updates. Paste all writes the clipboard and clears the session list. Idea notes are written to SQLite immediately.

## 8. Questions the Coding Agent Should Ask Me First

Before writing code, please discuss and confirm:

1. Display system: am I on X11 or Wayland? Check by running echo $XDG\_SESSION\_TYPE. Also which desktop environment: GNOME, KDE, Hyprland or other?
2. Can the floating window stay on top on my desktop? On GNOME with Wayland it cannot be forced, so should we use a tray icon with a popup instead?
3. How much memory and what CPU does my machine have, and is there a GPU? This decides the model size.
4. Which microphone and audio system do I use, PipeWire or PulseAudio?
5. Which window toolkit do I prefer, GTK, Qt or Tkinter?
6. Should the two record hotkeys be separate, one for bugs and one for ideas, or one hotkey with a choice afterwards?
7. Where should the data folder live, for example in my home directory under a hidden folder, and do I want a plain text export as well as SQLite?
8. What format should paste all produce for Claude Code, for example a short intro line followed by a numbered list?
9. Should paste all clear the list immediately, or ask first, or keep a short undo?

## 9. Build Order

1. Check the environment: display system, desktop, audio, Python version.
2. Prove the core: hotkey command starts and stops a recording, faster-whisper returns text, text appears in the terminal.
3. Add the session list and paste all to clipboard.
4. Add the floating window with edit and delete.
5. Add idea notes and SQLite.
6. Add autostart and the home screen.
7. Polish: sounds, error messages, a short README.

Each step should work and be tested before the next starts.

## 10. Success Criteria for Version 1

- I can record a note from any window with one key press.
- A 5 to 10 second note appears as text in about 1 to 3 seconds.
- I can collect several notes and paste them all into Claude Code with one action.
- Idle memory stays under about 1 GB and idle CPU stays near zero.
- Idea notes are still there after a reboot.
- The app starts by itself when I log in.

## 11. Ideas for Version 2 and Beyond

- A Clean up button using a small local language model, one to three billion parameters, to fix grammar, remove filler words and group similar bugs. It would add roughly one to two gigabytes of memory and a few seconds of delay, so it should be optional.
- Search and tags for idea notes.
- Typing directly into the focused window with ydotool, wtype or xdotool.
- Export session notes to a markdown file per day.
- Optional screenshot attached to a note.

## 12. Open Risks

- Always on top windows behave differently across Wayland desktops.
- Global hotkeys inside Python apps are unreliable on Wayland, which is why shortcuts are set in the desktop settings.
- Speech to text may misspell technical words, which is why edit is a must have.
- The model uses memory all the time if kept loaded. If that is a problem, load it only when recording.
