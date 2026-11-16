"""GTK3 UI: a panel icon and a dropdown next to it with Bugs, To-do, Dictation and Projects tabs.

Everything here runs on the GTK main thread. Other threads reach the UI only
through App.changed() / show_panel() / toggle_panel() / open_home() / quit(),
which hop over to the main thread with GLib.idle_add.
"""

import json
import os
import threading
from pathlib import Path
import signal
import time

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")

# Run through XWayland so the dropdown can be placed exactly under the icon
# and kept above other windows. PyGObject opens the display as soon as Gdk is
# imported, so this must be an env var set before the import. Removed
# afterwards so child processes (wl-copy, pw-play) don't inherit it.
_saved_backend = os.environ.get("GDK_BACKEND")
os.environ["GDK_BACKEND"] = "x11,*"
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

if _saved_backend is None:
    os.environ.pop("GDK_BACKEND", None)
else:
    os.environ["GDK_BACKEND"] = _saved_backend

from . import paths  # noqa: E402
from .words import suggest_fix  # noqa: E402

COMPACT_SIZE = (340, 340)   # default dropdown
LARGE_SIZE = (520, 600)     # after pressing the expand button
FLASH_SECONDS = 6
COPIED_GREEN_SECONDS = 2

CSS = b"""
.fn-dropdown { border: 1px solid alpha(@theme_fg_color, 0.18); border-radius: 10px;
               background-color: @theme_bg_color; }
.fn-tabs { margin: 6px 0 2px 6px; }
.fn-tabs button { padding: 2px 8px; min-height: 24px; }
.fn-status { font-size: smaller; opacity: 0.75; }
.fn-num { opacity: 0.55; }
.fn-date { opacity: 0.55; font-size: smaller; }
.fn-row { padding: 6px 6px 2px 10px; }
.fn-actions button { min-height: 20px; min-width: 20px; padding: 1px 4px; }
.fn-actions .fn-move { font-size: smaller; }
.fn-rule { opacity: 0.35; margin: 0 4px; }
.fn-pending { opacity: 0.6; font-style: italic; }
.fn-hint { opacity: 0.6; padding: 24px; }
.fn-section { font-weight: bold; opacity: 0.8; margin: 10px 10px 2px 10px; }
.fn-placeholder { opacity: 0.5; }
.fn-chip { background-color: alpha(@theme_fg_color, 0.09); border-radius: 14px; padding: 0 2px 0 10px; }
.fn-chip button { min-height: 22px; min-width: 22px; padding: 0; }
.fn-chip-arrow { opacity: 0.55; }
.fn-error { color: #ff6b6b; }
.fn-preview { font-family: monospace; font-size: smaller; opacity: 0.8;
              background-color: alpha(@theme_fg_color, 0.06); border-radius: 6px; padding: 6px 8px; }
.fn-guide-title { font-size: larger; font-weight: bold; }
.fn-key { font-weight: bold; }
.fn-project { font-weight: bold; }
.fn-menu-item { padding: 4px 10px; }
.fn-subtabs button { padding: 1px 10px; min-height: 22px; font-size: smaller; }
.fn-top-btn { padding: 3px; min-width: 22px; min-height: 22px; }
"""


def _idle(fn, *args):
    """Run fn on the GTK main thread, once."""
    def call():
        fn(*args)
        return GLib.SOURCE_REMOVE
    GLib.idle_add(call)


def _shrinkable(view: Gtk.TextView) -> Gtk.Widget:
    """Wrap a wrapping TextView so it never holds the window wide.

    GTK3 reports a wrapped TextView's current width as its minimum width, so
    after the dropdown was large it could not shrink back (only the height did).
    EXTERNAL keeps the width out of the size request without a scrollbar.
    """
    scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                                vscrollbar_policy=Gtk.PolicyType.NEVER)
    scroll.add(view)
    return scroll


def _icon_button(icon: str, tooltip: str, callback) -> Gtk.Button:
    b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.set_tooltip_text(tooltip)
    b.set_valign(Gtk.Align.START)
    b.set_can_focus(False)
    b.connect("clicked", lambda *_: callback())
    return b


def _hint(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, justify=Gtk.Justification.CENTER, wrap=True, max_width_chars=1)
    label.get_style_context().add_class("fn-hint")
    label.show()
    return label


def _scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    sw.add(child)
    return sw


def _clear(listbox: Gtk.ListBox) -> None:
    for child in listbox.get_children():
        listbox.remove(child)


class NoteRow(Gtk.ListBoxRow):
    """One note: a leading widget (number, checkbox or icon), the text across the
    full width, and under it a line of actions: [date] ───── ✎ … 🗑.

    Double-click the text or press the pencil to edit in a wrapping text box.
    Enter saves, Shift+Enter adds a line break, Esc cancels.
    """

    def __init__(self, note, lead: Gtk.Widget, *, on_save, on_delete, on_edit_state,
                 extra_buttons=(), subtitle: str | None = None):
        super().__init__(activatable=False, selectable=False)
        self.note = note
        self._on_save = on_save
        self._on_edit_state = on_edit_state

        box = Gtk.Box(spacing=6)
        box.get_style_context().add_class("fn-row")
        lead.set_valign(Gtk.Align.START)
        box.pack_start(lead, False, False, 0)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.pack_start(column, True, True, 0)

        self.label = Gtk.Label(label=note.text, xalign=0, wrap=True, hexpand=True,
                               wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=1)
        if note.done:
            self.label.set_markup(f"<s>{GLib.markup_escape_text(note.text)}</s>")
        view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        view.pack_start(self.label, False, False, 0)
        clicks = Gtk.EventBox()
        clicks.add(view)
        clicks.connect("button-press-event", self._on_click)

        # Multi-line editor: wraps like the label, grows with the text.
        self.editor = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, hexpand=True,
                                   left_margin=6, right_margin=6, top_margin=4, bottom_margin=4)
        self.editor.connect("key-press-event", self._on_key)
        frame = Gtk.Frame()
        frame.add(_shrinkable(self.editor))

        self.stack = Gtk.Stack(hexpand=True, vhomogeneous=False, interpolate_size=True)
        self.stack.add_named(clicks, "view")
        self.stack.add_named(frame, "edit")
        column.pack_start(self.stack, False, False, 0)

        # Actions under the text, so the text gets the full width.
        actions = Gtk.Box(spacing=0)
        actions.get_style_context().add_class("fn-actions")
        if subtitle:
            sub = Gtk.Label(label=subtitle, xalign=0, valign=Gtk.Align.CENTER)
            sub.get_style_context().add_class("fn-date")
            actions.pack_start(sub, False, False, 0)
        rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, valign=Gtk.Align.CENTER)
        rule.get_style_context().add_class("fn-rule")
        actions.pack_start(rule, True, True, 0)
        self.edit_btn = _icon_button("document-edit-symbolic", "Edit", self.toggle_edit)
        for b in (self.edit_btn, *extra_buttons,
                  _icon_button("user-trash-symbolic", "Delete", lambda: on_delete(note))):
            b.set_valign(Gtk.Align.CENTER)
            actions.pack_start(b, False, False, 0)
        column.pack_start(actions, False, False, 0)
        self.add(box)

    @property
    def editing(self) -> bool:
        return self.stack.get_visible_child_name() == "edit"

    def _on_click(self, _widget, event):
        if event.type == Gdk.EventType._2BUTTON_PRESS:
            self.start_edit()
        return False

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.finish_edit(save=False)
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not event.state & Gdk.ModifierType.SHIFT_MASK:
            self.finish_edit(save=True)
            return True
        return False

    def toggle_edit(self):
        if self.editing:
            self.finish_edit(save=True)
        else:
            self.start_edit()

    def start_edit(self):
        buf = self.editor.get_buffer()
        buf.set_text(self.note.text)
        self.stack.set_visible_child_name("edit")
        self.edit_btn.set_image(Gtk.Image.new_from_icon_name("object-select-symbolic", Gtk.IconSize.BUTTON))
        self.edit_btn.set_tooltip_text("Save (Enter)")
        self._on_edit_state(self, True)
        self.editor.grab_focus()
        buf.place_cursor(buf.get_end_iter())

    def finish_edit(self, save: bool):
        if not self.editing:
            return
        buf = self.editor.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        self.stack.set_visible_child_name("view")
        self.edit_btn.set_image(Gtk.Image.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON))
        self.edit_btn.set_tooltip_text("Edit")
        changed = save and text and text != self.note.text
        if changed:
            self.label.set_text(text)
        self._on_edit_state(self, False)
        if changed:
            self._on_save(self.note, text)


class MultiEntry(Gtk.Overlay):
    """Multi-line text box with a placeholder. Enter submits, Shift+Enter adds a line."""

    def __init__(self, placeholder: str, on_submit):
        super().__init__(margin=6)
        self._on_submit = on_submit
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False,
                                 left_margin=6, right_margin=6, top_margin=5, bottom_margin=5)
        self.view.set_size_request(-1, 44)
        self.view.connect("key-press-event", self._on_key)
        frame = Gtk.Frame()
        frame.add(_shrinkable(self.view))
        self.add(frame)
        self.placeholder = Gtk.Label(label=placeholder, xalign=0, yalign=0, wrap=True, max_width_chars=1,
                                     hexpand=True, margin_start=8, margin_top=5, margin_end=8)
        self.placeholder.get_style_context().add_class("fn-placeholder")
        self.add_overlay(self.placeholder)
        self.set_overlay_pass_through(self.placeholder, True)
        self.view.get_buffer().connect("changed", lambda *_: self._sync_placeholder())

    def _sync_placeholder(self):
        self.placeholder.set_visible(self.view.get_buffer().get_char_count() == 0)

    def _on_key(self, _widget, event):
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not event.state & Gdk.ModifierType.SHIFT_MASK:
            buf = self.view.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
            if text:
                self._on_submit(text)
                buf.set_text("")
            return True
        return False


