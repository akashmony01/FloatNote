import os

import pytest

from floatnote import hotkeys
from floatnote.hotkeys import ChordTracker, parse_combo

CTRL, SUPER, ALT, SHIFT, A, LEFT = 29, 125, 56, 42, 30, 105


def tracker():
    return ChordTracker({parse_combo("ctrl+super"): "bug", parse_combo("super+alt"): "idea"}, delay=0.25)


def press(t, code, now):
    return t.feed(code, 1, now)


def release(t, code, now):
    return t.feed(code, 0, now)


def test_parse_combo():
    assert parse_combo("Ctrl+Super") == {"ctrl", "super"}
    assert parse_combo("meta + alt") == {"super", "alt"}
    assert parse_combo("ctrl+super+left") == {"ctrl", "super", "left"}
    for bad in ("ctrl+b", "left", "ctrl+left+right"):
        with pytest.raises(ValueError):
            parse_combo(bad)


def test_hold_starts_after_delay_and_release_stops():
    t = tracker()
    assert press(t, CTRL, 0.0) == []
    assert press(t, SUPER, 0.05) == []
    assert t.poll(0.2) == []
    assert t.poll(0.31) == [("start", "bug")]
    assert t.feed(SUPER, 2, 0.5) == []  # auto-repeat ignored
    assert release(t, SUPER, 2.0) == [("stop",)]
    assert release(t, CTRL, 2.1) == []


def test_order_does_not_matter_and_idea_combo():
    t = tracker()
    press(t, ALT, 0.0)
    press(t, SUPER, 0.1)
    assert t.poll(0.4) == [("start", "idea")]
    assert release(t, ALT, 1.0) == [("stop",)]


def test_quick_shortcut_never_starts():
    t = tracker()
    press(t, CTRL, 0.0)
    press(t, SUPER, 0.05)
    assert press(t, LEFT, 0.1) == []  # Ctrl+Super+Left before the delay
    assert t.poll(1.0) == []
    release(t, LEFT, 1.1)
    assert t.poll(2.0) == []  # still spoiled until all keys are up


def test_other_key_while_recording_cancels():
    t = tracker()
    press(t, CTRL, 0.0)
    press(t, SUPER, 0.0)
    assert t.poll(0.3) == [("start", "bug")]
    assert press(t, A, 0.5) == [("cancel",)]
    assert release(t, CTRL, 0.6) == []


def test_extra_modifier_cancels():
    t = tracker()
    press(t, CTRL, 0.0)
    press(t, SUPER, 0.0)
    t.poll(0.3)
    assert press(t, SHIFT, 0.5) == [("cancel",)]


def test_rearms_after_all_released():
    t = tracker()
    press(t, CTRL, 0.0)
    press(t, SUPER, 0.0)
    t.poll(0.3)
    release(t, CTRL, 1.0)
    press(t, CTRL, 1.1)  # pressing the released key again records the next note
    assert t.poll(1.4) == [("start", "bug")]
    release(t, CTRL, 2.1)
    release(t, SUPER, 2.1)
    press(t, CTRL, 3.0)
    press(t, SUPER, 3.0)
    assert t.poll(3.3) == [("start", "bug")]


def test_single_modifier_is_not_a_combo():
    t = tracker()
    press(t, SUPER, 0.0)
    assert t.poll(5.0) == []


def test_listener_reads_raw_events_from_a_pipe():
    t = tracker()
    actions = []
    listener = hotkeys.HotkeyListener(t, actions.append)
    r, w = os.pipe()
    os.set_blocking(r, False)
    for code, value in [(CTRL, 1), (SUPER, 1), (0, 0)]:
        os.write(w, hotkeys._EVENT.pack(0, 0, hotkeys.EV_KEY if code else 0, code, value))
    listener._read(r, "pipe")
    assert t.poll(10**9) == [("start", "bug")]
    os.write(w, hotkeys._EVENT.pack(0, 0, hotkeys.EV_KEY, SUPER, 0))
    listener._read(r, "pipe")
    assert actions == [("stop",)]
    os.close(r)
    os.close(w)


