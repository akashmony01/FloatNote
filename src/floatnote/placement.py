"""Where the dropdown opens: next to the tray icon, on the panel's side.

Pure functions (no GTK) so they can be tested. Rectangles are (x, y, width,
height) in screen coordinates; `area` is the monitor's work area (the monitor
minus its panels), which tells us where the panel is.
"""

Rect = tuple[int, int, int, int]


def panel_side(monitor: Rect, area: Rect, click: tuple[int, int] | None = None) -> str:
    """'top', 'bottom', 'left' or 'right': the panel the tray icon is on.

    A click on the icon lands on its panel, outside the work area. Without a
    click, guess: a horizontal panel (where trays usually are) over a side
    dock, the bigger one first."""
    mx, my, mw, mh = monitor
    ax, ay, aw, ah = area
    if click is not None:
        x, y = click
        if y < ay:
            return "top"
        if y >= ay + ah:
            return "bottom"
        if x < ax:
            return "left"
        if x >= ax + aw:
            return "right"
        # Inside the work area (floating or auto-hiding panel): the nearest edge.
        edges = {"top": y - my, "bottom": my + mh - y, "left": x - mx, "right": mx + mw - x}
        return min(edges, key=edges.get)
    gaps = {"top": ay - my, "bottom": (my + mh) - (ay + ah),
            "left": ax - mx, "right": (mx + mw) - (ax + aw)}
    for sides in (("top", "bottom"), ("left", "right")):
        side = max(sides, key=gaps.get)
        if gaps[side] > 0:
            return side
    return "top"  # no panel found (auto-hide)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def place(monitor: Rect, area: Rect, size: tuple[int, int],
          click: tuple[int, int] | None = None, side: str | None = None) -> tuple[int, int]:
    """Top-left corner for a window of `size`.

    With a click on the tray icon: flush against the panel, centred on the
    click along it (kept inside the work area). Without one (opened by a
    shortcut): the corner where the panel meets the right edge (left edge for a
    left panel), which is where tray icons usually are. `side` overrides the
    panel guess (e.g. the side of the last click).
    """
    ax, ay, aw, ah = area
    w, h = size
    side = panel_side(monitor, area, click) if click is not None or side is None else side
    right, bottom = ax + aw - w, ay + ah - h
    if side in ("top", "bottom"):
        y = ay if side == "top" else bottom
        x = right if click is None else _clamp(click[0] - w // 2, ax, right)
    else:
        x = ax if side == "left" else right
        y = ay if click is None else _clamp(click[1] - h // 2, ay, bottom)
    return max(x, ax), max(y, ay)


def usable_click(monitor: Rect, x: int | None, y: int | None) -> tuple[int, int] | None:
    """The tray's click position, if it looks real. Some panels send (0, 0), and
    with display scaling the numbers can be off-screen: then use the corner."""
    if x is None or y is None or (x, y) == (0, 0):
        return None
    mx, my, mw, mh = monitor
    if not (mx <= x < mx + mw and my <= y < my + mh):
        return None
    return x, y