def _pending_row(in_progress: bool = True) -> Gtk.Widget:
    """A recording that isn't text yet: the one being transcribed, or one waiting."""
    row = Gtk.Box(spacing=8, margin=8)
    spinner = Gtk.Spinner()
    if in_progress:
        spinner.start()
    label = Gtk.Label(label="Transcribing…" if in_progress else "Waiting…", xalign=0)
    label.get_style_context().add_class("fn-pending")
    row.pack_start(spinner, False, False, 0)
    row.pack_start(label, True, True, 0)
    return row


def _chip(parts: list[str], on_delete) -> Gtk.Widget:
    """A rounded tag: 'whitetail → Wagtail ✕' (parts joined with an arrow)."""
    box = Gtk.Box(spacing=4, halign=Gtk.Align.START)
    box.get_style_context().add_class("fn-chip")
    for i, part in enumerate(parts):
        if i:
            arrow = Gtk.Label(label="→")
            arrow.get_style_context().add_class("fn-chip-arrow")
            box.pack_start(arrow, False, False, 0)
        box.pack_start(Gtk.Label(label=part), False, False, 0)
    remove = _icon_button("window-close-symbolic", "Remove", on_delete)
    remove.set_valign(Gtk.Align.CENTER)
    box.pack_start(remove, False, False, 0)
    return box


def _chips_box() -> Gtk.FlowBox:
    return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False, margin=6,
                       row_spacing=6, column_spacing=6, max_children_per_line=30,
                       valign=Gtk.Align.START)


def _word_row(text: str, on_delete) -> Gtk.ListBoxRow:
    row = Gtk.ListBoxRow(activatable=False, selectable=False)
    box = Gtk.Box(spacing=6)
    box.get_style_context().add_class("fn-row")
    box.pack_start(Gtk.Label(label=text, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END),
                   True, True, 0)
    box.pack_start(_icon_button("user-trash-symbolic", "Remove", on_delete), False, False, 0)
    row.add(box)
    return row


