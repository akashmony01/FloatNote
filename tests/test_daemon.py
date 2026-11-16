import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from floatnote import bench, client, daemon as daemon_mod
from floatnote.config import Config
from floatnote.store import Store
from floatnote.transcriber import Result, build_prompt


class FakeRecorder:
    def __init__(self, seconds=2.0):
        self.seconds = seconds
        self.active = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False
        return np.zeros(int(self.seconds * 16000), dtype=np.float32)


class FakeTranscriber:
    def __init__(self, text="the button is broken"):
        self.text = text

    def transcribe(self, audio):
        return Result(self.text, len(audio) / 16000, 0.01)


class FakeSounds:
    def __init__(self):
        self.played = []

    def play(self, cue):
        self.played.append(cue)


def make(seconds=2.0, text="the button is broken", store=None, **cfg):
    cfg.setdefault("keep_recordings", 0)
    notes = []
    done = threading.Event()

    def on_note(n):
        notes.append(n)
        done.set()

    store = store or Store(Path(tempfile.mkdtemp()) / "t.db")
    d = daemon_mod.Daemon(Config(**cfg), store, recorder=FakeRecorder(seconds), sounds=FakeSounds(),
                          transcriber_factory=lambda: FakeTranscriber(text), on_note=on_note)
    d.copied = []
    d.copy = d.copied.append
    d.start()
    return d, notes, done


def test_toggle_records_and_transcribes():
    d, notes, done = make()
    assert d.handle({"cmd": "toggle-bug"})["message"] == "recording bug note"
    assert d.handle({"cmd": "toggle-bug"})["ok"]
    assert done.wait(2)
    assert notes[0].kind == "bug" and notes[0].text == "the button is broken"
    assert d.sounds.played == ["start", "stop"]
    d.close()


def test_other_key_stops_and_keeps_kind():
    d, notes, done = make()
    d.handle({"cmd": "toggle-todo"})
    d.handle({"cmd": "toggle-bug"})
    assert done.wait(2)
    assert notes[0].kind == "todo"
    d.close()


def test_short_recording_discarded():
    d, notes, done = make(seconds=0.2)
    d.handle({"cmd": "toggle-bug"})
    assert "discarded" in d.handle({"cmd": "toggle-bug"})["message"]
    assert not done.wait(0.3)
    assert d.sounds.played == ["start", "cancel"]
    d.close()


def test_empty_transcript_makes_no_note():
    d, notes, done = make(text="")
    d.handle({"cmd": "toggle-bug"})
    d.handle({"cmd": "toggle-bug"})
    assert not done.wait(0.3)
    assert notes == []
    d.close()


def test_auto_stop_after_max_length():
    d, notes, done = make(max_record_seconds=0.1)
    d.handle({"cmd": "toggle-bug"})
    assert done.wait(2)
    assert d.handle({"cmd": "status"})["recording"] is None
    d.close()


def test_unknown_and_unbuilt_commands():
    d, _, _ = make()
    assert not d.handle({"cmd": "nope"})["ok"]
    assert "no window" in d.handle({"cmd": "show"})["error"]
    d.close()


def test_socket_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    d, _, _ = make()
    server = daemon_mod._Server(str(tmp_path / "floatnote.sock"), daemon_mod._Handler)
    server.daemon_obj = d
    d.on_quit = lambda: threading.Thread(target=server.shutdown, daemon=True).start()
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        assert client.send("ping")["message"] == "pong"
        assert client.send("toggle-bug")["ok"]
        assert client.send("quit")["message"] == "bye"
        t.join(2)
        assert not t.is_alive()
    finally:
        server.server_close()
        d.close()


def test_prompt_and_wer():
    assert build_prompt([]) is None
    assert "Supabase" in build_prompt(["Supabase"])
    assert bench.word_error_rate("The navbar is broken.", "the navbar is broken") == 0
    assert bench.word_error_rate("a b c d", "a x c") == 0.5


def record_note(d, done, kind="toggle-bug"):
    done.clear()
    d.handle({"cmd": kind})
    d.handle({"cmd": kind})
    assert done.wait(2)


def test_notes_are_saved_to_store():
    d, notes, done = make()
    record_note(d, done)
    record_note(d, done, "toggle-todo")
    assert [n.text for n in d.store.session_notes()] == ["the button is broken"]
    assert len(d.store.todos()) == 1
    d.close()


