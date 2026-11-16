"""Desktop notifications (org.freedesktop.Notifications), used by dictation.

Each one replaces the previous FloatNote notification, closes itself after a
few seconds and is marked transient, so they never pile up in the desktop's
notification history.
"""

import logging
import threading

log = logging.getLogger("floatnote")

EXPIRE_MS = 4000
PREVIEW_CHARS = 80

_lock = threading.Lock()
_last_id = 0


def preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    """One line, shortened: 'Hello there, this is a long…'."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def show(summary: str, body: str = "", icon: str = "audio-input-microphone") -> None:
    """Show a notification; never raises (no notification service is fine)."""
    global _last_id
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        hints = {"transient": GLib.Variant("b", True), "urgency": GLib.Variant("y", 1),
                 "desktop-entry": GLib.Variant("s", "floatnote")}
        with _lock:
            reply = bus.call_sync(
                "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                "org.freedesktop.Notifications", "Notify",
                GLib.Variant("(susssasa{sv}i)", ("FloatNote", _last_id, icon, summary,
                                                 GLib.markup_escape_text(body), [], hints, EXPIRE_MS)),
                GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 3000, None)
            _last_id = reply.unpack()[0]
    except Exception as e:  # noqa: BLE001 - no notification service, no session bus...
        log.debug("notification failed: %s", e)
