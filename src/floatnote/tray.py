"""Panel (tray) icon (StatusNotifierItem) and dock badge (Unity LauncherEntry).

Implemented directly over D-Bus instead of libappindicator so that a left
click calls Activate(x, y) with the click position: we open our own dropdown
there, instead of the plain menu an AppIndicator would show.
KDE, Cinnamon and XFCE show these icons natively; GNOME needs the AppIndicator
extension (on by default in Ubuntu). Must run on the GLib main loop.
"""

import logging
import os
from pathlib import Path
from typing import Callable

from gi.repository import Gio, GLib

log = logging.getLogger("floatnote")

ICON_DIR = Path(__file__).parent / "icons"
ICONS = {"idle", "bug", "idea", "busy", "ok"}
DESKTOP_ID = "floatnote.desktop"

_SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="XAyatanaLabel" type="s" access="read"/>
    <property name="XAyatanaLabelGuide" type="s" access="read"/>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
    <signal name="XAyatanaNewLabel"><arg name="label" type="s"/><arg name="guide" type="s"/></signal>
  </interface>
</node>
"""
_SNI_PATH = "/StatusNotifierItem"
_SNI_IFACE = "org.kde.StatusNotifierItem"
_WATCHER = "org.kde.StatusNotifierWatcher"
_BADGE_PATH = "/com/canonical/unity/launcherentry/floatnote"


def no_host_hint() -> str:
    """How to get a tray on this desktop."""
    from .shortcuts import detect_desktop

    return {
        "gnome": "enable the AppIndicator extension (on by default in Ubuntu; "
                 "Fedora: sudo dnf install gnome-shell-extension-appindicator, then log out and in)",
        "xfce": "add the Status Tray Plugin to your panel",
        "kde": "add the System Tray widget to your panel",
        "cinnamon": "add the Xapp Status applet to your panel",
    }.get(detect_desktop() or "", "your panel needs a StatusNotifier (AppIndicator) tray")


BAR_LABEL_MAX = 16  # longer project names are shortened with "…" in the panel


def bar_label(name: str, limit: int = BAR_LABEL_MAX) -> str:
    """Project name for the panel: 'My very long project name' -> 'My very long pr…'."""
    name = " ".join(name.split())
    return name if len(name) <= limit else name[: limit - 1].rstrip() + "…"


# ---- project badge on the icon ----------------------------------------------
# Only GNOME shows text next to a tray icon (the label above). Elsewhere (KDE,
# XFCE, Cinnamon) the project's initials are drawn into the icon itself.

COLORS = {"idle": "#bdbdbd", "bug": "#ff4d4d", "idea": "#4da3ff", "busy": "#ffcc33", "ok": "#3ddc84"}
LETTER_COLOR = "#b18cff"  # the project letters stay purple; the mic shows the state
ICON_DESIGN = 2  # bump when icon_svg changes


def project_initials(name: str) -> str:
    """1-2 letters for the badge: 'Client website' -> 'CW', 'FloatNote' -> 'FN',
    'floatnote' -> 'Fl', 'X' -> 'X'."""
    import re

    words = re.findall(r"[^\W_]+", name)  # letters and digits, any language
    # Split camelCase too: "FloatNote" -> ["Float", "Note"].
    parts = [p for w in words for p in (re.findall(r"[A-Z][^A-Z]*", w) if w[:1].isupper() else [w])]
    parts = [p for p in parts if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    if parts:
        word = parts[0]
        return word[0].upper() + word[1:2].lower()
    return ""


def icon_svg(state: str, initials: str) -> str:
    """A thin mic on the left in the state's colour (red still means recording)
    and the project's 1-2 letters on the right in purple. Tray icons are
    square (~22 px on KDE), so two letters is what stays readable."""
    from xml.sax.saxutils import escape

    color = COLORS[state]
    mic = (f'<g transform="translate(-1.5,1.5) scale(0.62)">'
           f'<rect x="5" y="1" width="6" height="9" rx="3" fill="{color}"/>'
           f'<path d="M3 7.5a5 5 0 0 0 10 0" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round"/>'
           f'<path d="M8 12.6v2.2M5.5 15h5" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round"/>'
           f'</g>')
    letters = (f'<text x="11.2" y="11.6" font-family="sans-serif" font-weight="800" font-size="8.6" '
               f'letter-spacing="-0.3" text-anchor="middle" fill="{LETTER_COLOR}">{escape(initials[:2])}</text>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
            f'{mic}{letters}</svg>\n')


def badge_icon(folder: Path, state: str, initials: str) -> str:
    """Write the badge icon (once) and return its icon name."""
    # The design version is in the name: files (and the panel's icon cache)
    # from an older design are never reused.
    name = f"floatnote-{state}-v{ICON_DESIGN}-p{initials.encode().hex()}"
    path = folder / f"{name}.svg"
    if not path.exists():
        path.write_text(icon_svg(state, initials))
    return name


class Tray:
    def __init__(self, on_activate: Callable[[int | None, int | None], None]):
        self.on_activate = on_activate
        self._icon = "idle"
        self._tooltip = ("FloatNote", "")
        self._label = ""  # text shown next to the icon (the active project)
        self._initials = ""  # project badge drawn on the icon ("" = plain icon)
        self._badge_dir: Path | None = None
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        node = Gio.DBusNodeInfo.new_for_xml(_SNI_XML)
        self._reg = self._bus.register_object(_SNI_PATH, node.interfaces[0],
                                              self._on_call, self._on_get, None)
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        Gio.bus_own_name_on_connection(self._bus, self.name, Gio.BusNameOwnerFlags.NONE,
                                       self._on_name_acquired, None)

    # ---- registration ------------------------------------------------------

    def _on_name_acquired(self, *_):
        # (Re-)register whenever the watcher (the panel's tray) appears.
        Gio.bus_watch_name_on_connection(self._bus, _WATCHER, Gio.BusNameWatcherFlags.NONE,
                                         self._register, self._watcher_gone)

    def _register(self, *_):
        self._bus.call(_WATCHER, "/StatusNotifierWatcher", _WATCHER, "RegisterStatusNotifierItem",
                       GLib.Variant("(s)", (self.name,)), None, Gio.DBusCallFlags.NONE, -1, None,
                       self._registered)

    def _registered(self, bus, result):
        try:
            bus.call_finish(result)
            log.info("panel icon registered")
        except GLib.Error as e:
            log.warning("panel icon not registered: %s", e.message)

    def _watcher_gone(self, *_):
        log.warning("no panel icon host: %s", no_host_hint())

    # ---- D-Bus callbacks ---------------------------------------------------

    def _on_call(self, conn, sender, path, iface, method, params, invocation):
        if method in ("Activate", "SecondaryActivate", "ContextMenu"):
            x, y = params.unpack()
            GLib.idle_add(lambda: self.on_activate(x, y) and False)
        invocation.return_value(None)

    def _on_get(self, conn, sender, path, iface, prop):
        title, body = self._tooltip
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "floatnote"),
            "Title": GLib.Variant("s", "FloatNote"),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconName": GLib.Variant("s", self._icon_name()),
            "IconThemePath": GLib.Variant("s", str(self._badge_dir if self._initials else ICON_DIR)),
            "AttentionIconName": GLib.Variant("s", ""),
            "OverlayIconName": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], title, body)),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", "/NO_DBUSMENU"),
            "XAyatanaLabel": GLib.Variant("s", self._label),
            "XAyatanaLabelGuide": GLib.Variant("s", self._label),
        }
        return values.get(prop)

    def _emit(self, signal: str, params=None) -> None:
        try:
            self._bus.emit_signal(None, _SNI_PATH, _SNI_IFACE, signal, params)
        except GLib.Error as e:
            log.debug("signal %s failed: %s", signal, e.message)

    # ---- public ------------------------------------------------------------

    def set_icon(self, state: str) -> None:
        assert state in ICONS, state
        if state != self._icon:
            self._icon = state
            self._emit("NewIcon")

    def _icon_name(self) -> str:
        if self._initials:
            try:
                return badge_icon(self._badge_dir, self._icon, self._initials)
            except OSError as e:
                log.warning("project badge icon failed: %s", e)
                self._initials = ""
        return f"floatnote-{self._icon}"

    def set_initials(self, initials: str) -> None:
        """Draw the project's initials on the icon (for panels without text
        labels, i.e. not GNOME); "" shows the plain icon."""
        if initials and self._badge_dir is None:
            from . import paths

            try:
                self._badge_dir = paths.icon_dir()
            except OSError as e:
                log.warning("no folder for the project badge icon: %s", e)
                return
        if initials != self._initials:
            self._initials = initials
            self._emit("NewIcon")

    def set_label(self, text: str) -> None:
        """Text shown right of the icon in the panel (GNOME; KDE/XFCE ignore it); "" hides it."""
        if text != self._label:
            self._label = text
            self._emit("XAyatanaNewLabel", GLib.Variant("(ss)", (text, text)))

    def set_tooltip(self, title: str, body: str = "") -> None:
        if (title, body) != self._tooltip:
            self._tooltip = (title, body)
            self._emit("NewToolTip")

    def set_badge(self, count: int) -> None:
        """Number badge on the dock icon (when FloatNote is pinned)."""
        props = {"count": GLib.Variant("x", count), "count-visible": GLib.Variant("b", count > 0)}
        try:
            self._bus.emit_signal(None, _BADGE_PATH, "com.canonical.Unity.LauncherEntry", "Update",
                                  GLib.Variant("(sa{sv})", (f"application://{DESKTOP_ID}", props)))
        except GLib.Error as e:
            log.debug("badge update failed: %s", e.message)