def test_paste_all_copies_archives_and_undo_restores():
    d, notes, done = make(copy_intro="Fix these:")
    record_note(d, done)
    record_note(d, done)
    r = d.handle({"cmd": "copy-all"})
    assert r["count"] == 2
    assert d.copied == ["Fix these:\n\n1. the button is broken\n2. the button is broken\n"]
    assert d.store.session_notes() == []
    assert d.handle({"cmd": "undo"})["message"] == "Restored 2 note(s)"
    assert len(d.store.session_notes()) == 2
    assert d.handle({"cmd": "undo"})["message"] == "Nothing to undo in this project"
    d.close()


def test_paste_all_empty_and_clipboard_failure():
    d, notes, done = make()
    assert d.handle({"cmd": "paste-all"})["count"] == 0
    record_note(d, done)

    def broken(text):
        raise daemon_mod.clipboard.ClipboardError("no display")

    d.copy = broken
    r = d.handle({"cmd": "paste-all"})
    assert not r["ok"] and "no display" in r["error"]
    assert len(d.store.session_notes()) == 1  # nothing lost
    d.close()


class FakeUI:
    def __init__(self):
        self.events = []

    def changed(self, message=None, event=None):
        self.events.append(("changed", message))
        if event:
            self.events.append(("event", event))

    def show_panel(self, kind=None):
        self.events.append(("show", kind))

    def toggle_panel(self):
        self.events.append(("toggle", None))

    def open_home(self):
        self.events.append(("home", None))

    def quit(self):
        self.events.append(("quit", None))


def test_ui_is_notified_and_panel_shown_on_record():
    d, notes, done = make(show_panel_on_record=True)
    ui = d.ui = FakeUI()
    record_note(d, done)
    assert ("show", "bug") in ui.events
    assert d.ui_state()["pending"] == 0
    d.handle({"cmd": "paste-all"})
    assert ("changed", "Copied 1 bug(s), now paste them anywhere") in ui.events
    assert ("event", "copied") in ui.events
    d.handle({"cmd": "show"})
    d.handle({"cmd": "home"})
    assert ("toggle", None) in ui.events and ("home", None) in ui.events
    d.close()


def test_clear_archives_without_copying():
    d, notes, done = make()
    record_note(d, done)
    assert d.handle({"cmd": "clear"})["count"] == 1
    assert d.copied == [] and d.store.session_notes() == []
    assert d.handle({"cmd": "undo"})["ok"]
    assert len(d.store.session_notes()) == 1
    d.close()


def test_copy_note_copies_one_idea_without_archiving():
    d, notes, done = make()
    idea_id = d.store.add("todo", "Dark mode for the dropdown")
    assert d.handle({"cmd": "copy-note", "id": idea_id})["ok"]
    assert d.copied == ["Dark mode for the dropdown"]
    assert [n.text for n in d.store.todos()] == ["Dark mode for the dropdown"]  # still there
    assert not d.handle({"cmd": "copy-note", "id": 999})["ok"]
    assert not d.handle({"cmd": "copy-note", "id": "1"})["ok"]
    d.close()


def test_keeps_only_recent_recordings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    d, notes, done = make(keep_recordings=2)
    for _ in range(3):
        record_note(d, done)
        time.sleep(1.05)  # file names have 1 s resolution
    rec = tmp_path / "floatnote" / "recordings"
    assert len(list(rec.glob("*.wav"))) == 2
    heard = sorted(rec.glob("*.heard.txt"))
    assert len(heard) == 2 and "the button is broken" in heard[-1].read_text()
    d.close()


def test_hold_actions_start_stop_cancel():
    d, notes, done = make()
    d.on_hold_action(("start", "todo"))
    assert d.ui_state()["recording"] == "todo"
    assert d.handle({"cmd": "start-bug"})["message"] == "already recording"
    d.on_hold_action(("stop",))
    assert done.wait(2) and notes[0].kind == "todo"
    d.on_hold_action(("start", "bug"))
    d.on_hold_action(("cancel",))
    assert d.ui_state()["recording"] is None
    assert d.handle({"cmd": "stop"})["message"] == "not recording"
    assert len(notes) == 1
    d.close()