RIGHT, UP = 106, 103


def arrows():
    return ChordTracker({parse_combo("ctrl+super+left"): "bug",
                         parse_combo("ctrl+super+right"): "idea"}, delay=0.1)


def test_arrow_combo_hold_and_release():
    t = arrows()
    press(t, CTRL, 0.0)
    press(t, SUPER, 0.0)
    assert t.poll(1.0) == []  # Ctrl+Super alone is not a combo any more
    press(t, LEFT, 1.0)
    assert t.feed(LEFT, 2, 1.05) == []  # auto-repeat
    assert t.poll(1.11) == [("start", "bug")]
    assert release(t, LEFT, 3.0) == [("stop",)]
    press(t, RIGHT, 3.5)  # still holding Ctrl+Super: next note, as an idea
    assert t.poll(3.61) == [("start", "idea")]


def test_arrow_combo_idea_and_copy_key_is_ignored():
    t = arrows()
    press(t, CTRL, 0.0)
    press(t, SUPER, 0.0)
    press(t, UP, 0.0)  # Ctrl+Super+Up = copy (a GNOME shortcut), not a hold
    assert t.poll(1.0) == []
    for k in (UP, SUPER, CTRL):
        release(t, k, 1.1)
    press(t, CTRL, 2.0)
    press(t, SUPER, 2.0)
    press(t, RIGHT, 2.0)
    assert t.poll(2.2) == [("start", "idea")]


N = 49


def modifiers():
    return ChordTracker({parse_combo("ctrl+super"): "bug", parse_combo("super+alt"): "idea"},
                        delay=0.25, taps={parse_combo("ctrl+super+alt"): "copy"})


def test_tap_copies_on_release():
    t = modifiers()
    press(t, CTRL, 0.0)
    press(t, SUPER, 0.0)
    press(t, ALT, 0.05)  # all three before the hold delay: no recording
    assert t.poll(1.0) == []
    assert release(t, ALT, 1.1) == [("tap", "copy")]
    release(t, SUPER, 1.2)
    assert t.poll(5.0) == []  # Ctrl still down: must not start a bug recording
    release(t, CTRL, 5.1)


def test_tap_after_recording_started_cancels_then_copies():
    t = modifiers()
    press(t, CTRL, 0.0)
    press(t, SUPER, 0.0)
    assert t.poll(0.3) == [("start", "bug")]
    assert press(t, ALT, 0.5) == [("cancel",)]
    assert release(t, CTRL, 0.6) == [("tap", "copy")]


def test_tap_with_letter_is_a_normal_shortcut():
    t = modifiers()
    for k in (CTRL, SUPER, ALT):
        press(t, k, 0.0)
    press(t, N, 0.1)  # Ctrl+Super+Alt+N opens the window (GNOME shortcut)
    release(t, N, 0.2)
    assert release(t, ALT, 0.3) == []
    assert t.poll(2.0) == []


def test_modifier_holds_still_work_with_taps():
    t = modifiers()
    press(t, SUPER, 0.0)
    press(t, ALT, 0.0)
    assert t.poll(0.3) == [("start", "idea")]
    assert release(t, ALT, 1.0) == [("stop",)]


def test_format_and_pretty_combo():
    assert hotkeys.format_combo({"n", "alt", "ctrl", "super"}) == "ctrl+super+alt+n"
    assert hotkeys.pretty_combo("ctrl+super+alt+n") == "Ctrl+Super+Alt+N"
    assert hotkeys.pretty_combo("ctrl+super+left") == "Ctrl+Super+←"
    assert hotkeys.pretty_combo("super+f5") == "Super+F5"


