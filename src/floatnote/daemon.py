"""The FloatNote background process.

Listens on a Unix socket for commands from `floatnote <cmd>` (bound to desktop
hotkeys), records audio, and transcribes it on a worker thread so the socket
always answers quickly. When a display is available it also runs the GTK
windows (see ui.py) on the main thread.
"""

import json
import logging
import os
import queue
import signal
import socketserver
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from . import client, clipboard, notify, paths
from .config import Config
from .recorder import SAMPLE_RATE, Recorder, save_wav
from .sounds import Sounds
from .store import GENERAL_ID, Note, Store, format_paste
from .transcriber import read_wav

log = logging.getLogger("floatnote")

MIN_RECORD_SECONDS = 0.5

# Run as root by pkexec, user name as $1. On Fedora Silverblue/Kinoite the
# 'input' group is only in /usr/lib/group, which usermod doesn't read: copy it
# to /etc/group first.
ADD_TO_INPUT_GROUP = (
    "if ! grep -q '^input:' /etc/group && [ -f /usr/lib/group ]; then "
    "grep '^input:' /usr/lib/group >> /etc/group; fi; "
    'exec usermod -aG input "$1"'
)
KINDS = {"toggle-bug": "bug", "toggle-todo": "todo", "toggle-dictation": "dictation"}
NAMES = {"bug": "bug", "todo": "to-do", "dictation": "dictation"}  # for messages

# Safety net: a transcription taking longer than this is considered stuck, and
# FloatNote restarts itself (queued recordings are on disk and survive).
STUCK_BASE_SECONDS = 60
STUCK_PER_AUDIO_SECOND = 3


# Shortcut name (Settings → Keys) -> config field.
KEY_FIELDS = {"bug": "hold_bug", "todo": "hold_todo", "dictation": "hold_dictation", "copy": "copy_keys",
              "toggle": "toggle_keys", "next": "next_project_keys"}


def model_is_downloaded(name: str) -> bool:
    from .models import is_downloaded

    return is_downloaded(name)


class UI(Protocol):
    """What the daemon needs from the windows. Methods are safe to call from any thread."""

    def changed(self, message: str | None = None, event: str | None = None) -> None: ...
    def show_panel(self, kind: str | None = None) -> None: ...
    def toggle_panel(self) -> None: ...
    def open_home(self) -> None: ...
    def quit(self) -> None: ...


@dataclass
class _Job:
    kind: str
    audio: np.ndarray
    project_id: int | None = None  # project that was active when recording started
    file: Path | None = None  # its copy in the queue folder, deleted when done
    recovered: bool = False  # left over from before a restart

    @property
    def seconds(self) -> float:
        return len(self.audio) / SAMPLE_RATE


def stuck_after(audio_seconds: float) -> float:
    """How long one transcription may take before FloatNote calls it stuck."""
    return STUCK_BASE_SECONDS + STUCK_PER_AUDIO_SECOND * audio_seconds


