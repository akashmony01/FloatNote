"""Developer tool: open the FloatNote dropdown with sample data and save a PNG.

    .venv/bin/python tools/screenshot.py OUT_DIR VIEW

VIEW is one of: bugs, todo, dictation, projects, selector, settings, settings-keys,
settings-copy, settings-speech, settings-words, settings-general, guide, guide5, large.
Uses a throwaway data folder, so your real notes are never touched. Used for
checking layouts and for the README screenshots.
"""

import os
import sys
import tempfile
from pathlib import Path

from floatnote.env import clean_snap_env

clean_snap_env()
out, view = Path(sys.argv[1]), sys.argv[2]
out.mkdir(parents=True, exist_ok=True)
os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()

import numpy as np  # noqa: E402

from floatnote.config import Config  # noqa: E402
from floatnote.daemon import Daemon  # noqa: E402
from floatnote.store import Store  # noqa: E402
from floatnote.transcriber import Result  # noqa: E402
from floatnote.ui import App, Gdk, GLib, Gtk  # noqa: E402


class FakeRecorder:
    def start(self):
        pass

    def stop(self):
        return np.zeros(32000, dtype=np.float32)


class FakeTranscriber:
    def transcribe(self, audio):
        return Result("x", 2, 0.1)

    def set_words(self, *args):
        pass


store = Store(Path(os.environ["XDG_DATA_HOME"]) / "sample.db")
web = store.add_project("Client website", folder=str(Path.home() / "code" / "client-site"))
store.add_project("FloatNote")
for text in ["The navbar overlaps the hero image on mobile.",
             "Submit button does nothing when the email is empty.",
             "The Wagtail admin is not showing the preview in the canvas."]:
    store.add("bug", text, project_id=web)
store.add("bug", "Login page typo in the footer.")
store.add("todo", "Export notes as a markdown file per day.")
store.add("todo", "Write the release notes for the new version.")
done = store.add("todo", "Attach a screenshot to the last note.")
store.set_done(done, True)
for text in ["Sounds good, I'll send the case studies by Friday.",
             "Hi team, the staging site is updated. Please test the checkout flow when you get a chance "
             "and let me know if anything looks off.",
             "Can we move the call to 3 pm?"]:
    store.add("dictation", text)
store.set_active_project(web)

cfg = Config(sounds=False, keep_recordings=0, dictation_enabled=True,
             vocabulary=["Claude Code", "Tailwind", "Supabase", "API", "Wagtail"],
             replacements={"whitetail": "Wagtail", "white tail": "Wagtail"})
daemon = Daemon(cfg, store, recorder=FakeRecorder(), transcriber_factory=FakeTranscriber)
daemon.start()
# Look like a normal setup with keyboard access (Settings → Keys buttons enabled),
# without really reading the keyboard.
daemon.listener = type("NoListener", (), {"tracker": None})()
daemon.shortcut_method = "keyboard"
app = App(daemon)
if not view.startswith("guide"):
    app.settings["guide_seen"] = True
tab = {"selector": "bugs", "large": "bugs", "guide": None, "guide5": None}.get(view, view)
if view.startswith("settings-"):
    tab = "settings"
app.dropdown.open_dropdown(None, tab)
if view.startswith("settings-"):
    app.dropdown.settings_tab_buttons[view.split("-", 1)[1]].set_active(True)
if view == "guide5":
    app.dropdown._guide_step(4)
if view == "large":
    app.dropdown._toggle_size()
if view == "todo":
    app.dropdown.show_done.set_active(True)
if view == "selector":
    GLib.timeout_add(600, lambda: app.dropdown.project_btn.set_active(True) and False)


def snap():
    app.dropdown.present()  # focused, so nothing is drawn greyed out
    while Gtk.events_pending():
        Gtk.main_iteration()
    window = app.dropdown.get_window()
    x, y = app.dropdown.get_position()
    w, h = app.dropdown.get_size()
    print(f"{view}: {w}x{h} at x={x} (right edge {x + w})")
    pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, window.get_width(), window.get_height())
    pixbuf.savev(str(out / f"{view}.png"), "png", [], [])
    Gtk.main_quit()
    return False


GLib.timeout_add(1500, snap)
Gtk.main()