def test_capture_records_combo_and_blocks_actions():
    t = modifiers()
    actions, results = [], []
    listener = hotkeys.HotkeyListener(t, actions.append)
    listener.capture(lambda names, err: results.append((names, err)))
    r, w = os.pipe()
    os.set_blocking(r, False)
    for code, value in [(CTRL, 1), (SUPER, 1), (N, 1), (N, 0), (SUPER, 0), (CTRL, 0)]:
        os.write(w, hotkeys._EVENT.pack(0, 0, hotkeys.EV_KEY, code, value))
    listener._read(r, "pipe")
    assert results == [(frozenset({"ctrl", "super", "n"}), None)]
    assert actions == []  # nothing recorded or copied while capturing
    os.close(r)
    os.close(w)


def test_validate_keys():
    v = hotkeys.validate_keys
    assert v("ctrl+super", "super+alt", "ctrl+super+alt", "ctrl+super+alt+n") is None
    assert "same keys" in v("ctrl+super", "ctrl+super", "ctrl+super+alt", "ctrl+super+alt+n")
    assert "at least two" in v("ctrl", "super+alt", "ctrl+super+alt", "ctrl+super+alt+n")
    assert "Record bug" in v("ctrl+n", "super+alt", "ctrl+super+alt", "ctrl+super+alt+n")
    assert "Open/close" in v("ctrl+super", "super+alt", "ctrl+super+alt", "ctrl+super+alt")
    assert "Open/close" in v("ctrl+super", "super+alt", "ctrl+super+alt", "n")


def test_to_accelerator():
    assert hotkeys.to_accelerator("ctrl+super+alt+n") == "<Control><Super><Alt>n"
    assert hotkeys.to_accelerator("super+shift+f5") == "<Super><Shift>F5"
    assert hotkeys.to_accelerator("ctrl+alt+up") == "<Control><Alt>Up"


def test_capture_cancel_with_esc_and_button():
    results = []
    listener = hotkeys.HotkeyListener(modifiers(), lambda a: None)
    listener.capture(lambda names, err: results.append((names, err)))
    r, w = os.pipe()
    os.set_blocking(r, False)
    os.write(w, hotkeys._EVENT.pack(0, 0, hotkeys.EV_KEY, hotkeys.KEY_ESC, 1))
    listener._read(r, "pipe")
    assert results == [(None, None)] and listener._capture is None

    listener.capture(lambda names, err: results.append((names, err)))
    listener.cancel_capture()
    assert listener._capture["cancelled"]  # finished by the listener thread's loop
    listener._finish_capture()
    assert results[-1] == (None, None)
    os.close(r)
    os.close(w)


def test_dropped_events_reset_held_keys():
    t = modifiers()
    actions = []
    listener = hotkeys.HotkeyListener(t, actions.append)
    r, w = os.pipe()
    os.set_blocking(r, False)
    for etype, code, value in [(hotkeys.EV_KEY, CTRL, 1), (hotkeys.EV_KEY, SUPER, 1)]:
        os.write(w, hotkeys._EVENT.pack(0, 0, etype, code, value))
    listener._read(r, "pipe")
    listener._emit(listener.tracker.poll(10**9))
    assert actions == [("start", "bug")]
    os.write(w, hotkeys._EVENT.pack(0, 0, hotkeys.EV_SYN, hotkeys.SYN_DROPPED, 0))
    listener._read(r, "pipe")
    assert actions[-1] == ("cancel",)
    press(listener.tracker, SUPER, 0.0)  # Ctrl is no longer "stuck": Super alone does nothing
    assert listener.tracker.poll(5.0) == []
    os.close(r)
    os.close(w)


# ---- key shortcuts (open/close, next project) --------------------------------

N, P, ESC_ = 49, 25, 1