class Dropdown(Gtk.Window):
    """Borderless panel that opens next to the panel (tray) icon.

    Opens on a click on the icon, Ctrl+Super+Alt+N, or at login. Closes when
    you click anywhere else, press Esc, or click the icon again.
    """

    def __init__(self, app):
        super().__init__(title="FloatNote")
        self.app = app
        self._editing: NoteRow | None = None
        self._dirty = False
        self._flash = ""
        self._flash_until = 0.0
        self._tick_id = 0
        self._hidden_at = 0.0
        self._dialog_open = False
        self._suggestion: tuple[str, str] | None = None
        self._had_focus = False       # only close on focus loss after we really had it
        self._closed_by_focus_at = 0.0
        self._capturing: str | None = None  # shortcut waiting for new keys
        self._window_capture = False  # capturing from this window's key presses
        self._click: tuple[int | None, int | None] = (None, None)  # last tray click
        self._last_side: str | None = None  # panel side of the last usable tray click

        self.set_decorated(False)
        self._expanded = bool(app.settings.get("expanded"))
        self.set_default_size(*self._size())
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_icon_name("audio-input-microphone")
        self.connect("delete-event", lambda *_: self.close_dropdown() or True)
        self.connect("focus-out-event", self._on_focus_out)
        self.connect("focus-in-event", self._on_focus_in)
        # Window managers keep the top-left corner when a window shrinks; re-snap.
        self.connect("configure-event", lambda *_: _idle(self._snap_to_anchor) or False)
        self.connect("key-press-event", self._on_key)

        # Rounded corners need an RGBA visual (most desktops; falls back to square).
        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
            self.set_app_paintable(True)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_titled(self._build_bugs_page(), "bugs", "Bugs")
        self.stack.add_titled(self._build_todo_page(), "todo", "To-do")
        self.stack.add_titled(self._build_dictation_page(), "dictation", "Dictation")
        self.stack.add_titled(self._build_projects_page(), "projects", "Projects")
        self.stack.add_named(self._build_settings_page(), "settings")
        self.stack.add_named(self._build_guide_page(), "guide")
        self.stack.connect("notify::visible-child-name", lambda *_: self._on_tab_changed())

        # Linked buttons instead of Gtk.StackSwitcher: each tab only as wide as
        # its label, so the compact dropdown stays narrow.
        tabs = Gtk.Box(halign=Gtk.Align.START, hexpand=True)
        tabs.get_style_context().add_class("linked")
        tabs.get_style_context().add_class("fn-tabs")
        self._tab_buttons: dict[str, Gtk.RadioButton] = {}
        group = None
        for name, title in self.TABS:
            b = Gtk.RadioButton(group=group, label=title, draw_indicator=False)
            b.set_can_focus(False)
            b.connect("toggled", lambda btn, n=name: btn.get_active() and self.stack.set_visible_child_name(n))
            group = group or b
            self._tab_buttons[name] = b
            tabs.pack_start(b, False, False, 0)
        self.expand_btn = _icon_button("view-fullscreen-symbolic", "Make bigger", self._toggle_size)
        self.expand_btn.set_valign(Gtk.Align.CENTER)
        self._no_tab = Gtk.RadioButton(group=group)  # active while Settings/Guide is shown
        self.help_btn = _icon_button("help-about-symbolic", "How FloatNote works", lambda: self._show_page("guide"))
        self.settings_btn = _icon_button("emblem-system-symbolic", "Settings", lambda: self._show_page("settings"))
        self.power_btn = self._build_power_button()
        for b in (self.help_btn, self.settings_btn, self.power_btn, self.expand_btn):
            b.set_valign(Gtk.Align.CENTER)
            b.get_style_context().add_class("fn-top-btn")
        top = Gtk.Box()
        top.pack_start(tabs, True, True, 0)
        top.pack_end(self.expand_btn, False, False, 4)
        top.pack_end(self.power_btn, False, False, 0)
        top.pack_end(self.settings_btn, False, False, 0)
        top.pack_end(self.help_btn, False, False, 0)
        self.status = Gtk.Label(xalign=1, margin_end=10, ellipsize=Pango.EllipsizeMode.END,
                                max_width_chars=1, hexpand=True)
        self.status.get_style_context().add_class("fn-status")
        # Project selector: "General · 2 ▾" opens a list of projects.
        self.project_btn = Gtk.MenuButton(relief=Gtk.ReliefStyle.NONE, margin_start=4)
        self.project_btn.set_tooltip_text("Active project: new bugs go here")
        self.project_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
        self.project_label.get_style_context().add_class("fn-project")
        btn_box = Gtk.Box(spacing=4)
        btn_box.pack_start(self.project_label, False, False, 0)
        btn_box.pack_start(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        self.project_btn.add(btn_box)
        self.project_popover = Gtk.Popover()
        self.project_popover.connect("show", lambda *_: self._fill_project_menu())
        self.project_btn.set_popover(self.project_popover)
        status_row = Gtk.Box(spacing=4, margin_bottom=2)
        status_row.pack_start(self.project_btn, False, False, 0)
        status_row.pack_start(self.status, True, True, 0)

        # "Always fix X -> Y?" offer after editing a note.
        self.suggest_bar = Gtk.InfoBar(message_type=Gtk.MessageType.QUESTION, show_close_button=False)
        self.suggest_label = Gtk.Label(xalign=0, wrap=True, hexpand=True, max_width_chars=1,
                                       wrap_mode=Pango.WrapMode.WORD_CHAR)
        self.suggest_bar.get_content_area().add(self.suggest_label)
        self.suggest_bar.add_button("Always fix", 1)
        self.suggest_bar.add_button("No", 0)
        self.suggest_bar.connect("response", self._on_suggest_response)

        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.get_style_context().add_class("fn-dropdown")
        frame.pack_start(top, False, False, 0)
        frame.pack_start(status_row, False, False, 0)
        frame.pack_start(Gtk.Separator(), False, False, 0)
        frame.pack_start(self.suggest_bar, False, False, 0)
        frame.pack_start(self._build_permission_bar(), False, False, 0)
        frame.pack_start(self.stack, True, True, 0)
        self.add(frame)
        frame.show_all()
        self.suggest_bar.hide()  # shown when there's a fix to offer
        self.perm_bar.hide()     # shown when hold-to-record lacks permission
        self.apply_features()    # hide the To-do / Dictation tabs when switched off
        self._sync_expand_button()

    # ---- pages ------------------------------------------------------------

    TABS = [("bugs", "Bugs"), ("todo", "To-do"), ("dictation", "Dictation"), ("projects", "Projects")]
    OPTIONAL_TABS = {"todo": "todo_enabled", "dictation": "dictation_enabled"}

    def apply_features(self):
        """Show only the tabs (and key rows) of the parts that are switched on."""
        cfg = self.app.daemon.cfg
        for name, option in self.OPTIONAL_TABS.items():
            on = getattr(cfg, option)
            self._tab_buttons[name].set_visible(on)
            self.stack.get_child_by_name(name).set_visible(on)
            if not on and self.stack.get_visible_child_name() == name:
                self._tab_buttons["bugs"].set_active(True)
        for which, row in getattr(self, "_key_rows", {}).items():
            row.set_visible(self.app.daemon.enabled(which))

    def _build_bugs_page(self) -> Gtk.Widget:
        self.bug_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.bug_hint = _hint("")  # text names the current keys: see _update_key_hints
        self.bug_list.set_placeholder(self.bug_hint)
        self.new_bug = MultiEntry("Type a bug and press Enter (Shift+Enter for a new line)", self._add_bug)
        self.bug_scroller = _scrolled(self.bug_list)

        self.copy_btn = Gtk.Button(label="Copy all")
        self.copy_btn.get_style_context().add_class("suggested-action")
        # Off the GTK thread: a hanging clipboard tool must not freeze the window.
        self.copy_btn.connect("clicked", lambda *_: threading.Thread(
            target=self.app.daemon.handle, args=({"cmd": "copy-all"},), daemon=True).start())
        footer = Gtk.Box(spacing=4, margin=6)
        footer.pack_start(_icon_button("edit-undo-symbolic", "Undo last copy/clear",
                                       lambda: self.app.daemon.handle({"cmd": "undo"})), False, False, 0)
        footer.pack_start(_icon_button("edit-clear-all-symbolic", "Clear list without copying",
                                       lambda: self.app.daemon.handle({"cmd": "clear"})), False, False, 0)
        footer.pack_end(self.copy_btn, False, False, 0)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.pack_start(self.new_bug, False, False, 0)
        page.pack_start(Gtk.Separator(), False, False, 0)
        page.pack_start(self.bug_scroller, True, True, 0)
        page.pack_start(Gtk.Separator(), False, False, 0)
        page.pack_start(footer, False, False, 0)
        return page

    def _build_todo_page(self) -> Gtk.Widget:
        self.new_todo = MultiEntry("Type a to-do and press Enter (Shift+Enter for a new line)", self._add_todo)

        self.todo_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.todo_hint = _hint("")
        self.todo_list.set_placeholder(self.todo_hint)

        self.show_done = Gtk.CheckButton(label="Show done")
        self.show_done.connect("toggled", lambda *_: self.refresh())
        footer = Gtk.Box(spacing=4, margin=6)
        footer.pack_start(self.show_done, False, False, 0)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.pack_start(self.new_todo, False, False, 0)
        page.pack_start(Gtk.Separator(), False, False, 0)
        page.pack_start(_scrolled(self.todo_list), True, True, 0)
        page.pack_start(Gtk.Separator(), False, False, 0)
        page.pack_start(footer, False, False, 0)
        return page

    def _build_dictation_page(self) -> Gtk.Widget:
        self.dictation_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.dictation_hint = _hint("")
        self.dictation_list.set_placeholder(self.dictation_hint)
        clear = Gtk.Button(label="Clear history")
        clear.connect("clicked", lambda *_: self._clear_dictations())
        self.dictation_count = Gtk.Label(xalign=0)
        self.dictation_count.get_style_context().add_class("fn-date")
        footer = Gtk.Box(spacing=4, margin=6)
        footer.pack_start(self.dictation_count, True, True, 4)
        footer.pack_end(clear, False, False, 0)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.pack_start(_scrolled(self.dictation_list), True, True, 0)
        page.pack_start(Gtk.Separator(), False, False, 0)
        page.pack_start(footer, False, False, 0)
        return page

    def _build_words_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        def section(title, explain):
            label = Gtk.Label(label=title, xalign=0)
            label.get_style_context().add_class("fn-section")
            page.pack_start(label, False, False, 0)
            sub = Gtk.Label(label=explain, xalign=0, wrap=True, max_width_chars=1,
                            margin_start=10, margin_end=10)
            sub.get_style_context().add_class("fn-date")
            page.pack_start(sub, False, False, 0)

        section("Fix misheard words", "e.g. whitetail → Wagtail: whenever it hears the left word, it writes the right one.")
        self.fix_heard = Gtk.Entry(placeholder_text="it writes", hexpand=True, width_chars=5)
        self.fix_right = Gtk.Entry(placeholder_text="you said", hexpand=True, width_chars=5)
        add_fix = Gtk.Button(label="Add")
        add_fix.connect("clicked", lambda *_: self._add_fix())
        self.fix_right.connect("activate", lambda *_: self._add_fix())
        form = Gtk.Box(spacing=4, margin=6)
        form.pack_start(self.fix_heard, True, True, 0)
        form.pack_start(Gtk.Label(label="→"), False, False, 0)
        form.pack_start(self.fix_right, True, True, 0)
        form.pack_start(add_fix, False, False, 0)
        page.pack_start(form, False, False, 0)
        self.fix_list = _chips_box()
        self.fix_empty = _hint("No fixes yet. Tip: edit a note and FloatNote offers one.")
        page.pack_start(self.fix_list, False, False, 0)
        page.pack_start(self.fix_empty, False, False, 0)

        section("Hint words", "Names and tech terms, so they get spelled right in the first place.")
        self.hint_entry = Gtk.Entry(placeholder_text="Add a word and press Enter", margin=6)
        self.hint_entry.connect("activate", lambda *_: self._add_hint())
        page.pack_start(self.hint_entry, False, False, 0)
        self.hint_list = _chips_box()
        page.pack_start(self.hint_list, False, False, 0)
        return page  # placed inside Settings → Words, which scrolls

    # ---- settings page ------------------------------------------------------

    KEY_ROWS = [("bug", "Record a bug", "hold"), ("todo", "Record a to-do", "hold"),
                ("dictation", "Dictate (copied to the clipboard)", "hold"),
                ("copy", "Copy all bugs", "press, let go"), ("toggle", "Open / close", "press"),
                ("next", "Next project", "press")]

    WINDOW_KEYS = ("toggle", "next")  # can be captured without keyboard access
    LENGTHS = (60, 180, 300, 600)    # choices for the longest recording, in seconds

    SETTINGS_TABS = [("keys", "Keys", "Click Change, hold the new keys together, let go."),
                     ("copy", "Copy", "The first line of what Copy all puts on the clipboard."),
                     ("speech", "Speech", "Which speech model turns your voice into text."),
                     ("words", "Words", ""),
                     ("general", "General", "")]

    def _build_settings_page(self) -> Gtk.Widget:
        # Sub-tabs inside Settings: Keys | Copy | Speech | General
        self.settings_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        bar = Gtk.Box(halign=Gtk.Align.START, margin_start=10, margin_top=6, margin_bottom=2)
        bar.get_style_context().add_class("linked")
        bar.get_style_context().add_class("fn-subtabs")
        pages, group = {}, None
        self.settings_tab_buttons: dict[str, Gtk.RadioButton] = {}
        for name, title, explain in self.SETTINGS_TABS:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            if explain:
                intro = Gtk.Label(label=explain, xalign=0, wrap=True, max_width_chars=1,
                                  margin_start=10, margin_end=10, margin_top=8, margin_bottom=4)
                intro.get_style_context().add_class("fn-date")
                box.pack_start(intro, False, False, 0)
            self.settings_stack.add_named(_scrolled(box), name)
            pages[name] = box
            b = Gtk.RadioButton(group=group, label=title, draw_indicator=False)
            b.set_can_focus(False)
            b.connect("toggled", lambda btn, n=name: btn.get_active()
                      and self.settings_stack.set_visible_child_name(n))
            group = group or b
            self.settings_tab_buttons[name] = b
            bar.pack_start(b, False, False, 0)

        pages["words"].pack_start(self._build_words_page(), False, False, 0)
        page = pages["keys"]
        self._key_values: dict[str, Gtk.Label] = {}
        self._key_buttons: dict[str, Gtk.Button] = {}
        self._key_rows: dict[str, Gtk.Widget] = {}
        for which, title, how in self.KEY_ROWS:
            # Two lines per shortcut so it fits the compact dropdown:
            #   Record a bug (hold)          [Change]
            #   Ctrl+Super
            name = Gtk.Label(xalign=0, hexpand=True)
            name.set_markup(f"{title} <span alpha='60%'>({how})</span>")
            value = Gtk.Label(xalign=0)
            value.get_style_context().add_class("fn-key")
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            texts.pack_start(name, False, False, 0)
            texts.pack_start(value, False, False, 0)
            button = Gtk.Button(label="Change", valign=Gtk.Align.CENTER)
            button.connect("clicked", lambda _b, w=which: self._on_change_clicked(w))
            row = Gtk.Box(spacing=8, margin_start=10, margin_end=8, margin_top=3)
            row.pack_start(texts, True, True, 0)
            row.pack_end(button, False, False, 0)
            page.pack_start(row, False, False, 0)
            self._key_rows[which] = row
            self._key_values[which] = value
            self._key_buttons[which] = button
        self.key_error = Gtk.Label(xalign=0, wrap=True, max_width_chars=1, margin_start=10, margin_end=10)
        self.key_error.get_style_context().add_class("fn-error")
        page.pack_start(self.key_error, False, False, 0)

        page = pages["copy"]
        # Multi-line, wrapping box (the heading can be a sentence or two).
        self.heading_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False,
                                         left_margin=6, right_margin=6, top_margin=5, bottom_margin=5)
        self.heading_view.set_size_request(-1, 48)
        self.heading_view.get_buffer().connect("changed", lambda *_: self._heading_changed())
        heading_frame = Gtk.Frame(margin_start=8, margin_end=8)
        heading_frame.add(_shrinkable(self.heading_view))
        page.pack_start(heading_frame, False, False, 0)
        hint = Gtk.Label(label="Leave empty to copy just the numbered list.", xalign=0,
                         margin_start=10, wrap=True, max_width_chars=1)
        hint.get_style_context().add_class("fn-date")
        page.pack_start(hint, False, False, 0)
        self.heading_preview = Gtk.Label(xalign=0, yalign=0, wrap=True, max_width_chars=1, margin=8, selectable=False)
        self.heading_preview.get_style_context().add_class("fn-preview")
        page.pack_start(self.heading_preview, False, False, 0)
        self._heading_timer = 0

        page = pages["speech"]
        self._model_buttons: dict[str, Gtk.RadioButton] = {}
        group = None  # model radio group
        for name, about in (("small.en", "accurate, ~1.5 s per 10 s of speech"),
                            ("base.en", "fastest, more misheard words")):
            b = Gtk.RadioButton(group=group, label=f"{name}: {about}", margin_start=8, margin_top=4)
            b.get_child().set_line_wrap(True)
            b.get_child().set_max_width_chars(1)
            b.connect("toggled", lambda btn, n=name: btn.get_active() and not self._loading_settings
                      and self.app.daemon.set_model(n))
            group = group or b
            self._model_buttons[name] = b
            page.pack_start(b, False, False, 0)

        length = Gtk.Label(label="Longest recording", xalign=0)
        length.get_style_context().add_class("fn-section")
        page.pack_start(length, False, False, 0)
        about = Gtk.Label(label="Recording stops by itself after this. Longer notes take longer to "
                                "turn into text (about 1 s per 10 s of speech).",
                          xalign=0, wrap=True, max_width_chars=1, margin_start=10, margin_end=10)
        about.get_style_context().add_class("fn-date")
        page.pack_start(about, False, False, 0)
        self.length_combo = Gtk.ComboBoxText(margin_start=10, margin_top=4, halign=Gtk.Align.START)
        for seconds in self.LENGTHS:
            self.length_combo.append(str(seconds), f"{seconds // 60} minute{'s' if seconds > 60 else ''}")
        self.length_combo.connect("changed", lambda c: not self._loading_settings and c.get_active_id()
                                  and self.app.daemon.set_option("max_record_seconds", int(c.get_active_id())))
        page.pack_start(self.length_combo, False, False, 0)

        page = pages["general"]
        self.sounds_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.sounds_switch.connect("notify::active", lambda sw, _p: not self._loading_settings
                                   and self.app.daemon.set_option("sounds", sw.get_active()))
        self.bar_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.bar_switch.connect("notify::active", lambda sw, _p: not self._loading_settings
                                and self._set_bar_label(sw.get_active()))
        self.login_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.login_switch.connect("notify::active", lambda sw, _p: not self._loading_settings
                                  and self.app.daemon.set_option("home_on_login", sw.get_active()))
        self.todo_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.todo_switch.connect("notify::active", lambda sw, _p: not self._loading_settings
                                 and self._set_feature("todo_enabled", sw.get_active()))
        self.dictation_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.dictation_switch.connect("notify::active", lambda sw, _p: not self._loading_settings
                                      and self._set_feature("dictation_enabled", sw.get_active()))
        for label, about, switch in (
                ("To-do list", "Hold the to-do keys to add one; tick them off when done.", self.todo_switch),
                ("Dictation", "Hold the dictation keys and talk: the text is copied, "
                              "ready to paste into any app.", self.dictation_switch),
                ("Show the project on the panel icon", "", self.bar_switch),
                ("Start / stop sounds", "", self.sounds_switch),
                ("Show to-dos at login", "", self.login_switch)):
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            texts.pack_start(Gtk.Label(label=label, xalign=0, wrap=True, max_width_chars=1), False, False, 0)
            if about:
                sub = Gtk.Label(label=about, xalign=0, wrap=True, max_width_chars=1)
                sub.get_style_context().add_class("fn-date")
                texts.pack_start(sub, False, False, 0)
            row = Gtk.Box(spacing=8, margin_start=10, margin_end=10, margin_top=8)
            row.pack_start(texts, True, True, 0)
            row.pack_end(switch, False, False, 0)
            page.pack_start(row, False, False, 0)

        guide = Gtk.Button(label="Show the guide", margin=10, halign=Gtk.Align.START)
        guide.connect("clicked", lambda *_: self._show_page("guide"))
        page.pack_start(guide, False, False, 0)
        self._loading_settings = False

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.pack_start(bar, False, False, 0)
        outer.pack_start(self.settings_stack, True, True, 0)
        return outer

    def _load_settings_page(self):
        cfg = self.app.daemon.cfg
        self._loading_settings = True
        try:
            self._show_keys()
            self.key_error.set_text("")
            self.heading_view.get_buffer().set_text(cfg.copy_intro)
            self._update_heading_preview()
            if cfg.model in self._model_buttons:
                self._model_buttons[cfg.model].set_active(True)
            self.sounds_switch.set_active(cfg.sounds)
            self.bar_switch.set_active(cfg.show_project_in_bar)
            self.login_switch.set_active(cfg.home_on_login)
            self.todo_switch.set_active(cfg.todo_enabled)
            if str(cfg.max_record_seconds) not in map(str, self.LENGTHS):  # a custom value from config.toml
                self.length_combo.append(str(cfg.max_record_seconds), f"{cfg.max_record_seconds} seconds")
            self.length_combo.set_active_id(str(cfg.max_record_seconds))
            self.dictation_switch.set_active(cfg.dictation_enabled)
        finally:
            self._loading_settings = False

    def _show_keys(self):
        from .hotkeys import pretty_combo

        from .daemon import KEY_FIELDS

        cfg = self.app.daemon.cfg
        values = {which: getattr(cfg, field) for which, field in KEY_FIELDS.items()}
        for which, label in self._key_values.items():
            label.set_text(pretty_combo(values[which]))
        # Without keyboard access the hold keys can't work (or be captured);
        # open/close and next project are captured in this window instead.
        reads_keyboard = self.app.daemon.can_capture_keys()
        for which, b in self._key_buttons.items():
            b.set_label("Change")
            b.set_sensitive(reads_keyboard or which in self.WINDOW_KEYS)
        if not reads_keyboard and self._capturing is None:
            self._key_message("Turn on keyboard access (the bar at the top) to use and change "
                              "the hold keys.")

    def _on_change_clicked(self, which: str):
        if self._capturing == which:
            self._cancel_capture()  # the button reads "Cancel" while capturing
        else:
            self._start_capture(which)

    def _start_capture(self, which: str):
        self._capturing = which
        for w, b in self._key_buttons.items():
            b.set_sensitive(w == which)
        self._key_buttons[which].set_label("Cancel")
        self._key_values[which].set_text("Press the new keys…")
        if self.app.daemon.can_capture_keys():
            self._window_capture = False
            self._key_message("Hold the new keys together, then let go. Esc or Cancel keeps the old ones.")
            self.app.daemon.capture_keys(lambda names, err: _idle(self._captured, which, names, err))
        else:  # no keyboard access: read the keys from this window
            self._window_capture = True
            self._key_message("Press the new keys together. Esc or Cancel keeps the old ones.")

    def _capture_in_window(self, event) -> bool:
        """Key press while capturing in this window. Returns True if handled."""
        if event.keyval == Gdk.KEY_Escape:
            self._captured(self._capturing, None, None)
            return True
        # The key as if no modifier was held (Shift+1 -> 1, not !).
        keymap = Gdk.Keymap.get_for_display(self.get_display())
        ok, keyval, *_ = keymap.translate_keyboard_state(event.hardware_keycode, 0, event.group)
        name = (Gdk.keyval_name(Gdk.keyval_to_lower(keyval if ok else event.keyval)) or "").lower()
        if name.split("_")[0] in ("control", "alt", "super", "shift", "meta", "hyper") \
                or name.startswith(("iso_level", "iso_group")):
            return True  # a modifier on its own: wait for the real key
        state = event.state
        names = {mod for mod, mask in (("ctrl", Gdk.ModifierType.CONTROL_MASK),
                                       ("alt", Gdk.ModifierType.MOD1_MASK),
                                       ("super", Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.MOD4_MASK),
                                       ("shift", Gdk.ModifierType.SHIFT_MASK)) if state & mask}
        from .hotkeys import NAMED_KEYS

        if name not in NAMED_KEYS.values():
            self._captured(self._capturing, None, "That key can't be used; try letters, numbers, arrows or F-keys.")
        else:
            self._captured(self._capturing, frozenset(names | {name}), None)
        return True

    def _cancel_capture(self):
        if not self._window_capture:
            self.app.daemon.cancel_capture()
        self._capturing = None
        self._show_keys()
        self._key_message("Kept the old shortcut.")

    def _captured(self, which, names, error):
        from .hotkeys import format_combo, pretty_combo

        if self._capturing != which:
            return  # already cancelled from the button
        self._capturing = None
        if names is None and error is None:  # cancelled with Esc
            self._show_keys()
            self._key_message("Kept the old shortcut.")
            return
        if error is None:
            combo = format_combo(names)
            error = self.app.daemon.set_keys(which, combo)
            if error is None:
                self.flash(f"Shortcut saved: {pretty_combo(combo)}")
        self._show_keys()
        self._key_message(error or "", error=True)
        self.refresh()

    def _key_message(self, text: str, error: bool = False):
        ctx = self.key_error.get_style_context()
        (ctx.add_class if error else ctx.remove_class)("fn-error")
        if not error:
            ctx.add_class("fn-date")
        else:
            ctx.remove_class("fn-date")
        self.key_error.set_text(text)

    def _set_feature(self, option: str, on: bool):
        self.app.daemon.set_option(option, on)
        self.apply_features()
        name = {"todo_enabled": "To-do list", "dictation_enabled": "Dictation"}[option]
        self.flash(f"{name} {'on' if on else 'off'}")
        self.refresh()

    def _set_bar_label(self, on: bool):
        self.app.daemon.set_option("show_project_in_bar", on)
        self.app._update_indicators()

    def _heading_changed(self):
        self._update_heading_preview()
        if self._loading_settings:
            return
        if self._heading_timer:
            GLib.source_remove(self._heading_timer)
        self._heading_timer = GLib.timeout_add(600, self._save_heading)

    def _save_heading(self):
        self._heading_timer = 0
        self.app.daemon.set_option("copy_intro", self._heading_text())
        return GLib.SOURCE_REMOVE

    def _update_heading_preview(self):
        from .store import Note, format_paste

        sample = [Note(0, "bug", t, "", None, False, None, None, None)
                  for t in ("The navbar overlaps the logo on mobile.", "Submit does nothing.")]
        self.heading_preview.set_text(format_paste(self._heading_text(), sample).rstrip())

    def _heading_text(self) -> str:
        buf = self.heading_view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()

    # ---- guide --------------------------------------------------------------

    def _build_guide_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=12, spacing=8)
        self.guide_counter = Gtk.Label(xalign=0)
        self.guide_counter.get_style_context().add_class("fn-date")
        self.guide_title = Gtk.Label(xalign=0, wrap=True, max_width_chars=1)
        self.guide_title.get_style_context().add_class("fn-guide-title")
        self.guide_body = Gtk.Label(xalign=0, yalign=0, wrap=True, max_width_chars=1, vexpand=True)
        self.guide_back = Gtk.Button(label="Back")
        self.guide_back.connect("clicked", lambda *_: self._guide_step(self._guide_index - 1))
        self.guide_next = Gtk.Button(label="Next")
        self.guide_next.get_style_context().add_class("suggested-action")
        self.guide_next.connect("clicked", lambda *_: self._guide_next())
        skip = Gtk.Button(label="Skip")
        skip.set_relief(Gtk.ReliefStyle.NONE)
        skip.connect("clicked", lambda *_: self._guide_done())
        buttons = Gtk.Box(spacing=6)
        buttons.pack_start(skip, False, False, 0)
        buttons.pack_end(self.guide_next, False, False, 0)
        buttons.pack_end(self.guide_back, False, False, 0)
        page.pack_start(self.guide_counter, False, False, 0)
        page.pack_start(self.guide_title, False, False, 0)
        page.pack_start(self.guide_body, True, True, 0)
        page.pack_start(buttons, False, False, 0)
        self._guide_index = 0
        return _scrolled(page)

    def _guide_steps(self) -> list[tuple[str, str]]:
        from .hotkeys import pretty_combo

        cfg = self.app.daemon.cfg

        def key(text):
            return f"<b>{GLib.markup_escape_text(pretty_combo(text))}</b>"

        return [
            ("Record a bug by voice",
             f"Hold {key(cfg.hold_bug)}, describe what's wrong, then let go.\n\n"
             "The mic icon in your panel turns <b>red</b> while recording and <b>yellow</b> while "
             "it writes the text. The note lands in the <b>Bugs</b> tab.\n\n"
             "Long note? <b>Tap the keys twice</b> to record hands-free, and tap them once more to stop. "
             "This works for to-dos and dictation too."),
            ("Add a to-do",
             f"Hold {key(cfg.hold_todo)} and say what you want to do. The icon turns <b>blue</b>.\n\n"
             "To-dos stay in the <b>To-do</b> tab until you tick them done, and show up when you log in. "
             "Don't need them? Switch the list off in ⚙ Settings → General."),
            ("Dictate into any app",
             (f"Hold {key(cfg.hold_dictation)} and talk. The icon turns <b>purple</b>; let go and the "
              "text is copied, ready to paste into a chat, an email, anything. Past dictations are in "
              "the <b>Dictation</b> tab."
              if cfg.dictation_enabled else
              "Want to type by voice in other apps? Switch on <b>Dictation</b> in ⚙ Settings → General: "
              f"hold {key(cfg.hold_dictation)}, talk, let go, and the text is copied, ready to paste.")),
            ("Copy the bugs for Claude",
             f"Press {key(cfg.copy_keys)} together and let go. All bugs are copied as a numbered "
             "list and the icon flashes <b>green</b>. Paste them anywhere, e.g. into Claude Code.\n\n"
             "The list then starts fresh; the ↶ button brings the last batch back."),
            ("Projects",
             "Testing more than one app? Make a project for each in the <b>Projects</b> tab. "
             "New bugs go to the active project (shown at the top; click it to switch), "
             f"or press {key(cfg.next_project_keys)} to jump to the next one.\n\n"
             "Copy all only copies the active project's bugs. Link a code folder and Claude Code "
             "can read that project's bugs with <tt>floatnote list --take</tt> from that folder."),
            ("Fix words and find your way around",
             "Misheard a name? Edit the note and FloatNote offers to always fix that word. "
             "All fixes and hint words live in <b>⚙ Settings → Words</b>.\n\n"
             f"Open this dropdown by clicking the mic icon or with {key(cfg.toggle_keys)}. "
             "Shortcuts, the copy heading and the speech model are in ⚙ Settings too."),
        ]

    def _guide_step(self, index: int):
        steps = self._guide_steps()
        self._guide_index = max(0, min(index, len(steps) - 1))
        title, body = steps[self._guide_index]
        self.guide_counter.set_text(f"Step {self._guide_index + 1} of {len(steps)}")
        self.guide_title.set_text(title)
        self.guide_body.set_markup(body)
        self.guide_back.set_sensitive(self._guide_index > 0)
        last = self._guide_index == len(steps) - 1
        self.guide_next.set_label("Done" if last else "Next")

    def _guide_next(self):
        if self._guide_index >= len(self._guide_steps()) - 1:
            self._guide_done()
        else:
            self._guide_step(self._guide_index + 1)

    def _guide_done(self):
        self.app.settings["guide_seen"] = True
        self.app.save_settings()
        self._tab_buttons["bugs"].set_active(True)

    # ---- open / close -----------------------------------------------------

    def _on_tab_changed(self):
        name = self.stack.get_visible_child_name()
        if self._capturing is not None and name != "settings":
            self._cancel_capture()
        if name in self._tab_buttons and not self._tab_buttons[name].get_active():
            self._tab_buttons[name].set_active(True)  # tab chosen by code (e.g. at login)
        self.refresh()

    def _build_power_button(self) -> Gtk.MenuButton:
        """Restart / Quit, so a stuck FloatNote can be fixed without a terminal."""
        button = Gtk.MenuButton(relief=Gtk.ReliefStyle.NONE, tooltip_text="Restart or quit FloatNote")
        button.set_can_focus(False)
        button.add(Gtk.Image.new_from_icon_name("system-shutdown-symbolic", Gtk.IconSize.BUTTON))
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=6, spacing=2)
        self.power_warning = Gtk.Label(xalign=0, wrap=True, max_width_chars=28, margin=4)
        self.power_warning.get_style_context().add_class("fn-hint")
        box.pack_start(self.power_warning, False, False, 0)
        # Quit may first hand the open/close keys to the desktop (a second or two).
        quit_ = lambda: threading.Thread(target=self.app.daemon.quit, daemon=True).start()  # noqa: E731
        for label, action in (("Restart FloatNote", lambda: self.app.daemon.restart()),
                              ("Quit FloatNote", quit_)):
            item = Gtk.ModelButton(text=label)
            item.connect("clicked", lambda *_, a=action: GLib.idle_add(lambda: a() and False))
            box.pack_start(item, False, False, 0)
        box.show_all()
        popover.add(box)

        def on_show(*_):
            pending = self.app.daemon.ui_state()["pending"]
            self.power_warning.set_text(f"{pending} note(s) still transcribing: they'll be finished "
                                        "the next time FloatNote starts." if pending else "")
            self.power_warning.set_visible(bool(pending))

        popover.connect("show", on_show)
        button.set_popover(popover)
        return button

    def _show_page(self, name: str):
        """Show Settings or the Guide; pressing the same button again goes back to Bugs."""
        if self.stack.get_visible_child_name() == name:
            self._tab_buttons["bugs"].set_active(True)
            return
        if name == "settings":
            self._load_settings_page()
        else:
            self._guide_step(0)
        self._no_tab.set_active(True)
        self.stack.set_visible_child_name(name)

    def _size(self) -> tuple[int, int]:
        return LARGE_SIZE if self._expanded else COMPACT_SIZE

    def _toggle_size(self):
        self._expanded = not self._expanded
        self.app.settings["expanded"] = self._expanded
        self.app.save_settings()
        self._sync_expand_button()
        self._apply_geometry()

    def _sync_expand_button(self):
        icon = "view-restore-symbolic" if self._expanded else "view-fullscreen-symbolic"
        self.expand_btn.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
        self.expand_btn.set_tooltip_text("Make smaller" if self._expanded else "Make bigger")

    def open_dropdown(self, x: int | None = None, tab: str | None = None, y: int | None = None):
        if not self.app.settings.get("guide_seen"):
            tab = "guide"  # first time: explain how FloatNote works
        if tab in ("settings", "guide"):
            if self.stack.get_visible_child_name() != tab:
                self._show_page(tab)
        elif tab:
            self.stack.set_visible_child_name(tab)
        self._had_focus = False
        self._click = (x, y)  # where the tray icon was clicked (None: opened by a shortcut)
        self._apply_geometry()
        self.show()
        self.refresh()
        self._focus()

    def close_dropdown(self):
        if not self.get_visible():
            return
        if self._capturing is not None:
            self._cancel_capture()  # don't keep swallowing keys after the window is gone
        if self._editing is not None:
            self._editing.finish_edit(save=True)
        self._hidden_at = time.monotonic()
        self.hide()

    def toggle(self, x: int | None = None, y: int | None = None):
        # A click on the icon first takes focus away (which closes us), then
        # arrives as a toggle: don't reopen straight away in that case.
        if self.get_visible() or time.monotonic() - self._closed_by_focus_at < 0.5:
            self.close_dropdown()
        else:
            self.open_dropdown(x, y=y)

    def _target(self, size: tuple[int, int] | None = None) -> tuple[int, int]:
        """Where the dropdown goes: next to the tray icon, on the panel's side
        (see placement.py). Opened by a shortcut: the panel's corner."""
        from .placement import panel_side, place, usable_click

        display = Gdk.Display.get_default()
        x, y = self._click
        monitor = None
        if x is not None and y is not None:
            monitor = display.get_monitor_at_point(x, y)
        monitor = monitor or display.get_primary_monitor() or display.get_monitor(0)
        g, a = monitor.get_geometry(), monitor.get_workarea()
        geometry, area = (g.x, g.y, g.width, g.height), (a.x, a.y, a.width, a.height)
        click = usable_click(geometry, x, y)
        if click is not None:  # opened by a shortcut later: same panel as this click
            self._last_side = panel_side(geometry, area, click)
        return place(geometry, area, size or self._current_size(), click, self._last_side)

    def _current_size(self) -> tuple[int, int]:
        gdk_window = self.get_window()
        if gdk_window is not None and self.get_visible():
            return gdk_window.get_width(), gdk_window.get_height()
        return self._size()

    def _apply_geometry(self):
        """Size the dropdown and put it next to the tray icon."""
        w, h = self._size()
        self.resize(w, h)
        self.move(*self._target((w, h)))

    def _snap_to_anchor(self):
        """After a resize lands, keep the dropdown against the panel (window
        managers keep the top-left corner when a window shrinks)."""
        gdk_window = self.get_window()
        if not self.get_visible() or gdk_window is None:
            return
        _, x, y = gdk_window.get_origin()  # real position (get_position() can be stale)
        tx, ty = self._target()
        if abs(x - tx) > 1 or abs(y - ty) > 1:
            gdk_window.move(tx, ty)

    def _focus(self):
        # Take focus so clicking elsewhere closes the dropdown. Use the X server
        # time so the window manager treats it as a response to the user's action.
        try:
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11

            self.present_with_time(GdkX11.x11_get_server_time(self.get_window()))
        except (ImportError, ValueError, TypeError):
            self.present()

    def _on_focus_in(self, *_):
        self._had_focus = True
        return False

    def _on_focus_out(self, *_):
        # Ignore focus changes while the dropdown is still opening (the panel
        # click briefly keeps focus): only close once we really had focus.
        # X11 can also send brief focus-out/in pairs, so check a moment later.
        if self._had_focus:
            GLib.timeout_add(250, self._check_focus_lost)
        return False

    def _check_focus_lost(self):
        if self.get_visible() and not self.is_active() and not self._dialog_open:
            self._closed_by_focus_at = time.monotonic()
            self.close_dropdown()
        return GLib.SOURCE_REMOVE

    def _on_key(self, _widget, event):
        if self._capturing is not None and self._window_capture:
            return self._capture_in_window(event)
        if event.keyval == Gdk.KEY_Escape and self._editing is None:
            self.close_dropdown()
            return True
        return False

    def _edit_state(self, row: NoteRow, editing: bool) -> None:
        if editing:
            if self._editing is not None and self._editing is not row:
                self._editing.finish_edit(save=True)
            self._editing = row
        elif self._editing is row:
            self._editing = None
            if self._dirty:
                self._dirty = False
                _idle(self.refresh)

    # ---- content ----------------------------------------------------------

    def _build_permission_bar(self) -> Gtk.Widget:
        self.perm_bar = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING)
        label = Gtk.Label(label="Hold-to-record is off: FloatNote needs permission to see your keyboard.",
                          xalign=0, wrap=True, hexpand=True, max_width_chars=1)
        self.perm_bar.get_content_area().add(label)
        self.perm_bar.add_button("Turn on…", 1)
        self.perm_bar.connect("response", lambda *_: self._ask_hold_permission())
        return self.perm_bar

    def _ask_hold_permission(self):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE, text="Turn on hold-to-record?")
        dialog.format_secondary_text(
            "Linux desktops don't tell apps when a shortcut is released, and each desktop handles "
            "shortcuts its own way, so FloatNote reads the keyboard directly. That needs your user "
            "in the 'input' group (your password is asked next).\n\n"
            "FloatNote only looks at its own shortcut keys and never stores what you type, but any program you "
            "run could then read keystrokes. You can undo it any time with:\n"
            "sudo gpasswd -d $USER input")
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Turn on", Gtk.ResponseType.OK)

        def answered(response):
            if response == Gtk.ResponseType.OK:
                self.flash("Waiting for your password…")
                threading.Thread(target=self._enable_hold_keys, daemon=True).start()

        self._run_dialog(dialog, answered)

    def _enable_hold_keys(self):  # worker thread: pkexec waits for the password dialog
        ok, message = self.app.daemon.enable_hold_keys()
        if ok:
            _idle(self.flash, "Turned on. Restarting FloatNote…")
            GLib.timeout_add(800, lambda: self.app.daemon.restart() and False)
        else:
            _idle(self.flash, message)

    def _update_key_hints(self):
        """Texts that name a shortcut always show the current keys, not the defaults."""
        from .hotkeys import pretty_combo

        cfg = self.app.daemon.cfg
        self.bug_hint.set_text(f"No bugs yet.\nHold {pretty_combo(cfg.hold_bug)} and describe the issue,\n"
                               "let go when you're done.")
        self.todo_hint.set_text(f"Nothing to do.\nHold {pretty_combo(cfg.hold_todo)} and say what you "
                                "want to do.")
        self.dictation_hint.set_text(f"No dictations yet.\nHold {pretty_combo(cfg.hold_dictation)}, talk, let go:\n"
                                     "the text is copied, ready to paste anywhere.")
        self.copy_btn.set_tooltip_text(f"Copy all bugs, then clear the list (press "
                                       f"{pretty_combo(cfg.copy_keys)} and let go)")

    def refresh(self):
        store = self.app.store
        project = store.project(store.active_project_id())
        bugs = store.session_notes(project.id)
        open_todos = store.todos()
        self._update_key_hints()
        self.copy_btn.set_label(f"Copy all ({len(bugs)})" if bugs else "Copy all")
        self.copy_btn.set_sensitive(bool(bugs))
        self.project_label.set_text(f"{project.name} · {len(bugs)}" if bugs else project.name)
        from .hotkeys import NO_PERMISSION

        no_permission = (self.app.daemon.hold_error == NO_PERMISSION
                         and not self.app.daemon.user_in_input_group())
        self.perm_bar.set_visible(no_permission)
        self.update_status()
        if not self.get_visible():
            return
        if self._editing is not None:
            self._dirty = True
            return
        queue = self.app.daemon.ui_state()["queue"]
        self._fill_bugs(bugs, queue)
        self._fill_todos(store.todos(include_done=True) if self.show_done.get_active() else open_todos, queue)
        self._fill_dictations(store.dictations(), queue)
        self._fill_words()
        self._fill_projects()

    @staticmethod
    def _add_pending(listbox, queue: list[str], kind: str):
        """Rows for this kind's recordings still in the queue (the first in it is being transcribed)."""
        for i, k in enumerate(queue):
            if k == kind:
                listbox.add(_pending_row(in_progress=i == 0))

    def _fill_bugs(self, bugs, queue=()):
        _clear(self.bug_list)
        self._add_pending(self.bug_list, list(queue), "bug")
        # Newest first; numbers match the copied list (which is oldest first).
        for i, note in reversed(list(enumerate(bugs, 1))):
            num = Gtk.Label(label=f"{i}.")
            num.get_style_context().add_class("fn-num")
            to_todo = Gtk.Button(label="→ To-do", relief=Gtk.ReliefStyle.NONE, can_focus=False,
                                 tooltip_text="Move this bug to the To-do list")
            to_todo.get_style_context().add_class("fn-move")
            to_todo.connect("clicked", lambda *_, note=note: self._to_todo(note))
            self.bug_list.add(NoteRow(note, num, on_save=self._save, on_delete=self._delete_bug,
                                      on_edit_state=self._edit_state,
                                      extra_buttons=[to_todo] if self.app.daemon.cfg.todo_enabled else []))
        self.bug_list.show_all()

    def _fill_todos(self, todos, queue=()):
        _clear(self.todo_list)
        self._add_pending(self.todo_list, list(queue), "todo")
        for note in sorted(todos, key=lambda n: n.done):  # open first, newest first within
            check = Gtk.CheckButton(active=note.done, tooltip_text="Done")
            check.connect("toggled", lambda b, note=note: self._set_done(note, b.get_active()))
            copy = _icon_button("edit-copy-symbolic", "Copy this to-do", lambda note=note: self._copy_note(note))
            self.todo_list.add(NoteRow(note, check, on_save=self._save, on_delete=self._delete_todo,
                                       on_edit_state=self._edit_state, subtitle=note.created_at[:10],
                                       extra_buttons=[copy]))
        self.todo_list.show_all()

    def _fill_dictations(self, dictations, queue=()):
        from .store import DICTATION_KEEP

        _clear(self.dictation_list)
        self._add_pending(self.dictation_list, list(queue), "dictation")
        for note in dictations:  # newest first
            lead = Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic", Gtk.IconSize.BUTTON)
            copy = _icon_button("edit-copy-symbolic", "Copy again", lambda note=note: self._copy_note(note))
            self.dictation_list.add(NoteRow(note, lead, on_save=self._save, on_delete=self._delete_bug,
                                            on_edit_state=self._edit_state,
                                            subtitle=note.created_at[:16].replace("T", " "),
                                            extra_buttons=[copy]))
        self.dictation_list.show_all()
        self.dictation_count.set_text(f"Keeps the last {DICTATION_KEEP}" if dictations else "")

    def _clear_dictations(self):
        if not self.app.store.dictations():
            return
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.OK_CANCEL, text="Clear the dictation history?")
        dialog.format_secondary_text("All past dictations are deleted. What you copied stays on the clipboard.")

        def answered(response):
            if response == Gtk.ResponseType.OK:
                self.app.store.clear_dictations()
                self.flash("Dictation history cleared")
                _idle(self.refresh)

        self._run_dialog(dialog, answered)

    def _fill_words(self):
        cfg = self.app.daemon.cfg
        _clear(self.fix_list)
        for heard, right in sorted(cfg.replacements.items()):
            self.fix_list.add(_chip([heard, right], lambda h=heard: self._remove_fix(h)))
        self.fix_list.show_all()
        self.fix_empty.set_visible(not cfg.replacements)
        _clear(self.hint_list)
        for word in cfg.vocabulary:
            self.hint_list.add(_chip([word], lambda w=word: self._remove_hint(w)))
        self.hint_list.show_all()

    # ---- note actions -----------------------------------------------------

    def _save(self, note, text):
        self.app.store.update_text(note.id, text)
        self._offer_fix(note.text, text)
        _idle(self.refresh)

    def _copy_note(self, note):
        # Off the GTK thread: a hanging clipboard tool must not freeze the window.
        threading.Thread(target=self.app.daemon.handle, args=({"cmd": "copy-note", "id": note.id},),
                         daemon=True).start()

    def _delete_bug(self, note):
        self.app.store.delete(note.id)
        _idle(self.refresh)

    def _delete_todo(self, note):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.OK_CANCEL, text="Delete this to-do?")
        dialog.format_secondary_text(note.text)
        dialog.set_keep_above(True)
        self._dialog_open = True
        try:
            if dialog.run() == Gtk.ResponseType.OK:
                self.app.store.delete(note.id)
                _idle(self.refresh)
        finally:
            dialog.destroy()
            self._dialog_open = False
            self._focus()

    # ---- projects -----------------------------------------------------------

    def _build_projects_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.new_project = Gtk.Entry(placeholder_text="New project name, press Enter", margin=6)
        self.new_project.connect("activate", lambda e: self._add_project(e.get_text()))
        self.project_error = Gtk.Label(xalign=0, wrap=True, max_width_chars=1, margin_start=10, margin_end=10)
        self.project_error.get_style_context().add_class("fn-error")
        self.project_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.project_list.connect("row-activated", lambda _l, row: self._activate_project(row.project_id))
        explain = Gtk.Label(label="Click a project to make it active: new bugs and Copy all use it. "
                                  "Link a folder so `floatnote list` in that folder (e.g. from Claude Code) "
                                  "picks this project.",
                            xalign=0, wrap=True, max_width_chars=1, margin=10)
        explain.get_style_context().add_class("fn-date")
        page.pack_start(self.new_project, False, False, 0)
        page.pack_start(self.project_error, False, False, 0)
        page.pack_start(Gtk.Separator(), False, False, 0)
        page.pack_start(self.project_list, False, False, 0)
        page.pack_start(explain, False, False, 0)
        return _scrolled(page)

    def _fill_projects(self):
        from .store import GENERAL_ID

        store = self.app.store
        active, counts = store.active_project_id(), store.bug_counts()
        _clear(self.project_list)
        for project in store.projects():
            row = Gtk.ListBoxRow(selectable=False)
            row.project_id = project.id
            box = Gtk.Box(spacing=6)
            box.get_style_context().add_class("fn-row")
            mark = (Gtk.Image.new_from_icon_name("object-select-symbolic", Gtk.IconSize.BUTTON)
                    if project.id == active else Gtk.Image())
            mark.set_size_request(16, -1)
            mark.set_valign(Gtk.Align.START)
            box.pack_start(mark, False, False, 0)
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            name = Gtk.Label(label=project.name, xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=1)
            if project.id == active:
                name.get_style_context().add_class("fn-project")
            n = counts.get(project.id, 0)
            folder = project.folder.replace(str(Path.home()), "~") if project.folder else "no folder"
            sub = Gtk.Label(label=f"{n} bug{'s' if n != 1 else ''} · {folder}", xalign=0,
                            ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=1)
            sub.get_style_context().add_class("fn-date")
            texts.pack_start(name, False, False, 0)
            texts.pack_start(sub, False, False, 0)
            box.pack_start(texts, True, True, 0)
            box.pack_start(_icon_button("folder-symbolic", "Link a code folder",
                                        lambda p=project: self._choose_folder(p)), False, False, 0)
            box.pack_start(_icon_button("document-edit-symbolic", "Rename",
                                        lambda p=project: self._rename_project(p)), False, False, 0)
            delete = _icon_button("user-trash-symbolic", "Delete", lambda p=project: self._delete_project(p))
            delete.set_sensitive(project.id != GENERAL_ID)
            if project.id == GENERAL_ID:
                delete.set_tooltip_text("General can be renamed, not deleted")
            box.pack_start(delete, False, False, 0)
            row.add(box)
            self.project_list.add(row)
        self.project_list.show_all()

    def _fill_project_menu(self):
        """Contents of the '▾' project selector."""
        for child in self.project_popover.get_children():
            self.project_popover.remove(child)
        store = self.app.store
        active, counts = store.active_project_id(), store.bug_counts()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=4)
        for project in store.projects():
            n = counts.get(project.id, 0)
            label = Gtk.Label(label=f"{'✓ ' if project.id == active else '    '}{project.name}"
                                    + (f"  ({n})" if n else ""), xalign=0)
            item = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
            item.add(label)
            item.get_style_context().add_class("fn-menu-item")
            item.connect("clicked", lambda _b, pid=project.id: self._activate_project(pid))
            box.pack_start(item, False, False, 0)
        box.pack_start(Gtk.Separator(margin_top=4, margin_bottom=4), False, False, 0)
        manage = Gtk.Button(label="+ New / manage projects…", relief=Gtk.ReliefStyle.NONE)
        manage.get_child().set_xalign(0)
        manage.connect("clicked", lambda *_: self._open_projects_tab())
        box.pack_start(manage, False, False, 0)
        box.show_all()
        self.project_popover.add(box)

    def _open_projects_tab(self):
        self.project_popover.popdown()
        self._tab_buttons["projects"].set_active(True)
        self.new_project.grab_focus()

    def _activate_project(self, project_id: int):
        self.project_popover.popdown()
        self.app.daemon.set_active_project(project_id)  # notifies: refresh + flash

    def _add_project(self, name: str):
        try:
            pid = self.app.store.add_project(name)
        except ValueError as e:
            self.project_error.set_text(str(e))
            return
        self.project_error.set_text("")
        self.new_project.set_text("")
        self.app.daemon.set_active_project(pid)

    def _rename_project(self, project):
        dialog = Gtk.Dialog(title="Rename project", transient_for=self, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Rename", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry(text=project.name, activates_default=True, margin=10)
        dialog.get_content_area().add(entry)
        dialog.show_all()
        self._run_dialog(dialog, lambda r: r == Gtk.ResponseType.OK and self._do_rename(project, entry.get_text()))

    def _do_rename(self, project, name):
        try:
            self.app.store.rename_project(project.id, name)
            self.project_error.set_text("")
        except ValueError as e:
            self.project_error.set_text(str(e))
        _idle(self.app.refresh_all)

    def _choose_folder(self, project):
        dialog = Gtk.FileChooserDialog(title=f"Code folder for {project.name}", transient_for=self,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL)
        if project.folder:
            dialog.add_button("Unlink folder", 2)
            dialog.set_current_folder(project.folder)
        else:
            dialog.set_current_folder(str(Path.home()))
        dialog.add_button("Link this folder", Gtk.ResponseType.OK)

        def done(response):
            if response == Gtk.ResponseType.OK:
                self.app.store.set_project_folder(project.id, dialog.get_filename())
            elif response == 2:
                self.app.store.set_project_folder(project.id, None)
            _idle(self.refresh)

        self._run_dialog(dialog, done)

    def _delete_project(self, project):
        from .store import GENERAL_ID

        n = self.app.store.bug_counts().get(project.id, 0)
        general = self.app.store.project(GENERAL_ID).name
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   text=f'Delete the project "{project.name}"?')
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        if n:
            dialog.format_secondary_text(f"It still has {n} bug{'s' if n != 1 else ''}.")
            dialog.add_button(f"Move bugs to {general}", 1)
            dialog.add_button("Delete bugs too", 2)
        else:
            dialog.add_button("Delete", 1)

        def done(response):
            if response in (1, 2):
                self.app.store.delete_project(project.id, move_bugs_to=GENERAL_ID if response == 1 else None)
                self.flash(f'Deleted "{project.name}"')
                _idle(self.app.refresh_all)

        self._run_dialog(dialog, done)

    def _run_dialog(self, dialog, on_response):
        """Run a modal dialog without the dropdown closing because focus moved to it."""
        dialog.set_keep_above(True)
        self._dialog_open = True
        try:
            on_response(dialog.run())
        finally:
            dialog.destroy()
            self._dialog_open = False
            self._focus()

    def _to_todo(self, note):
        if not self.app.daemon.cfg.todo_enabled:
            self.flash("The to-do list is off (Settings → General)")
            return
        self.app.store.set_kind(note.id, "todo")
        self.flash("Moved to To-do")
        _idle(self.refresh)

    def _set_done(self, note, done):
        self.app.store.set_done(note.id, done)
        _idle(self.refresh)

    def _add_todo(self, text: str):
        self.app.store.add("todo", text)
        self.flash("To-do saved")
        _idle(self.refresh)

    def _add_bug(self, text: str):
        self.app.store.add("bug", text, project_id=self.app.store.active_project_id())
        self.flash("Bug saved")
        _idle(self.app.refresh_all)

    # ---- words ------------------------------------------------------------

    def _set_words(self, vocabulary, replacements):
        self.app.daemon.set_words(vocabulary, replacements)
        _idle(self.refresh)

    def _add_fix(self):
        heard = self.fix_heard.get_text().strip().lower()
        right = self.fix_right.get_text().strip()
        if not heard or not right:
            return
        cfg = self.app.daemon.cfg
        vocab = cfg.vocabulary if right in cfg.vocabulary else [*cfg.vocabulary, right]
        self._set_words(vocab, {**cfg.replacements, heard: right})
        self.fix_heard.set_text("")
        self.fix_right.set_text("")
        self.flash(f'Will write "{right}" for "{heard}"')

    def _remove_fix(self, heard):
        fixes = dict(self.app.daemon.cfg.replacements)
        fixes.pop(heard, None)
        self._set_words(self.app.daemon.cfg.vocabulary, fixes)

    def _add_hint(self):
        word = self.hint_entry.get_text().strip()
        cfg = self.app.daemon.cfg
        if word and word not in cfg.vocabulary:
            self._set_words([*cfg.vocabulary, word], cfg.replacements)
        self.hint_entry.set_text("")

    def _remove_hint(self, word):
        cfg = self.app.daemon.cfg
        self._set_words([w for w in cfg.vocabulary if w != word], cfg.replacements)

    def _offer_fix(self, before: str, after: str):
        fix = suggest_fix(before, after, self.app.daemon.cfg.replacements)
        if fix is None:
            return
        self._suggestion = fix
        self.suggest_label.set_text(f'Always write "{fix[1]}" when FloatNote hears "{fix[0]}"?')
        self.suggest_bar.show()

    def _on_suggest_response(self, _bar, response):
        if response == 1 and self._suggestion:
            heard, right = self._suggestion
            cfg = self.app.daemon.cfg
            vocab = cfg.vocabulary if right in cfg.vocabulary else [*cfg.vocabulary, right]
            self._set_words(vocab, {**cfg.replacements, heard: right})
            self.flash(f'Saved "{heard}" → "{right}" in Settings → Words')
        self._suggestion = None
        self.suggest_bar.hide()

    # ---- status line ------------------------------------------------------

    def flash(self, message: str):
        self._flash = message
        self._flash_until = time.monotonic() + FLASH_SECONDS
        self.update_status()

    def update_status(self):
        state = self.app.daemon.ui_state()
        if state["recording"]:
            secs = int(time.monotonic() - state["started_at"])
            from .daemon import NAMES

            text = f"● Recording {NAMES.get(state['recording'], state['recording'])}  {secs // 60}:{secs % 60:02d}"
            if state.get("hands_free"):
                from .daemon import KEY_FIELDS
                from .hotkeys import pretty_combo

                keys = getattr(self.app.daemon.cfg, KEY_FIELDS[state["recording"]])
                text += f" · hands-free, tap {pretty_combo(keys)} to stop"
        elif time.monotonic() < self._flash_until:
            text = self._flash
        elif state["model_error"]:
            text = "Speech model failed, see log"
        elif not state["model_ready"]:
            text = state.get("model_status") or "Loading speech model…"
        elif state["pending"]:
            text = "Transcribing…" if state["pending"] == 1 else f"Transcribing… ({state['pending'] - 1} waiting)"
        elif state["hold_error"]:
            text = "Hold keys off: run floatnote doctor"
        else:
            text = ""  # quiet when idle; the guide (ⓘ) explains the keys
        self.status.set_text(text)
        needs_tick = state["recording"] or time.monotonic() < self._flash_until
        if needs_tick and not self._tick_id:
            self._tick_id = GLib.timeout_add(500, self._tick)

    def _tick(self):
        self._tick_id = 0
        self.update_status()  # re-arms itself while still needed
        return GLib.SOURCE_REMOVE


