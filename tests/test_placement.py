from floatnote.placement import panel_side, place, usable_click

MONITOR = (0, 0, 1920, 1080)
SIZE = (400, 600)


def test_panel_side():
    assert panel_side(MONITOR, (0, 32, 1920, 1048)) == "top"      # GNOME
    assert panel_side(MONITOR, (0, 0, 1920, 1036)) == "bottom"    # KDE, Cinnamon
    assert panel_side(MONITOR, (48, 0, 1872, 1080)) == "left"     # only a dock on the left
    assert panel_side(MONITOR, (0, 0, 1880, 1080)) == "right"
    assert panel_side(MONITOR, MONITOR) == "top"                  # auto-hidden panel
    # A top panel plus a wider dock on the left: the tray is in the top panel.
    assert panel_side(MONITOR, (60, 30, 1860, 1050)) == "top"


def test_panel_side_from_click():
    area = (60, 30, 1860, 1050)
    assert panel_side(MONITOR, area, (1850, 15)) == "top"
    assert panel_side(MONITOR, area, (20, 500)) == "left"
    assert panel_side(MONITOR, (0, 0, 1920, 1036), (1800, 1050)) == "bottom"
    assert panel_side(MONITOR, MONITOR, (1900, 1070)) == "bottom"  # floating panel: nearest edge


def test_top_panel_with_left_dock():
    area = (60, 30, 1860, 1050)
    assert place(MONITOR, area, SIZE, (1850, 15)) == (1520, 30)
    assert place(MONITOR, area, SIZE) == (1520, 30)
    assert place(MONITOR, area, SIZE, side="left") == (60, 30)    # last click was on the dock


def test_top_panel_click_and_shortcut():
    area = (0, 32, 1920, 1048)
    assert place(MONITOR, area, SIZE) == (1520, 32)               # top-right, as in 1.0
    assert place(MONITOR, area, SIZE, (1800, 10)) == (1520, 32)   # icon near the edge: flush right
    assert place(MONITOR, area, SIZE, (900, 10)) == (700, 32)     # centred under the icon


def test_bottom_panel_click_and_shortcut():
    area = (0, 0, 1920, 1036)
    assert place(MONITOR, area, SIZE) == (1520, 436)              # bottom-right, above the panel
    assert place(MONITOR, area, SIZE, (1700, 1060)) == (1500, 436)
    assert place(MONITOR, area, SIZE, (50, 1060)) == (0, 436)     # kept on screen


def test_side_panels():
    assert place(MONITOR, (48, 0, 1872, 1080), SIZE, (20, 300)) == (48, 0)
    assert place(MONITOR, (0, 0, 1880, 1080), SIZE, (1900, 700)) == (1480, 400)


def test_second_monitor_offsets():
    monitor, area = (1920, 0, 2560, 1440), (1920, 0, 2560, 1400)
    assert place(monitor, area, SIZE, (4000, 1420)) == (3800, 800)


def test_usable_click():
    assert usable_click(MONITOR, 0, 0) is None
    assert usable_click(MONITOR, None, None) is None
    assert usable_click(MONITOR, 5000, 10) is None                # off-screen (scaling mix-up)
    assert usable_click(MONITOR, 1800, 1060) == (1800, 1060)