def test_set_words_saves_and_updates_live_transcriber(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from floatnote import config

    d, notes, done = make()
    assert d.model_ready.wait(2)

    class Live(FakeTranscriber):
        def set_words(self, vocab, fixes):
            self.words = (vocab, fixes)

    d._transcriber = Live()
    d.set_words(["Wagtail"], {"whitetail": "Wagtail"})
    assert d._transcriber.words == (["Wagtail"], {"whitetail": "Wagtail"})
    assert config.load().replacements == {"whitetail": "Wagtail"}
    d.close()


def test_panel_not_shown_on_record_by_default():
    d, notes, done = make()
    ui = d.ui = FakeUI()
    record_note(d, done)
    assert not any(e[0] == "show" for e in ui.events)
    d.close()


def test_copy_tap_copies():
    d, notes, done = make()
    record_note(d, done)
    d.on_hold_action(("tap", "copy"))
    assert len(d.copied) == 1 and d.store.session_notes() == []
    d.close()


def test_settings_api(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from floatnote import config, hotkeys

    d, notes, done = make()
    d.set_option("copy_intro", "Fix:")
    d.set_option("sounds", False)
    assert config.load().copy_intro == "Fix:" and d.sounds.enabled is False

    d.listener = hotkeys.HotkeyListener(hotkeys.ChordTracker({}), d.on_hold_action)
    assert d.set_keys("bug", "super+alt") is not None  # same as idea
    assert d.set_keys("bug", "ctrl+shift") is None
    assert config.load().hold_bug == "ctrl+shift"
    assert hotkeys.parse_combo("ctrl+shift") in d.listener.tracker.combos

    installed = []
    monkeypatch.setattr("floatnote.shortcuts.install",
                        lambda launcher, toggle, next_project: installed.append(toggle))
    d.shortcut_method = "keyboard"  # FloatNote reads the keys: only the tracker changes
    assert d.set_keys("toggle", "ctrl+super+alt+m") is None
    assert installed == [] and config.load().toggle_keys == "ctrl+super+alt+m"
    assert d.listener.tracker.keys[hotkeys.parse_key_combo("ctrl+super+alt+m")] == "toggle"

    d.shortcut_method = "desktop"  # the desktop handles them: update its settings too
    assert d.set_keys("toggle", "ctrl+super+alt+j") is None
    assert installed == ["ctrl+super+alt+j"]

    def refuse(*a):
        raise RuntimeError("taken")

    monkeypatch.setattr("floatnote.shortcuts.install", refuse)
    assert "taken" in d.set_keys("toggle", "ctrl+super+alt+k")
    assert config.load().toggle_keys == "ctrl+super+alt+j"  # not saved
    d.close()


def test_key_actions_toggle_and_next_project():
    d, notes, done = make()
    toggled = []

    class FakeUI:
        def changed(self, *a): pass
        def toggle_panel(self): toggled.append(1)

    d.ui = FakeUI()
    web = d.store.add_project("Web")
    d.on_hold_action(("key", "toggle"))
    assert toggled == [1]
    d.on_hold_action(("key", "next"))
    assert d.active_project_id == web
    d.close()


def test_projects_record_copy_and_cycle():
    from floatnote.store import GENERAL_ID

    d, notes, done = make()
    web = d.store.add_project("Web")
    record_note(d, done)  # goes to General
    d.handle({"cmd": "set-project", "name": "web"})
    assert d.active_project_id == web
    record_note(d, done)
    assert len(d.store.session_notes(web)) == 1 and len(d.store.session_notes(GENERAL_ID)) == 1

    assert d.handle({"cmd": "copy-all"})["count"] == 1  # only the active project
    assert len(d.store.session_notes(GENERAL_ID)) == 1

    assert d.handle({"cmd": "next-project"})["project"] == "General"  # wraps around
    assert d.handle({"cmd": "next-project"})["project"] == "Web"
    assert not d.handle({"cmd": "set-project", "name": "nope"})["ok"]
    d.close()


def test_project_switch_mid_recording_keeps_original_project():
    from floatnote.store import GENERAL_ID

    d, notes, done = make()
    web = d.store.add_project("Web")
    done.clear()
    d.handle({"cmd": "toggle-bug"})        # starts in General
    d.set_active_project(web)
    d.handle({"cmd": "toggle-bug"})
    assert done.wait(2)
    assert notes[0].project_id == GENERAL_ID
    d.close()


def test_take_returns_and_archives():
    d, notes, done = make()
    record_note(d, done)
    r = d.handle({"cmd": "take"})
    assert r["project"] == "General" and r["notes"] == ["the button is broken"]
    assert d.handle({"cmd": "take"})["count"] == 0
    assert d.handle({"cmd": "undo"})["ok"]
    assert len(d.store.session_notes()) == 1
    d.close()


def test_next_project_key_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d, notes, done = make()
    monkeypatch.setattr("floatnote.shortcuts.install", lambda *a: None)
    assert "same keys" in d.set_keys("next", "ctrl+super+alt+n")  # clashes with open/close
    assert d.set_keys("next", "ctrl+super+alt+o") is None
    d.close()


def test_failed_model_load_is_retried_and_notes_not_lost():
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("offline")
        return FakeTranscriber("works now")

    notes, done = [], threading.Event()
    d = daemon_mod.Daemon(Config(keep_recordings=0), Store(Path(tempfile.mkdtemp()) / "t.db"),
                          recorder=FakeRecorder(), sounds=FakeSounds(), transcriber_factory=flaky,
                          on_note=lambda n: (notes.append(n), done.set()))
    d.copy = lambda text: None
    d.start()
    assert d.model_ready.wait(2) and d.model_error == "offline"
    record_note(d, done)  # the worker is still alive and retries the load
    assert notes[0].text == "works now" and d.model_error is None
    d.close()


def test_newest_model_choice_wins_and_is_saved_only_on_success(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from floatnote import config

    gate = threading.Event()

    def factory():
        if d.cfg.model == "base.en":
            gate.wait(2)  # slow first switch
            return FakeTranscriber("base")
        return FakeTranscriber("small")

    d = daemon_mod.Daemon(Config(keep_recordings=0), Store(Path(tempfile.mkdtemp()) / "t.db"),
                          recorder=FakeRecorder(), sounds=FakeSounds(), transcriber_factory=factory)
    d.start()
    assert d.model_ready.wait(2)
    d.set_model("base.en")      # slow
    d.set_model("distil-small.en")  # newer choice finishes first
    assert d.model_ready.wait(2)
    gate.set()
    time.sleep(0.2)
    assert d._transcriber.text == "small"  # the slow, older switch didn't overwrite it
    assert config.load().model == "distil-small.en"
    d.close()


def test_note_survives_its_project_being_deleted_while_transcribing():
    from floatnote.store import GENERAL_ID

    d, notes, done = make()
    web = d.store.add_project("Web")
    d.set_active_project(web)
    done.clear()
    d.handle({"cmd": "toggle-bug"})
    d.store.delete_project(web)
    d.handle({"cmd": "toggle-bug"})
    assert done.wait(2)
    assert notes[0].project_id == GENERAL_ID
    d.close()


def test_undo_only_touches_the_active_project():
    d, notes, done = make()
    web = d.store.add_project("Web")
    record_note(d, done)                 # General
    d.handle({"cmd": "copy-all"})
    d.set_active_project(web)
    assert d.handle({"cmd": "undo"})["message"] == "Nothing to undo in this project"
    d.close()


def test_single_instance_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from floatnote import paths
    paths.data_dir().mkdir(parents=True)
    first = daemon_mod._single_instance_lock()
    assert first is not None
    assert daemon_mod._single_instance_lock() is None
    first.close()
    assert daemon_mod._single_instance_lock() is not None


def test_enable_hold_keys_uses_pkexec(monkeypatch):
    import subprocess as sp

    d, notes, done = make()
    calls = []
    monkeypatch.setattr(daemon_mod.Daemon, "user_in_input_group", staticmethod(lambda: False))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pkexec")

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return sp.CompletedProcess(cmd, 126, "", "")  # user cancelled the password dialog

    monkeypatch.setattr(sp, "run", fake_run)
    ok, msg = d.enable_hold_keys()
    assert not ok and msg == "Not changed."
    assert calls[0][:3] == ["pkexec", "/bin/sh", "-c"]
    script, user = calls[0][3], calls[0][-1]
    assert 'usermod -aG input "$1"' in script and "/usr/lib/group" in script  # Fedora atomic too
    assert user and user != "sh"
    d.close()