class App:
    def __init__(self, daemon):
        if Gdk.Display.get_default() is None:
            raise RuntimeError("no display available")
        self.daemon = daemon
        self.store = daemon.store
        self.settings = self._load_settings()
        self._green_until = 0.0

        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.dropdown = Dropdown(self)
        self.panel = self.dropdown  # old name, used by tests/tools
        try:
            from .tray import Tray

            self.tray = Tray(lambda x, y: self.dropdown.toggle(x, y))
        except Exception:  # noqa: BLE001 - FloatNote still works from the shortcuts
            import logging

            logging.getLogger("floatnote").exception("panel icon unavailable")
            self.tray = None
        daemon.ui = self
        self._update_indicators()

    # ---- thread-safe entry points (called by the daemon) ------------------

    def changed(self, message: str | None = None, event: str | None = None) -> None:
        _idle(self._changed, message, event)

    def show_panel(self, kind: str | None = None) -> None:
        _idle(self.dropdown.open_dropdown, None, {"bug": "bugs", "todo": "todo", "dictation": "dictation"}.get(kind))

    def toggle_panel(self) -> None:
        _idle(self.dropdown.toggle)

    def open_home(self) -> None:
        _idle(self.dropdown.open_dropdown, None, "todo")

    def quit(self) -> None:
        _idle(Gtk.main_quit)

    # ---- main thread ------------------------------------------------------

    def refresh_all(self):
        self.dropdown.refresh()
        self._update_indicators()

    def _changed(self, message, event):
        if event == "copied":
            self._green_until = time.monotonic() + COPIED_GREEN_SECONDS
            GLib.timeout_add(int(COPIED_GREEN_SECONDS * 1000) + 50, lambda: self._update_indicators() and False)
        if message:
            self.dropdown.flash(message)
        self.dropdown.refresh()
        self._update_indicators()

    def _update_indicators(self):
        if self.tray is None:
            return
        state = self.daemon.ui_state()
        project = self.store.project(self.store.active_project_id())
        bugs = len(self.store.session_notes(project.id))
        if state["recording"]:
            from .daemon import NAMES

            icon, body = state["recording"], f"Recording {NAMES.get(state['recording'], state['recording'])}…"
        elif time.monotonic() < self._green_until:
            icon, body = "ok", "Copied"
        elif state["pending"] or not state["model_ready"]:
            icon, body = "busy", "Transcribing…" if state["pending"] else state.get("model_status", "")
        else:
            icon, body = "idle", f"{bugs} bug(s) waiting" if bugs else "Ready"
        self.tray.set_icon(icon)
        from .shortcuts import detect_desktop
        from .store import GENERAL_ID
        from .tray import bar_label, project_initials

        # Only GNOME shows text next to a tray icon; elsewhere the project's
        # initials go on the icon. The built-in General project shows neither
        # (the plain icon means General). The tooltip always names the project.
        show = self.daemon.cfg.show_project_in_bar and project.id != GENERAL_ID
        text_label = detect_desktop() == "gnome"
        self.tray.set_label(bar_label(project.name) if show and text_label else "")
        self.tray.set_initials(project_initials(project.name) if show and not text_label else "")
        self.tray.set_tooltip(f"FloatNote: {project.name}", body)
        self.tray.set_badge(bugs)

    def run(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._on_signal)
        Gtk.main()

    def _on_signal(self, *_):
        Gtk.main_quit()
        return GLib.SOURCE_REMOVE

    # ---- small persisted UI settings --------------------------------------

    def _load_settings(self) -> dict:
        try:
            return json.loads(paths.ui_state_file().read_text())
        except (OSError, ValueError):
            return {}

    def save_settings(self) -> None:
        try:
            paths.ui_state_file().write_text(json.dumps(self.settings))
        except OSError:
            pass
