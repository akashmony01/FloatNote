"""FloatNote 1.3: dictation, ideas renamed to to-dos, the on-disk queue and the safety net."""

import sqlite3
import threading
import time

import pytest

from floatnote import config, daemon as daemon_mod
from floatnote.store import DICTATION_KEEP, GENERAL_ID, Store

from test_daemon import FakeRecorder, FakeSounds, FakeTranscriber


def _v2_database(path):
    """A database as FloatNote 1.0-1.2 left it (ideas, CHECK without 'todo')."""
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE notes (id INTEGER PRIMARY KEY,
          kind TEXT NOT NULL CHECK (kind IN ('bug','idea')), text TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT, done INTEGER NOT NULL DEFAULT 0,
          archived_at TEXT, batch_id TEXT, duration_s REAL, project_id INTEGER);
        CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
          folder TEXT, created_at TEXT NOT NULL);
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO projects VALUES (1, 'General', NULL, '2026-11-12T10:00:00');
        INSERT INTO notes (kind, text, created_at, done, project_id)
          VALUES ('bug', 'old bug', '2026-11-12T10:00:00', 0, 1),
                 ('idea', 'open idea', '2026-11-12T10:00:00', 0, NULL),
                 ('idea', 'done idea', '2026-11-12T10:00:00', 1, NULL);
        PRAGMA user_version=2;
    """)
    db.close()


def test_ideas_become_todos_and_dictations_fit(tmp_path):
    path = tmp_path / "old.db"
    _v2_database(path)
    s = Store(path)
    assert [n.text for n in s.todos()] == ["open idea"]
    assert len(s.todos(include_done=True)) == 2
    assert s.session_notes(GENERAL_ID)[0].text == "old bug"
    s.add("dictation", "hello")  # the new CHECK constraint allows it
    assert s.dictations()[0].text == "hello"
    s.close()
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 3
    Store(path).close()  # opening again doesn't migrate twice


def test_dictation_history_keeps_the_newest(tmp_path):
    s = Store(tmp_path / "n.db")
    for i in range(DICTATION_KEEP + 5):
        s.add("dictation", f"d{i}", project_id=7)
    history = s.dictations()
    assert len(history) == DICTATION_KEEP
    assert history[0].text == f"d{DICTATION_KEEP + 4}" and history[0].project_id is None
    s.add("todo", "unaffected")
    assert s.clear_dictations() == DICTATION_KEEP
    assert s.dictations() == [] and len(s.todos()) == 1
    with pytest.raises(ValueError):
        s.add("idea", "old kind")


def test_old_hold_idea_setting_is_renamed(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('model = "small.en"\n# keys\nhold_idea = "super+shift"\n')
    cfg = config.load(path)
    assert cfg.hold_todo == "super+shift" and cfg.hold_dictation == "ctrl+alt"
    assert "hold_todo" in path.read_text() and "hold_idea" not in path.read_text()
    assert not cfg.dictation_enabled and cfg.todo_enabled


def _daemon(tmp_path, notified=None, **cfg):
    """A daemon with a queue folder and a fake desktop notification."""
    store = Store(tmp_path / "t.db")
    notes, done = [], threading.Event()
    d = daemon_mod.Daemon(
        config.Config(keep_recordings=0, **cfg), store, recorder=FakeRecorder(2.0), sounds=FakeSounds(),
        transcriber_factory=lambda: FakeTranscriber("see you at five"),
        on_note=lambda n: (notes.append(n), done.set()), queue_dir=tmp_path / "queue",
        desktop_notify=lambda title, body: (notified if notified is not None else []).append((title, body)))
    d.copied = []
    d.copy = d.copied.append
    return d, notes, done


def test_dictation_copies_and_notifies(tmp_path):
    notified = []
    d, notes, done = _daemon(tmp_path, notified, dictation_enabled=True)
    d.start()
    d.on_hold_action(("start", "dictation"))
    assert d.ui_state()["recording"] == "dictation"
    d.on_hold_action(("stop",))
    assert done.wait(2)
    assert notes[0].kind == "dictation" and d.copied == ["see you at five"]
    assert notified == [("Copied, paste it anywhere", "see you at five")]
    assert d.store.dictations()[0].text == "see you at five"
    assert list((tmp_path / "queue").iterdir()) == []  # the queued copy is gone once saved
    d.close()


def test_switched_off_parts_dont_record(tmp_path):
    d, notes, done = _daemon(tmp_path, todo_enabled=False)  # dictation is off by default
    d.start()
    for kind in ("dictation", "todo"):
        reply = d.start_recording(kind)
        assert not reply["ok"] and "turned off" in reply["error"]
        assert d.ui_state()["recording"] is None
    assert d.start_recording("bug")["ok"]
    d.close()


def test_tracker_only_has_switched_on_keys():
    names = lambda cfg: set(daemon_mod.build_tracker(cfg).combos.values())  # noqa: E731
    assert names(config.Config()) == {"bug", "todo"}
    assert names(config.Config(dictation_enabled=True, todo_enabled=False)) == {"bug", "dictation"}


def test_queued_recordings_survive_a_restart(tmp_path):
    gate = threading.Event()

    class SlowTranscriber(FakeTranscriber):
        def transcribe(self, audio):
            gate.wait(5)
            return super().transcribe(audio)

    d, notes, done = _daemon(tmp_path)
    d._transcriber_factory = SlowTranscriber
    d.start()
    for kind in ("bug", "todo"):
        d.start_recording(kind)
        d.stop_recording()
    assert d.ui_state()["queue"] == ["bug", "todo"]
    assert len(list((tmp_path / "queue").glob("*.wav"))) == 2
    # "Crash": a new FloatNote on the same folders picks both up.
    d2, notes2, done2 = _daemon(tmp_path)
    d2.store = Store(tmp_path / "t2.db")
    d2.start()
    deadline = time.monotonic() + 3
    while len(notes2) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert sorted(n.kind for n in notes2) == ["bug", "todo"]
    assert list((tmp_path / "queue").glob("*.wav")) == []
    gate.set()
    d.close()
    d2.close()


def test_watchdog_calls_stuck_handler(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon_mod, "STUCK_BASE_SECONDS", 0)
    monkeypatch.setattr(daemon_mod, "STUCK_PER_AUDIO_SECOND", 0)
    real_sleep = time.sleep
    monkeypatch.setattr(daemon_mod.time, "sleep", lambda s: real_sleep(min(s, 0.05)))
    gate, stuck = threading.Event(), threading.Event()

    class HangingTranscriber(FakeTranscriber):
        def transcribe(self, audio):
            gate.wait(5)
            return super().transcribe(audio)

    d, notes, done = _daemon(tmp_path)
    d._transcriber_factory = HangingTranscriber
    d.on_stuck = stuck.set
    d.start()
    d.start_recording("bug")
    d.stop_recording()
    assert stuck.wait(3)
    assert list((tmp_path / "queue").glob("*.wav"))  # kept for the next start
    gate.set()
    d.close()


def test_stuck_limit_grows_with_the_recording():
    assert daemon_mod.stuck_after(0) == 60
    assert daemon_mod.stuck_after(30) == 150


def test_quit_hands_open_close_to_the_desktop(tmp_path, monkeypatch):
    from floatnote import shortcuts

    installed = []
    monkeypatch.setattr(shortcuts, "detect_desktop", lambda *a: "kde")
    monkeypatch.setattr(shortcuts, "install", lambda launcher, toggle, nxt: installed.append((toggle, nxt)))
    d, notes, done = _daemon(tmp_path)
    quits = []
    d.on_quit = lambda: quits.append(1)
    d.shortcut_method = "desktop"  # already handled by the desktop: nothing to do
    d.quit()
    assert installed == [] and quits == [1]
    d.shortcut_method = "keyboard"
    d.quit()
    assert installed == [("ctrl+super+alt+n", "ctrl+super+alt+p")] and quits == [1, 1]
    monkeypatch.setattr(shortcuts, "install", lambda *a: 1 / 0)
    d.quit()  # a failure never blocks quitting
    assert quits == [1, 1, 1]


def test_recovered_dictation_is_saved_but_not_copied(tmp_path):
    notified = []
    d, notes, done = _daemon(tmp_path, notified, dictation_enabled=True)
    d._enqueue(daemon_mod._Job("dictation", FakeRecorder(1.0).stop()))  # saved to the queue folder
    d2, notes2, done2 = _daemon(tmp_path, notified, dictation_enabled=True)
    d2.start()
    assert done2.wait(2)
    assert notes2[0].kind == "dictation" and d2.copied == []
    assert notified == [("Dictation from before the restart", "It's in FloatNote's Dictation tab.")]
    d2.close()


def test_hands_free_recording_state_and_unlock(tmp_path):
    from floatnote.hotkeys import ChordTracker, parse_combo

    d, notes, done = _daemon(tmp_path)
    unlocked = []
    tracker = ChordTracker({parse_combo("ctrl+super"): "bug"})
    tracker.unlock = lambda: unlocked.append(1)
    d.listener = type("L", (), {"tracker": tracker})()
    d.start()
    d.on_hold_action(("start", "bug", "hands-free"))
    assert d.ui_state()["hands_free"] and d.ui_state()["recording"] == "bug"
    d._auto_stop()  # the time limit ends it: the keys are unlocked
    assert not d.ui_state()["hands_free"] and unlocked == [1]
    assert done.wait(2)
    d.on_hold_action(("start", "dictation", "hands-free"))  # dictation is off: never started
    assert unlocked == [1, 1] and d.ui_state()["recording"] is None
    d.close()


def test_notification_replaces_only_one_still_on_screen(monkeypatch):
    from floatnote import notify

    monkeypatch.setattr(notify, "_last_id", 7)
    monkeypatch.setattr(notify, "_last_at", 100.0)
    assert notify.replaces_id(now=101.0) == 7     # still showing: replace it
    assert notify.replaces_id(now=105.0) == 0     # expired: KDE would drop a replacement
    monkeypatch.setattr(notify, "_last_id", 0)    # closed (signal received)
    assert notify.replaces_id(now=100.5) == 0


def test_desktop_handled_keys_are_not_read_twice(tmp_path):
    from floatnote.hotkeys import parse_key_combo

    cfg = config.Config()
    assert set(daemon_mod.build_tracker(cfg).keys.values()) == {"toggle", "next"}
    assert daemon_mod.build_tracker(cfg, press_keys=False).keys == {}
    d, notes, done = _daemon(tmp_path)
    d.shortcut_method = "desktop"  # e.g. KDE: its shortcut opens FloatNote
    assert parse_key_combo("ctrl+super+alt+n") not in d._build_tracker().keys
    d.shortcut_method = "keyboard"
    assert parse_key_combo("ctrl+super+alt+n") in d._build_tracker().keys