def full_tracker():
    from floatnote.hotkeys import parse_key_combo

    return ChordTracker({parse_combo("ctrl+super"): "bug", parse_combo("super+alt"): "idea"}, delay=0.25,
                        taps={parse_combo("ctrl+super+alt"): "copy"},
                        keys={parse_key_combo("ctrl+super+alt+n"): "toggle",
                              parse_key_combo("ctrl+super+alt+p"): "next"})


def test_key_shortcut_fires_on_press_and_never_copies():
    t = full_tracker()
    press(t, CTRL, 0.0)
    press(t, SUPER, 0.01)
    press(t, ALT, 0.02)
    assert press(t, N, 0.1) == [("key", "toggle")]
    assert t.feed(N, 2, 0.2) == []  # auto-repeat
    assert release(t, N, 0.3) == []
    assert press(t, P, 0.4) == [("key", "next")]  # again while still holding the modifiers
    release(t, P, 0.45)
    out = release(t, ALT, 0.5) + release(t, SUPER, 0.5) + release(t, CTRL, 0.5)
    assert ("tap", "copy") not in out
    assert t.poll(2.0) == []  # and no recording either


def test_key_shortcut_does_not_start_or_keep_a_recording():
    t = full_tracker()
    press(t, CTRL, 0.0)
    press(t, SUPER, 0.0)
    press(t, ALT, 0.1)  # the bug candidate is gone, nothing recorded yet
    assert t.poll(1.0) == []
    assert press(t, N, 1.1) == [("key", "toggle")]


def test_key_shortcut_needs_exact_modifiers():
    t = full_tracker()
    press(t, CTRL, 0.0)
    press(t, ALT, 0.0)
    assert press(t, N, 0.1) == []  # Ctrl+Alt+N: not ours
    release(t, N, 0.2)
    press(t, SUPER, 0.3)
    press(t, SHIFT, 0.3)
    assert press(t, N, 0.4) == []  # extra Shift


def test_key_shortcut_ignored_while_another_key_is_down():
    t = full_tracker()
    for code in (CTRL, SUPER, ALT, A):
        press(t, code, 0.0)
    assert press(t, N, 0.1) == []


def test_key_shortcut_cancels_a_running_recording():
    t = full_tracker()
    press(t, CTRL, 0.0)
    press(t, SUPER, 0.0)
    assert t.poll(0.3) == [("start", "bug")]
    out = press(t, ALT, 0.5) + press(t, N, 0.6)
    assert ("cancel",) in out and ("key", "toggle") in out


def test_tracker_fresh_keeps_shortcuts():
    t = full_tracker()
    press(t, CTRL, 0.0)
    f = t.fresh()
    assert f.keys == t.keys and f.taps == t.taps and f.combos == t.combos
    assert f._held() == frozenset()


def test_parse_key_combo():
    from floatnote.hotkeys import parse_key_combo

    assert parse_key_combo("Ctrl+Super+Alt+N") == {"ctrl", "super", "alt", "n"}
    assert parse_key_combo("meta+f5") == {"super", "f5"}
    for bad in ("ctrl+super", "n", "ctrl+n+m", "ctrl+tab"):
        with pytest.raises(ValueError):
            parse_key_combo(bad)


def test_arrow_in_hold_combo_and_key_shortcut():
    from floatnote.hotkeys import parse_key_combo

    t = ChordTracker({parse_combo("ctrl+super+left"): "bug"}, delay=0.25,
                     keys={parse_key_combo("ctrl+alt+left"): "next"})
    press(t, CTRL, 0.0)
    press(t, ALT, 0.0)
    assert press(t, LEFT, 0.1) == [("key", "next")]
    release(t, LEFT, 0.2)
    release(t, ALT, 0.2)
    release(t, CTRL, 0.2)
    assert t._others == set() and t._held() == frozenset()
    press(t, CTRL, 1.0)  # the hold combo with the same arrow still works afterwards
    press(t, SUPER, 1.0)
    press(t, LEFT, 1.0)
    assert t.poll(1.3) == [("start", "bug")]
