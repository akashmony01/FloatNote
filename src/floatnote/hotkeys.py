"""FloatNote's keyboard shortcuts, read straight from the keyboard devices.

Wayland desktops never tell apps when a global shortcut is *released*, so
hold-to-talk can't use normal shortcuts, and every desktop has its own
shortcut settings. Instead this reads /dev/input (needs the user in the
'input' group), which works the same on GNOME, KDE, Cinnamon, XFCE, Wayland
and X11. Only modifier state and the few keys used by FloatNote's shortcuts
are tracked; key codes of other keys are kept in memory just long enough to
know they're held, never stored or logged.

Rules (see ChordTracker):
- Hold exactly a configured combo (e.g. Ctrl+Super+Left) for `delay` seconds: start.
- Release any key of the combo: stop (transcribe).
- Press any other key while holding: cancel (it was a normal shortcut).
- Press a key shortcut (e.g. Ctrl+Super+Alt+N): fire it straight away.
"""

import errno
import fcntl
import glob
import logging
import os
import selectors
import struct
import threading
import time
from typing import Callable

log = logging.getLogger("floatnote")

EV_SYN, EV_KEY = 0, 1
SYN_DROPPED = 3
MODIFIERS = {
    "ctrl": {29, 97},     # KEY_LEFTCTRL, KEY_RIGHTCTRL
    "alt": {56, 100},     # KEY_LEFTALT, KEY_RIGHTALT
    "super": {125, 126},  # KEY_LEFTMETA, KEY_RIGHTMETA
    "shift": {42, 54},    # KEY_LEFTSHIFT, KEY_RIGHTSHIFT
}
# Non-modifier keys a combo may include (at most one per combo).
KEYS = {"left": {105}, "right": {106}, "up": {103}, "down": {108}, "space": {57}}
_CODE_TO_MOD = {code: mod for mod, codes in MODIFIERS.items() for code in codes}
_CODE_TO_KEY = {code: key for key, codes in KEYS.items() for code in codes}

# Every key a captured shortcut may use (for the open/close and next-project
# shortcuts any letter/digit/F-key works too).
_LETTER_CODES = dict(zip("qwertyuiop", range(16, 26))) | dict(zip("asdfghjkl", range(30, 39))) \
    | dict(zip("zxcvbnm", range(44, 51)))
NAMED_KEYS: dict[int, str] = {
    **{code: ch for ch, code in _LETTER_CODES.items()},
    **{2 + i: str((i + 1) % 10) for i in range(10)},          # 1..9, 0
    **{59 + i: f"f{i + 1}" for i in range(10)}, 87: "f11", 88: "f12",
    **_CODE_TO_KEY, **_CODE_TO_MOD,
}
_NAME_TO_CODES: dict[str, set[int]] = {}
for _code, _name in NAMED_KEYS.items():
    if _name not in MODIFIERS:
        _NAME_TO_CODES.setdefault(_name, set()).add(_code)
_ORDER = ["ctrl", "super", "alt", "shift"]
KEY_ESC = 1


def format_combo(names) -> str:
    """{'super', 'ctrl', 'n'} -> 'ctrl+super+n' (modifiers first, fixed order)."""
    mods = [m for m in _ORDER if m in names]
    rest = sorted(n for n in names if n not in MODIFIERS)
    return "+".join(mods + rest)


def pretty_combo(text: str) -> str:
    """'ctrl+super+alt+n' -> 'Ctrl+Super+Alt+N'."""
    arrows = {"left": "←", "right": "→", "up": "↑", "down": "↓"}
    out = []
    for part in text.split("+"):
        out.append(arrows.get(part) or (part.upper() if len(part) == 1 or part.startswith("f") else part.capitalize()))
    return "+".join(out)
_ALIASES = {"control": "ctrl", "meta": "super", "win": "super", "windows": "super", "cmd": "super"}