class Daemon:
    def __init__(self, cfg: Config, store: Store, *, recorder=None, sounds=None,
                 transcriber_factory: Callable | None = None,
                 on_note: Callable[[Note], None] | None = None,
                 copy: Callable[[str], None] = clipboard.copy,
                 queue_dir: Path | None = None,
                 desktop_notify: Callable[[str, str], None] = notify.show):
        self.cfg = cfg
        self.store = store
        self.copy = copy
        self.queue_dir = queue_dir  # None: queued recordings only in memory (tests)
        self.desktop_notify = desktop_notify
        self.recorder = recorder or Recorder()
        self.sounds = sounds or Sounds(cfg.sounds)
        self._transcriber_factory = transcriber_factory or self._default_transcriber
        self.on_note = on_note
        self.ui: UI | None = None
        self.hold_error: str | None = None  # why hold-to-record is off, if it is
        self.listener = None  # HotkeyListener, when hold-to-record is on
        # Who handles open/close and next project: "keyboard" (our listener),
        # "desktop" (the desktop's own shortcut settings) or None (nobody).
        self.shortcut_method: str | None = None
        self.on_quit: Callable[[], None] = lambda: None
        self.on_stuck: Callable[[], None] = self._restart_when_stuck

        self._lock = threading.Lock()
        self._kind: str | None = None  # kind being recorded, None when idle
        self._hands_free = False  # started by double-tap: keeps going until tapped again
        self._recording_project: int | None = None
        self._model_gen = 0  # bumped on every model switch; the newest one wins
        self.model_status = "Loading speech model…"  # shown while the model isn't ready
        self._started_at = 0.0
        self._timer: threading.Timer | None = None
        self._jobs: queue.Queue[_Job | None] = queue.Queue()
        self._pending = 0  # recordings queued or being transcribed
        self._queue_kinds: list[str] = []  # their kinds, oldest (= in progress) first
        self._deadline: float | None = None  # when the current transcription counts as stuck
        self._transcriber = None
        self.model_ready = threading.Event()
        self.model_error: str | None = None
        self._worker = threading.Thread(target=self._work, name="transcriber", daemon=True)

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self._recover_queue()
        self._worker.start()
        threading.Thread(target=self._watchdog, name="watchdog", daemon=True).start()

    def close(self) -> None:
        with self._lock:
            if self._kind is not None:
                self._ended()
                self.recorder.stop()
                self._kind = None
        self._jobs.put(None)

    def _default_transcriber(self):
        from .transcriber import Transcriber

        return Transcriber(self.cfg.model, self.cfg.compute_type,
                           self.cfg.beam_size, self.cfg.vocabulary, self.cfg.replacements)

    def _notify(self, message: str | None = None, event: str | None = None) -> None:
        if self.ui is not None:
            self.ui.changed(message, event)

    def set_words(self, vocabulary: list[str], replacements: dict[str, str]) -> None:
        """Save hint words and word fixes, and use them from the next note on."""
        from . import config

        self.cfg.vocabulary = list(vocabulary)
        self.cfg.replacements = dict(replacements)
        config.set_values({"vocabulary": self.cfg.vocabulary, "replacements": self.cfg.replacements})
        if self._transcriber is not None:
            self._transcriber.set_words(self.cfg.vocabulary, self.cfg.replacements)
        log.info("word lists updated: %d hint word(s), %d fix(es)",
                 len(self.cfg.vocabulary), len(self.cfg.replacements))

    # ---- settings (used by the Settings screen) ---------------------------

    def set_option(self, key: str, value) -> None:
        """Change a simple setting (copy_intro, sounds, home_on_login) and save it."""
        from . import config

        assert key in ("copy_intro", "sounds", "home_on_login", "show_project_in_bar",
                       "todo_enabled", "dictation_enabled", "max_record_seconds"), key
        setattr(self.cfg, key, value)
        if key == "sounds":
            self.sounds.enabled = value
        config.set_values({key: value})
        if key.endswith("_enabled") and self.listener is not None:
            self.listener.tracker = self._build_tracker()
        self._notify()

    def _build_tracker(self):
        """The key tracker for the current settings; without open/close and next
        project when the desktop handles those (or each press would fire twice)."""
        return build_tracker(self.cfg, press_keys=self.shortcut_method != "desktop")

    def enabled(self, kind: str) -> bool:
        """Bugs are always on; to-do and dictation can be switched off in Settings."""
        return {"todo": self.cfg.todo_enabled, "dictation": self.cfg.dictation_enabled}.get(kind, True)

    def can_capture_keys(self) -> bool:
        """Can FloatNote read the keyboard (to capture any new shortcut)?"""
        return self.listener is not None and not self.hold_error

    def capture_keys(self, on_done) -> None:
        """Let the user press a new key combo; on_done(names, error) from another thread."""
        if self.listener is None or self.hold_error:
            on_done(None, self.hold_error or "Hold-to-record is off, so keys can't be captured.")
            return
        self.listener.capture(on_done)

    def cancel_capture(self) -> None:
        """Stop waiting for new keys; the current shortcut stays."""
        if self.listener is not None:
            self.listener.cancel_capture()

    def set_keys(self, which: str, combo: str) -> str | None:
        """Change one shortcut (a key of KEY_FIELDS). Returns an error or None."""
        from . import config
        from .hotkeys import validate_keys

        field = KEY_FIELDS[which]
        values = {w: getattr(self.cfg, f) for w, f in KEY_FIELDS.items()}
        values[which] = combo
        error = validate_keys(values)
        if error:
            return error
        if which in ("toggle", "next") and self.shortcut_method == "desktop":
            from . import shortcuts

            try:
                shortcuts.install(shortcuts.default_launcher(), values["toggle"], values["next"])
            except Exception as e:  # noqa: BLE001
                log.exception("could not change the desktop shortcut")
                return f"Couldn't change the desktop shortcut: {e}"
        setattr(self.cfg, field, combo)
        config.set_values({field: combo})
        if self.listener is not None:
            self.listener.tracker = self._build_tracker()
        log.info("shortcut %s set to %s", which, combo)
        return None

    def set_model(self, name: str) -> None:
        """Switch the speech model; loads in the background (may download first).
        The choice is only saved once the model has loaded."""
        from . import config

        with self._lock:
            if name == self.cfg.model and self.model_error is None and self._transcriber is not None:
                return
            self._model_gen += 1
            gen = self._model_gen
            self.cfg.model = name
            self.model_error = None
        self.model_ready.clear()
        self._notify(f"Loading {name}…")

        def load():
            ok = self._load_model(gen)
            if gen != self._model_gen:
                return  # the user picked another model meanwhile; that one reports
            if ok:
                config.set_values({"model": name})
                log.info("switched to model %s", name)
            self.model_ready.set()
            self._notify(f"Now using {name}" if ok else "Speech model failed, see log")

        threading.Thread(target=load, name="model-loader", daemon=True).start()

    def _load_model(self, gen: int) -> bool:
        """Load the configured model. Only installs it if no newer switch happened."""
        self.model_status = ("Loading speech model…" if model_is_downloaded(self.cfg.model)
                             else f"Downloading speech model {self.cfg.model} (needs internet, ~1 min)…")
        self._notify()
        try:
            transcriber = self._transcriber_factory()
        except Exception as e:  # noqa: BLE001 - offline, disk full, bad download...
            log.exception("could not load model %s", self.cfg.model)
            with self._lock:
                if gen == self._model_gen:
                    self.model_error = str(e)
            return False
        with self._lock:
            if gen != self._model_gen:
                return False
            self._transcriber = transcriber
            self.model_error = None
        return True

    # ---- hold-to-record permission -------------------------------------------

    @staticmethod
    def user_in_input_group() -> bool:
        import grp
        import pwd

        try:
            return pwd.getpwuid(os.getuid()).pw_name in grp.getgrnam("input").gr_mem
        except KeyError:
            return False

    def enable_hold_keys(self) -> tuple[bool, str]:
        """Add the user to the 'input' group with the system password dialog (pkexec).
        Blocking: call it off the GTK thread. Returns (ok, message)."""
        import pwd
        import shutil
        import subprocess

        from .distro import input_group_hint

        if self.user_in_input_group():
            return True, "already allowed"
        if not shutil.which("pkexec"):
            return False, f"Run: {input_group_hint()}  (then restart FloatNote)"
        user = pwd.getpwuid(os.getuid()).pw_name
        r = subprocess.run(["pkexec", "/bin/sh", "-c", ADD_TO_INPUT_GROUP, "sh", user],
                           capture_output=True, text=True)
        if r.returncode != 0:
            # 126/127: the password dialog was cancelled or refused
            return False, "Not changed." if r.returncode in (126, 127) else (r.stderr.strip() or "usermod failed")
        log.info("added %s to the input group", user)
        return True, "ok"

    def restart(self) -> None:
        """Start a fresh FloatNote (e.g. to pick up the 'input' group) and quit this one."""
        import subprocess

        env = {**os.environ, "FLOATNOTE_RESTART": "1"}
        env.pop("FLOATNOTE_SG", None)  # let the new one apply the group again
        subprocess.Popen([sys.executable, "-m", "floatnote", "daemon"], env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        self.on_quit()

    def ui_state(self) -> dict:
        return {
            "recording": self._kind,
            "hands_free": self._hands_free,
            "started_at": self._started_at,
            "pending": self._pending,
            "queue": list(self._queue_kinds),  # kinds waiting, the first one in progress
            "model_ready": self.model_ready.is_set() and self.model_error is None,
            "model_error": self.model_error,
            "model_status": self.model_status,
            "hold_error": self.hold_error,
        }

    # ---- commands --------------------------------------------------------

    def handle(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd == "ping":
            return {"ok": True, "message": "pong"}
        if cmd == "status":
            return {"ok": True, "message": self._status_text(), "recording": self._kind,
                    "model_ready": self.model_ready.is_set(), "pending": self._pending,
                    "hold_on": self.cfg.hold_to_record and self.hold_error is None,
                    "hold_error": self.hold_error, "shortcut_method": self.shortcut_method}
        if cmd in KINDS:
            return self._toggle(KINDS[cmd])
        if cmd in ("start-bug", "start-todo", "start-dictation"):
            return self.start_recording(cmd.removeprefix("start-"))
        if cmd == "stop":
            return self.stop_recording()
        if cmd == "cancel":
            return self.cancel_recording()
        if cmd in ("copy-all", "paste-all"):  # paste-all: old name
            return self._copy_all()
        if cmd == "copy-note":
            return self.copy_note(req.get("id"))
        if cmd == "undo":
            n = self.store.undo_last_batch(self.active_project_id)
            msg = f"Restored {n} note(s)" if n else "Nothing to undo in this project"
            self._notify(msg)
            return {"ok": True, "message": msg}
        if cmd == "clear":
            return self._clear()
        if cmd == "next-project":
            return self.next_project()
        if cmd == "set-project":
            return self.set_project_by_name(req.get("name", ""))
        if cmd == "take":
            return self.take(req.get("project_id"))
        if cmd in ("show", "home"):
            if self.ui is None:
                return {"ok": False, "error": "no window available (daemon runs without a display)"}
            (self.ui.toggle_panel if cmd == "show" else self.ui.open_home)()
            return {"ok": True}
        if cmd == "quit":
            threading.Thread(target=self.quit, name="quit", daemon=True).start()
            return {"ok": True, "message": "bye"}
        return {"ok": False, "error": f"unknown command: {cmd!r}"}

    def _status_text(self) -> str:
        if self.model_error:
            model = f"model {self.cfg.model} FAILED: {self.model_error}"
        else:
            model = f"model {self.cfg.model} {'ready' if self.model_ready.is_set() else 'loading'}"
        rec = f"recording {self._kind}" if self._kind else "idle"
        if self.hold_error:
            model += f"; hold-to-record off ({self.hold_error})"
        project = self.store.project(self.active_project_id)
        return (f"{rec}; {model}; {self._pending} transcribing; project {project.name}: "
                f"{len(self.store.session_notes(project.id))} bug(s); {len(self.store.todos())} open to-do(s)")

    # ---- projects ------------------------------------------------------------

    @property
    def active_project_id(self) -> int:
        return self.store.active_project_id()

    def set_active_project(self, project_id: int) -> None:
        self.store.set_active_project(project_id)
        project = self.store.project(project_id)
        log.info("active project: %s", project.name)
        self._notify(f"Project: {project.name}")

    def next_project(self) -> dict:
        """Switch to the next project (wraps around)."""
        projects = self.store.projects()
        ids = [p.id for p in projects]
        current = self.active_project_id
        nxt = ids[(ids.index(current) + 1) % len(ids)] if current in ids else ids[0]
        self.set_active_project(nxt)
        if len(ids) > 1:
            self.sounds.play("switch")
        name = self.store.project(nxt).name
        return {"ok": True, "message": f"project: {name}", "project": name}

    def set_project_by_name(self, name: str) -> dict:
        project = self.store.project_by_name(name)
        if project is None:
            return {"ok": False, "error": f"no project called {name!r}"}
        self.set_active_project(project.id)
        return {"ok": True, "message": f"project: {project.name}", "project": project.name}

    def take(self, project_id: int | None = None) -> dict:
        """Hand a project's bugs to the caller (e.g. Claude Code) and archive them."""
        project = self.store.project(project_id or self.active_project_id)
        if project is None:
            return {"ok": False, "error": "no such project"}
        notes = self.store.session_notes(project.id)
        if notes:
            self.store.archive_session([n.id for n in notes])
            self._notify(f"Claude took {len(notes)} bug(s) from {project.name}", "copied")
        return {"ok": True, "project": project.name, "count": len(notes),
                "notes": [n.text for n in notes]}

    def _copy_all(self) -> dict:
        notes = self.store.session_notes(self.active_project_id)
        if not notes:
            self._notify("No notes to copy")
            return {"ok": True, "message": "no notes to copy", "count": 0}
        try:
            self.copy(format_paste(self.cfg.copy_intro, notes))
        except clipboard.ClipboardError as e:
            log.error("clipboard failed: %s", e)
            self.sounds.play("error")
            self._notify("Clipboard failed, notes kept")
            return {"ok": False, "error": f"clipboard failed: {e}"}
        # Archive only what was copied: a note finishing transcription right now stays.
        self.store.archive_session([n.id for n in notes])
        self.sounds.play("stop")
        log.info("copied and archived %d note(s)", len(notes))
        self._notify(f"Copied {len(notes)} bug(s), now paste them anywhere", "copied")
        return {"ok": True, "message": f"copied {len(notes)} note(s) (undo: floatnote undo)",
                "count": len(notes)}

    def copy_note(self, note_id) -> dict:
        """Copy one note's text (a to-do, a dictation) without archiving it."""
        note = self.store.get(note_id) if isinstance(note_id, int) else None
        if note is None:
            return {"ok": False, "error": "no such note"}
        try:
            self.copy(note.text)
        except clipboard.ClipboardError as e:
            log.error("clipboard failed: %s", e)
            self.sounds.play("error")
            self._notify("Clipboard failed")
            return {"ok": False, "error": f"clipboard failed: {e}"}
        self.sounds.play("stop")
        what = NAMES.get(note.kind, "note")
        self._notify(f"Copied the {what}, now paste it anywhere", "copied")
        return {"ok": True, "message": f"copied {what}"}

    def _clear(self) -> dict:
        notes = self.store.session_notes(self.active_project_id)
        if notes:
            self.store.archive_session([n.id for n in notes])
        msg = f"Cleared {len(notes)} note(s)" if notes else "Nothing to clear"
        self._notify(msg)
        return {"ok": True, "message": msg, "count": len(notes)}

    def _toggle(self, kind: str) -> dict:
        with self._lock:
            if self._kind is None:
                reply = self._start_recording(kind)
            else:
                # Any record key stops the current recording; it keeps its own kind.
                reply = self._stop_recording()
        self._after_start(reply, kind)
        return reply

    def start_recording(self, kind: str, hands_free: bool = False) -> dict:
        """Start recording (hold-to-record pressed, or double-tapped for hands-free).
        No-op if already recording."""
        with self._lock:
            if self._kind is not None:
                return {"ok": True, "message": "already recording"}
            reply = self._start_recording(kind)
            if reply.get("started"):
                self._hands_free = hands_free
        self._after_start(reply, kind)
        return reply

    def stop_recording(self) -> dict:
        """Stop and transcribe (hold-to-record released)."""
        with self._lock:
            if self._kind is None:
                return {"ok": True, "message": "not recording"}
            return self._stop_recording()

    def cancel_recording(self) -> dict:
        """Throw the current recording away (another key was pressed while holding)."""
        with self._lock:
            if self._kind is None:
                return {"ok": True, "message": "not recording"}
            self._kind = None
            self._ended()
            self.recorder.stop()
        log.info("recording cancelled (another key pressed)")
        self._notify("Cancelled")
        return {"ok": True, "message": "cancelled"}

    def on_hold_action(self, action: tuple) -> None:
        if action[0] == "start":
            hands_free = action[2:] == ("hands-free",)
            reply = self.start_recording(action[1], hands_free=hands_free)
            if hands_free and not reply.get("started"):
                self._unlock_keys()  # nothing to stop later
        elif action[0] == "stop":
            self.stop_recording()
        elif action[0] == "cancel":
            self.cancel_recording()
        elif action == ("tap", "copy"):
            self._copy_all()
        elif action == ("key", "toggle"):
            if self.ui is not None:
                self.ui.toggle_panel()
        elif action == ("key", "next"):
            self.next_project()

    def _after_start(self, reply: dict, kind: str) -> None:
        # Never for dictation: you're typing in another app.
        if reply.get("started") and self.cfg.show_panel_on_record and kind != "dictation" and self.ui is not None:
            self.ui.show_panel(kind)

    def _start_recording(self, kind: str) -> dict:
        if not self.enabled(kind):
            return {"ok": False, "error": f"{NAMES[kind]} is turned off (Settings → General)"}
        try:
            self.recorder.start()
        except Exception as e:  # noqa: BLE001 - mic problems should not kill the daemon
            log.error("could not start recording: %s", e)
            self.sounds.play("error")
            self._notify("Microphone error, see log")
            return {"ok": False, "error": f"microphone error: {e}"}
        self._kind = kind
        self._recording_project = self.active_project_id
        self._started_at = time.monotonic()
        self._timer = threading.Timer(self.cfg.max_record_seconds, self._auto_stop)
        self._timer.daemon = True
        self._timer.start()
        self.sounds.play("start")
        log.info("recording %s note", kind)
        self._notify()
        return {"ok": True, "message": f"recording {kind} note", "started": True}

    def _ended(self) -> None:
        """A recording ended (any way): stop its timer and any hands-free lock."""
        self._cancel_timer()
        if self._hands_free:
            self._hands_free = False
            self._unlock_keys()

    def _unlock_keys(self) -> None:
        if self.listener is not None:
            self.listener.tracker.unlock()

    def _stop_recording(self) -> dict:
        kind = self._kind
        self._kind = None
        self._ended()
        audio = self.recorder.stop()
        seconds = len(audio) / SAMPLE_RATE
        if seconds < MIN_RECORD_SECONDS:
            self.sounds.play("cancel")
            log.info("discarded %.2fs recording (too short)", seconds)
            self._notify("Too short, discarded")
            return {"ok": True, "message": "too short, discarded"}
        self.sounds.play("stop")
        self._enqueue(_Job(kind, audio, self._recording_project))
        log.info("queued %s note (%.1fs audio)", kind, seconds)
        self._notify()
        return {"ok": True, "message": f"transcribing {kind} note ({seconds:.1f}s)"}

    # ---- the queue (kept on disk until each note is saved) ----------------

    def _enqueue(self, job: _Job) -> None:
        """Queue a recording; call with self._lock held (or before start())."""
        if job.file is None and self.queue_dir is not None:
            job.file = self._save_queued(job)
        self._pending += 1
        self._queue_kinds.append(job.kind)
        self._jobs.put(job)

    def _save_queued(self, job: _Job) -> Path | None:
        try:
            self.queue_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.monotonic_ns() % 10**9:09d}"
            wav = self.queue_dir / f"{stem}.wav"
            save_wav(wav, job.audio)
            wav.with_suffix(".json").write_text(json.dumps({"kind": job.kind, "project_id": job.project_id}))
            return wav
        except OSError:
            log.exception("could not save the recording to the queue folder")
            return None

    @staticmethod
    def _drop_queued(job: _Job) -> None:
        if job.file is not None:
            job.file.unlink(missing_ok=True)
            job.file.with_suffix(".json").unlink(missing_ok=True)

    def _recover_queue(self) -> None:
        """Queue recordings left over from last time (a crash, restart or quit)."""
        if self.queue_dir is None or not self.queue_dir.is_dir():
            return
        found = 0
        for wav in sorted(self.queue_dir.glob("*.wav")):
            try:
                meta = json.loads(wav.with_suffix(".json").read_text())
                kind = meta["kind"].replace("idea", "todo")
                job = _Job(kind, read_wav(str(wav)), meta.get("project_id"), file=wav, recovered=True)
            except (OSError, ValueError, KeyError):
                log.exception("unreadable queued recording %s, skipped", wav.name)
                wav.unlink(missing_ok=True)
                wav.with_suffix(".json").unlink(missing_ok=True)
                continue
            with self._lock:
                self._enqueue(job)
            found += 1
        if found:
            log.info("transcribing %d recording(s) left from last time", found)
            self._notify(f"Finishing {found} note(s) from last time…")

    # ---- safety net ----------------------------------------------------

    def _watchdog(self) -> None:
        while True:
            time.sleep(5)
            deadline = self._deadline
            if deadline is not None and time.monotonic() > deadline:
                log.error("transcription stuck, restarting FloatNote (queued notes are kept)")
                self._notify("Transcription got stuck. Restarting FloatNote, your notes are kept…")
                self.on_stuck()
                return

    def _restart_when_stuck(self) -> None:
        if self.queue_dir is None:
            return  # nothing would survive a restart
        self.restart()
        # A stuck thread could keep this process from exiting; make sure it does.
        threading.Timer(5, lambda: os._exit(0)).start()

    # ---- quit ----------------------------------------------------------

    def quit(self) -> None:
        """Quit because the user asked (not a restart). When FloatNote reads the
        keyboard itself, the open/close keys would do nothing until it runs again,
        so hand them to the desktop to start FloatNote; the next start takes them
        back (see _sync_shortcuts)."""
        if self.shortcut_method == "keyboard":
            from . import shortcuts

            try:
                if shortcuts.detect_desktop():
                    shortcuts.install(shortcuts.default_launcher(), self.cfg.toggle_keys, self.cfg.next_project_keys)
                    log.info("open/close keys handed to the desktop until FloatNote starts again")
            except Exception as e:  # noqa: BLE001 - quitting must always work
                log.warning("could not hand open/close to the desktop: %s", e)
        self.on_quit()

    def _auto_stop(self) -> None:
        with self._lock:
            if self._kind is not None:
                log.info("max recording length reached, stopping")
                self._stop_recording()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    # ---- transcription worker ------------------------------------------

    def _work(self) -> None:
        t = time.perf_counter()
        if self._load_model(self._model_gen):
            log.info("model %s loaded in %.1fs", self.cfg.model, time.perf_counter() - t)
        else:
            self.sounds.play("error")
        self.model_ready.set()
        self._notify()

        # Keep serving jobs even if the model failed: _transcribe retries the load.
        while (job := self._jobs.get()) is not None:
            try:
                self._transcribe(job)
            finally:
                self._deadline = None
                self._drop_queued(job)
                with self._lock:
                    self._pending -= 1
                    if self._queue_kinds:
                        self._queue_kinds.pop(0)
                self._notify()

    def _ensure_model(self) -> bool:
        """Wait for a model switch in progress; retry once if the model never loaded
        (e.g. FloatNote started offline and the download failed)."""
        self.model_ready.wait()
        if self._transcriber is not None:
            return True
        self.model_ready.clear()
        self._notify("Loading speech model…")
        ok = self._load_model(self._model_gen)
        self.model_ready.set()
        self._notify()
        return ok

    def _transcribe(self, job: _Job) -> None:
        wav = self._keep_recording(job)
        if not self._ensure_model():
            self.sounds.play("error")
            self._notify("Speech model unavailable, note not saved. Run floatnote doctor")
            return
        self._deadline = time.monotonic() + stuck_after(job.seconds)
        try:
            result = self._transcriber.transcribe(job.audio)
        except Exception:  # noqa: BLE001
            log.exception("transcription failed")
            self.sounds.play("error")
            self._notify("Transcription failed, see log")
            return
        if not result.text:
            log.info("nothing heard in %.1fs of audio", result.audio_seconds)
            self.sounds.play("cancel")
            self._notify("Nothing heard")
            return
        if wav is not None:
            wav.with_suffix(".heard.txt").write_text(f"[{self.cfg.model}] {result.text}\n")
        project_id = job.project_id
        if job.kind == "bug" and (project_id is None or self.store.project(project_id) is None):
            project_id = GENERAL_ID  # its project was deleted while transcribing
        note = self.store.get(self.store.add(job.kind, result.text, result.audio_seconds, project_id))
        # The note's text stays out of the log (privacy); only its size.
        log.info("[%s #%d] %d chars  (%.1fs audio -> %.2fs)", note.kind, note.id, len(note.text),
                 result.audio_seconds, result.elapsed_seconds)
        if note.kind == "todo":
            self._notify("To-do saved")
        elif note.kind == "dictation" and job.recovered:
            # From before a restart: don't overwrite whatever is on the clipboard now.
            self._notify("Dictation from before the restart saved")
            self.desktop_notify("Dictation from before the restart", "It's in FloatNote's Dictation tab.")
        elif note.kind == "dictation":
            self._deliver_dictation(note)
        if self.on_note:
            self.on_note(note)

    def _deliver_dictation(self, note: Note) -> None:
        """Dictation: straight to the clipboard, with a notification that closes itself."""
        try:
            self.copy(note.text)
        except clipboard.ClipboardError as e:
            log.error("clipboard failed: %s", e)
            self.sounds.play("error")
            self._notify("Clipboard failed; the text is in the Dictation tab")
            self.desktop_notify("Couldn't copy the dictation", "It's saved in FloatNote's Dictation tab.")
            return
        self._notify("Dictation copied, paste it anywhere", "copied")
        self.desktop_notify("Copied, paste it anywhere", notify.preview(note.text))


    def _keep_recording(self, job: _Job):
        """Save the last few recordings so models can be compared on real notes."""
        keep = self.cfg.keep_recordings
        if keep <= 0:
            return None
        try:
            folder = paths.recordings_dir()
            folder.mkdir(parents=True, exist_ok=True)
            wav = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{job.kind}.wav"
            save_wav(wav, job.audio)
            old = sorted(folder.glob("*.wav"))[:-keep]
            for f in old:
                f.unlink(missing_ok=True)
                f.with_suffix(".heard.txt").unlink(missing_ok=True)
            return wav
        except OSError:
            log.exception("could not save recording")
            return None


# ---- socket server -------------------------------------------------------

class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline()
        try:
            reply = self.server.daemon_obj.handle(json.loads(line))
        except json.JSONDecodeError:
            reply = {"ok": False, "error": "bad request"}
        except Exception as e:  # noqa: BLE001
            log.exception("command failed")
            reply = {"ok": False, "error": str(e)}
        self.wfile.write((json.dumps(reply) + "\n").encode())


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def setup_logging() -> None:
    from logging.handlers import RotatingFileHandler

    paths.data_dir().mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    log.setLevel(logging.INFO)
    file_handler = RotatingFileHandler(paths.log_file(), maxBytes=512_000, backupCount=2)
    for h in (logging.StreamHandler(sys.stderr), file_handler):
        h.setFormatter(fmt)
        log.addHandler(h)


def build_tracker(cfg: Config, press_keys: bool = True):
    """A ChordTracker for all of FloatNote's keyboard shortcuts. Raises ValueError
    for a bad shortcut in the config."""
    from .hotkeys import ChordTracker, parse_combo, parse_key_combo

    combos = {parse_combo(cfg.hold_bug): "bug"}
    if cfg.todo_enabled:
        combos[parse_combo(cfg.hold_todo)] = "todo"
    if cfg.dictation_enabled:
        combos[parse_combo(cfg.hold_dictation)] = "dictation"
    taps = {parse_combo(cfg.copy_keys): "copy"} if cfg.copy_keys else {}
    keys = {}
    for text, name in ((cfg.toggle_keys, "toggle"), (cfg.next_project_keys, "next")) if press_keys else ():
        if text:
            keys[parse_key_combo(text)] = name
    return ChordTracker(combos, taps=taps, keys=keys)


def _start_hold_keys(cfg: Config, daemon: Daemon):
    if not cfg.hold_to_record:
        return None
    from .hotkeys import HotkeyListener

    try:
        tracker = build_tracker(cfg)
    except ValueError as e:
        daemon.hold_error = str(e)
        log.error("hold-to-record off: %s", e)
        return None
    listener = HotkeyListener(tracker, daemon.on_hold_action)
    listener.start()
    daemon.listener = listener

    def watch_error():  # surface permission problems in status / the window
        while listener.is_alive():
            if listener.error != daemon.hold_error:
                daemon.hold_error = listener.error
                daemon._notify()
            time.sleep(3)

    threading.Thread(target=watch_error, name="hotkeys-status", daemon=True).start()
    return listener


def _sync_shortcuts(cfg: Config, daemon: Daemon, listener) -> None:
    """Decide who handles open/close and next project: FloatNote itself when it
    can read the keyboard, else the desktop's shortcut settings (see shortcuts.sync)."""
    from . import shortcuts
    from .env import clean_snap_env
    from .hotkeys import keyboard_readable

    keyboard = listener is not None and keyboard_readable()
    if not keyboard:
        daemon.shortcut_method = None  # until the desktop has them
    clean_snap_env()  # gsettings breaks with the VS Code snap's schema dir
    try:
        method = shortcuts.sync(keyboard, cfg.toggle_keys, cfg.next_project_keys)
    except Exception:  # noqa: BLE001 - FloatNote works without them
        log.exception("could not set up the open/close and next-project shortcuts")
        method = "keyboard" if keyboard else None
    daemon.shortcut_method = method
    if listener is not None and method == "desktop":
        listener.tracker = daemon._build_tracker()  # the desktop has those two keys now
    log.info("open/close and next project: %s", {"keyboard": "read from the keyboard",
                                                  "desktop": "desktop shortcuts"}.get(method, "no shortcut"))
    daemon._notify()


def _single_instance_lock():
    """Hold an exclusive lock for the daemon's lifetime; None if another one has it."""
    import fcntl

    lock = open(paths.data_dir() / "daemon.lock", "w")  # noqa: SIM115 - kept open on purpose
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


def run(cfg: Config, login: bool = False, headless: bool = False) -> int:
    paths.make_private()
    instance_lock = _single_instance_lock()  # noqa: F841 - released when the process exits
    if instance_lock is None and os.environ.pop("FLOATNOTE_RESTART", None):
        for _ in range(50):  # restarting: wait for the old FloatNote to exit
            time.sleep(0.2)
            if (instance_lock := _single_instance_lock()) is not None:
                break
    if instance_lock is None:
        print("floatnote: daemon is already running", file=sys.stderr)
        return 1
    setup_logging()
    sock = paths.socket_file()
    if sock.exists():
        if client.is_running():
            print("floatnote: daemon is already running", file=sys.stderr)
            return 1
        sock.unlink()  # stale file from a crash
    sock.parent.mkdir(parents=True, exist_ok=True)

    store = Store(paths.db_file(), export_path=paths.todo_export_file())
    paths.old_ideas_export_file().unlink(missing_ok=True)  # ideas.md became todo.md in 1.3
    daemon = Daemon(cfg, store, queue_dir=paths.queue_dir())

    app = None
    if not headless:
        try:
            from .ui import App

            app = App(daemon)
        except Exception:  # noqa: BLE001 - recording still works without windows
            log.exception("could not open windows; running without them")

    listener = _start_hold_keys(cfg, daemon)
    if not headless:
        threading.Thread(target=_sync_shortcuts, args=(cfg, daemon, listener),
                         name="shortcuts", daemon=True).start()

    server = _Server(str(sock), _Handler)
    sock.chmod(0o600)
    server.daemon_obj = daemon
    threading.Thread(target=server.serve_forever, name="socket", daemon=True).start()
    daemon.start()
    log.info("daemon listening on %s (model %s loading)", sock, cfg.model)

    try:
        if app is not None:
            daemon.on_quit = app.quit
            if login and cfg.home_on_login and cfg.todo_enabled and store.todos():
                app.open_home()
            app.run()  # GTK main loop; handles SIGTERM/SIGINT itself
        else:
            stop = threading.Event()
            daemon.on_quit = stop.set
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            signal.signal(signal.SIGINT, lambda *_: stop.set())
            while not stop.wait(1):
                pass
    finally:
        if listener is not None:
            listener.stop()
        server.shutdown()
        server.server_close()
        sock.unlink(missing_ok=True)
        daemon.close()
        store.close()
        log.info("daemon stopped")
    return 0
