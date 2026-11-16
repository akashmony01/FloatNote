"""Desktop notifications (org.freedesktop.Notifications), used by dictation.

Each one closes itself after a few seconds and is marked transient, so they
never pile up in the desktop's notification history. A new one replaces the
previous one only while that is still on screen: KDE silently drops a
"replacement" for a notification that has already closed.
"""

import logging
import threading
import time

log = logging.getLogger("floatnote")

EXPIRE_MS = 4000
PREVIEW_CHARS = 80

_lock = threading.Lock()
_last_id = 0          # our notification that may still be on screen (0: none)
_last_at = 0.0        # when it was shown
_subscribed = False


def preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    """One line, shortened: 'Hello there, this is a long…'."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def replaces_id(now: float | None = None) -> int:
    """The id to replace: the previous notification, if it can still be on screen."""
    now = time.monotonic() if now is None else now
    if _last_id and now - _last_at < EXPIRE_MS / 1000 - 0.3:
        return _last_id
    return 0


def _on_closed(_conn, _sender, _path, _iface, _signal, params, *_):
    global _last_id
    with _lock:
        if params.unpack()[0] == _last_id:
            _last_id = 0  # gone (expired or clicked away): the next one is a new one


def show(summary: str, body: str = "", icon: str = "audio-input-microphone") -> None:
    """Show a notification; never raises (no notification service is fine)."""
    global _last_id, _last_at, _subscribed
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        hints = {"transient": GLib.Variant("b", True), "urgency": GLib.Variant("y", 1),
                 "desktop-entry": GLib.Variant("s", "floatnote")}
        with _lock:
            if not _subscribed:
                bus.signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications",
                                     "NotificationClosed", "/org/freedesktop/Notifications", None,
                                     Gio.DBusSignalFlags.NONE, _on_closed)
                _subscribed = True
            reply = bus.call_sync(
                "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                "org.freedesktop.Notifications", "Notify",
                GLib.Variant("(susssasa{sv}i)", ("FloatNote", replaces_id(), icon, summary,
                                                 GLib.markup_escape_text(body), [], hints, EXPIRE_MS)),
                GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 3000, None)
            _last_id, _last_at = reply.unpack()[0], time.monotonic()
    except Exception as e:  # noqa: BLE001 - no notification service, no session bus...
        log.warning("notification failed: %s", e)