# struct input_event on 64-bit Linux: timeval (2 longs), u16 type, u16 code, s32 value
_EVENT = struct.Struct("llHHi")
_KEY_MAX = 0x2FF
_EVIOCGBIT_KEY = (2 << 30) | (((_KEY_MAX + 7) // 8) << 16) | (ord("E") << 8) | (0x20 + EV_KEY)

NO_PERMISSION = ("cannot read the keyboard: press 'Turn on…' in the FloatNote dropdown, "
                 "or run: sudo usermod -aG input $USER")


def parse_combo(text: str) -> frozenset[str]:
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    names = frozenset(_ALIASES.get(p, p) for p in parts)
    unknown = names - MODIFIERS.keys() - KEYS.keys()
    keys = names & KEYS.keys()
    if unknown or not (names & MODIFIERS.keys()) or len(keys) > 1:
        raise ValueError(f"bad hold combo {text!r}: use modifiers plus at most one of "
                         f"{', '.join(KEYS)}, e.g. ctrl+super+left")
    return names


def parse_key_combo(text: str) -> frozenset[str]:
    """'ctrl+super+alt+n' -> {'ctrl', 'super', 'alt', 'n'}: modifiers plus exactly
    one letter, digit, F-key, arrow or Space (open/close, next project)."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    names = frozenset(_ALIASES.get(p, p) for p in parts)
    keys = [n for n in names if n not in MODIFIERS]
    if not names & MODIFIERS.keys() or len(keys) != 1 or keys[0] not in _NAME_TO_CODES:
        raise ValueError(f"bad shortcut {text!r}: use modifier keys plus one letter, number, "
                         "arrow or F-key, e.g. ctrl+super+alt+n")
    return names


def validate_keys(bug: str, idea: str, copy: str, toggle: str, next_project: str | None = None) -> str | None:
    """Check a full set of shortcuts. Returns a message for the user, or None if fine."""
    labels = {"bug": "Record bug", "idea": "Record idea", "copy": "Copy bugs", "toggle": "Open/close",
              "next": "Next project"}
    combos = {}
    for which, text in (("bug", bug), ("idea", idea), ("copy", copy)):
        try:
            combos[which] = parse_combo(text)
        except ValueError:
            return (f"{labels[which]}: use 2-3 modifier keys (Ctrl, Super, Alt, Shift), "
                    "optionally with one arrow key.")
        if len(combos[which]) < 2:
            return f"{labels[which]}: use at least two keys, e.g. Ctrl+Super."
    # Key shortcuts: modifiers plus exactly one normal key.
    for which, text in (("toggle", toggle), ("next", next_project)):
        if text is None:
            continue
        try:
            combos[which] = parse_key_combo(text)
        except ValueError:
            return (f"{labels[which]}: use modifier keys plus one letter, number, arrow or F-key, "
                    "e.g. Ctrl+Super+Alt+N.")
    seen = {}
    for which, combo in combos.items():
        if combo in seen:
            return f"{labels[which]} and {labels[seen[combo]]} can't use the same keys."
        seen[combo] = which
    return None


def to_accelerator(toggle: str) -> str:
    """'ctrl+super+alt+n' -> '<Control><Super><Alt>n' (GTK's format, used by GNOME,
    Cinnamon and XFCE)."""
    gtk = {"ctrl": "<Control>", "super": "<Super>", "alt": "<Alt>", "shift": "<Shift>"}
    names = toggle.split("+")
    mods = "".join(gtk[m] for m in _ORDER if m in names)
    key = next(n for n in names if n not in MODIFIERS)
    key = {"left": "Left", "right": "Right", "up": "Up", "down": "Down"}.get(key) or \
        (key.upper() if key.startswith("f") and len(key) > 1 else key)
    return mods + key


class ChordTracker:
    """Pure state machine. Feed key events, collect actions:
    ("start", kind), ("stop",), ("cancel",), ("tap", name), ("key", name).

    combos: hold gestures, e.g. {ctrl, super} -> "bug".
    taps:   press-and-release gestures, e.g. {ctrl, super, alt} -> "copy". A tap
            fires when you let go, but only if no other key was pressed, so
            Ctrl+Super+Alt+N can still be a normal shortcut.
    keys:   normal shortcuts, modifiers plus one key, e.g. {ctrl, super, alt, n}
            -> "toggle". Fires when the key goes down while exactly those
            modifiers (and no other key) are held. Counts as "another key" for
            the gestures above, so it never copies or records.
    """

    def __init__(self, combos: dict[frozenset[str], str], delay: float = 0.25,
                 taps: dict[frozenset[str], str] | None = None,
                 keys: dict[frozenset[str], str] | None = None):
        self.combos = combos
        self.taps = taps or {}
        self.keys = keys or {}
        self.delay = delay
        # code -> key name, only for the keys used by key shortcuts.
        self._key_codes = {code: name for combo in self.keys for name in combo if name not in MODIFIERS
                           for code in _NAME_TO_CODES[name]}
        # Keys we track by name: all modifiers plus the keys used in combos.
        used = set().union(*combos, *self.taps) if (combos or self.taps) else set()
        self._tracked = {**_CODE_TO_MOD, **{c: k for c, k in _CODE_TO_KEY.items() if k in used}}
        self._mods: dict[str, set[int]] = {m: set() for m in [*MODIFIERS, *(used & KEYS.keys())]}
        self._others: set[int] = set()
        self._candidate: frozenset[str] | None = None
        self._since = 0.0
        self._active: frozenset[str] | None = None
        self._tap: frozenset[str] | None = None  # tap gesture currently held
        self._spoiled = False  # another key was involved; wait until all keys are up

    def fresh(self) -> "ChordTracker":
        """A new tracker with the same shortcuts and no keys held."""
        return ChordTracker(self.combos, self.delay, self.taps, self.keys)

    def _held(self) -> frozenset[str]:
        return frozenset(m for m, codes in self._mods.items() if codes)

    def _key_shortcut(self, code: int) -> str | None:
        """The key shortcut completed by pressing `code` now, if any."""
        name = self._key_codes.get(code)
        if name is None or self._others:
            return None
        mods = frozenset(m for m in MODIFIERS if self._mods[m])
        return self.keys.get(mods | {name})

    @property
    def pending_deadline(self) -> float | None:
        return self._since + self.delay if self._candidate and not self._active else None

    def feed(self, code: int, value: int, now: float) -> list[tuple]:
        if value == 2:  # auto-repeat
            return []
        actions: list[tuple] = []
        shortcut = self._key_shortcut(code) if value else None
        name = None if shortcut else self._tracked.get(code)
        if not value:  # a key used by a shortcut may also be tracked (an arrow): forget it both ways
            self._others.discard(code)
        if name:
            (self._mods[name].add if value else self._mods[name].discard)(code)
        elif value:
            self._others.add(code)
            self._spoiled = True
            self._tap = None
            self._candidate = None
            if self._active:
                actions.append(("cancel",))
                self._active = None
        if shortcut:
            actions.append(("key", shortcut))

        held = self._held()
        if self._active and held != self._active:
            if self._active <= held:  # extra modifier added: not our gesture
                actions.append(("cancel",))
                if held not in self.taps:
                    self._spoiled = True
            else:                      # a combo key was released
                actions.append(("stop",))
            self._active = None
            # Not spoiled after a stop: pressing the released key again
            # records the next note straight away.
            self._candidate = None

        if self._tap and held != self._tap:
            if held < self._tap and not self._others:  # let go, nothing else pressed
                actions.append(("tap", self.taps[self._tap]))
            self._tap = None
            self._spoiled = True  # releasing must not start a recording
        elif not self._tap and held in self.taps and not self._others and not self._spoiled:
            self._tap = held
            self._candidate = None

        if not held and not self._others:
            self._spoiled = False
        if not self._active and not self._tap:
            if held in self.combos and not self._others and not self._spoiled:
                if held != self._candidate:
                    self._candidate, self._since = held, now
            else:
                self._candidate = None
        return actions + self.poll(now)

    def poll(self, now: float) -> list[tuple]:
        if self._candidate and not self._active and now - self._since >= self.delay:
            self._active, self._candidate = self._candidate, None
            return [("start", self.combos[self._active])]
        return []


def keyboard_readable() -> bool:
    """Can FloatNote read the keyboard (is the user allowed to open /dev/input)?"""
    for path in glob.glob("/dev/input/event*"):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            if _is_keyboard(fd):
                return True
        finally:
            os.close(fd)
    return False


def _is_keyboard(fd: int) -> bool:
    bits = bytearray((_KEY_MAX + 7) // 8)
    try:
        fcntl.ioctl(fd, _EVIOCGBIT_KEY, bits)
    except OSError:
        return False

    def has(code):
        return bits[code // 8] >> (code % 8) & 1

    return has(29) and has(30)  # has Ctrl and the letter A


class HotkeyListener(threading.Thread):
    """Reads all keyboards, feeds a ChordTracker, calls on_action for each action."""

    RESCAN_SECONDS = 3.0

    def __init__(self, tracker: ChordTracker, on_action: Callable[[tuple], None]):
        super().__init__(name="hotkeys", daemon=True)
        self.tracker = tracker
        self.on_action = on_action
        self.error: str | None = None
        self._sel = selectors.DefaultSelector()
        self._open: dict[str, int] = {}
        self._stop = threading.Event()
        self._capture: dict | None = None  # set while the user is choosing new keys
        # Lets other threads wake the select() loop (e.g. to cancel a capture).
        self._wake_r, self._wake_w = os.pipe()
        os.set_blocking(self._wake_r, False)
        self._sel.register(self._wake_r, selectors.EVENT_READ, "wake")

    def capture(self, on_done: Callable[[frozenset | None, str | None], None], timeout: float = 10.0) -> None:
        """Record the next key combo instead of acting on it. Calls
        on_done(names, None) when all keys are released, on_done(None, error) on
        a problem, or on_done(None, None) if cancelled (Esc or cancel_capture())."""
        self._capture = {"down": set(), "names": set(), "unknown": False,
                         "cb": on_done, "deadline": time.monotonic() + timeout}

    def cancel_capture(self) -> None:
        """Stop waiting for keys; the old shortcut stays. Safe from any thread."""
        c = self._capture
        if c is not None:
            c["cancelled"] = True
            os.write(self._wake_w, b"x")

    def _feed_capture(self, code: int, value: int) -> None:
        c = self._capture
        if value == 1 and code == KEY_ESC:
            c["cancelled"] = True
            return
        if value == 1:
            c["down"].add(code)
            name = NAMED_KEYS.get(code)
            if name:
                c["names"].add(name)
            else:
                c["unknown"] = True
        elif value == 0:
            c["down"].discard(code)
            if not c["down"] and (c["names"] or c["unknown"]):
                self._finish_capture()

    def _finish_capture(self, error: str | None = None) -> None:
        c, self._capture = self._capture, None
        # Start fresh so half-pressed keys from the capture don't linger.
        self.tracker = self.tracker.fresh()
        if c.get("cancelled"):
            c["cb"](None, None)
            return
        if error is None and c["unknown"]:
            error = "That key can't be used; try letters, numbers, arrows or F-keys."
        c["cb"](None if error else frozenset(c["names"]), error)

    def stop(self) -> None:
        self._stop.set()

    def _scan(self) -> None:
        denied = 0
        for path in glob.glob("/dev/input/event*"):
            if path in self._open:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except PermissionError:
                denied += 1
                continue
            except OSError:
                continue
            if _is_keyboard(fd):
                self._open[path] = fd
                self._sel.register(fd, selectors.EVENT_READ, path)
                log.info("hold-to-record: watching %s", path)
            else:
                os.close(fd)
        if self._open:
            self.error = None
        elif denied:
            if self.error != NO_PERMISSION:
                log.warning("hold-to-record off: %s", NO_PERMISSION)
            self.error = NO_PERMISSION
        else:
            self.error = "no keyboard found"

    def _close(self, path: str) -> None:
        fd = self._open.pop(path, None)
        if fd is not None:
            self._sel.unregister(fd)
            os.close(fd)
            self._reset_keys()  # its key releases will never arrive

    def _reset_keys(self) -> None:
        """Forget which keys are held (after a keyboard vanished or events were
        dropped), so no key stays 'stuck' down. A recording in progress is dropped."""
        if self.tracker._active:
            self._emit([("cancel",)])
        self.tracker = self.tracker.fresh()

    def _emit(self, actions) -> None:
        for action in actions:
            try:
                self.on_action(action)
            except Exception:  # noqa: BLE001
                log.exception("hold-to-record action failed")

    def run(self) -> None:
        next_scan = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_scan:
                self._scan()
                next_scan = now + self.RESCAN_SECONDS
            deadline = self._capture["deadline"] if self._capture else self.tracker.pending_deadline
            timeout = next_scan - now if deadline is None else max(0.0, min(deadline, next_scan) - now)
            for key, _ in self._sel.select(timeout):
                if key.data == "wake":
                    os.read(self._wake_r, 64)
                else:
                    self._read(key.fd, key.data)
            if self._capture and self._capture.get("cancelled"):
                self._finish_capture()
            elif self._capture and time.monotonic() > self._capture["deadline"]:
                self._finish_capture("No keys pressed.")
            elif not self._capture:
                self._emit(self.tracker.poll(time.monotonic()))

    def _read(self, fd: int, path: str) -> None:
        try:
            data = os.read(fd, _EVENT.size * 64)
        except BlockingIOError:
            return
        except OSError as e:  # keyboard unplugged
            if e.errno in (errno.ENODEV, errno.EIO, errno.EBADF):
                self._close(path)
            return
        now = time.monotonic()
        for i in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
            _, _, etype, code, value = _EVENT.unpack_from(data, i)
            if etype == EV_SYN and code == SYN_DROPPED:
                self._reset_keys()  # the kernel dropped events: our key state is unreliable
                continue
            if etype != EV_KEY:
                continue
            if self._capture is not None:
                if value != 2:
                    self._feed_capture(code, value)
                if self._capture is not None and self._capture.get("cancelled"):
                    self._finish_capture()
            else:
                self._emit(self.tracker.feed(code, value, now))
