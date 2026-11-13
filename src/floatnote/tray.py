"""Top-bar icon (StatusNotifierItem) and dock badge (Unity LauncherEntry).

Implemented directly over D-Bus instead of libappindicator so that a left
click calls Activate(x, y) with the click position: we open our own dropdown
there, instead of the plain menu an AppIndicator would show.
GNOME shows these icons through the AppIndicator extension (on by default in
Ubuntu). Must run on the GLib main loop.
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


BAR_LABEL_MAX = 16  # longer project names are shortened with "…" in the top bar


def bar_label(name: str, limit: int = BAR_LABEL_MAX) -> str:
    """Project name for the top bar: 'My very long project name' -> 'My very long pr…'."""
    name = " ".join(name.split())
    return name if len(name) <= limit else name[: limit - 1].rstrip() + "…"


class Tray:
    def __init__(self, on_activate: Callable[[int | None, int | None], None]):
        self.on_activate = on_activate
        self._icon = "idle"
        self._tooltip = ("FloatNote", "")
        self._label = ""  # text shown next to the icon (the active project)
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        node = Gio.DBusNodeInfo.new_for_xml(_SNI_XML)
        self._reg = self._bus.register_object(_SNI_PATH, node.interfaces[0],
                                              self._on_call, self._on_get, None)
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        Gio.bus_own_name_on_connection(self._bus, self.name, Gio.BusNameOwnerFlags.NONE,
                                       self._on_name_acquired, None)

    # ---- registration ------------------------------------------------------

    def _on_name_acquired(self, *_):
        # (Re-)register whenever the watcher (the AppIndicator extension) appears.
        Gio.bus_watch_name_on_connection(self._bus, _WATCHER, Gio.BusNameWatcherFlags.NONE,
                                         self._register, self._watcher_gone)

    def _register(self, *_):
        self._bus.call(_WATCHER, "/StatusNotifierWatcher", _WATCHER, "RegisterStatusNotifierItem",
                       GLib.Variant("(s)", (self.name,)), None, Gio.DBusCallFlags.NONE, -1, None,
                       self._registered)

    def _registered(self, bus, result):
        try:
            bus.call_finish(result)
            log.info("top-bar icon registered")
        except GLib.Error as e:
            log.warning("top-bar icon not registered: %s", e.message)

    def _watcher_gone(self, *_):
        log.warning("no top-bar icon host (is the Ubuntu AppIndicators extension enabled?)")

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
            "IconName": GLib.Variant("s", f"floatnote-{self._icon}"),
            "IconThemePath": GLib.Variant("s", str(ICON_DIR)),
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

    def set_label(self, text: str) -> None:
        """Text shown right of the icon in the top bar; "" hides it."""
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
