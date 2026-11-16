import xml.etree.ElementTree as ET

import pytest

pytest.importorskip("gi")
from floatnote import tray  # noqa: E402


@pytest.mark.parametrize("name, expected", [
    ("Client website", "CW"),
    ("FloatNote", "FN"),
    ("floatnote", "Fl"),
    ("General", "Ge"),
    ("x", "X"),
    ("my-app 2", "MA"),
    ("  café  über ", "CÜ"),
    ("🚀 Rocket", "Ro"),
    ("!!!", ""),
])
def test_project_initials(name, expected):
    assert tray.project_initials(name) == expected


def test_icon_svg_is_valid_and_escaped():
    svg = tray.icon_svg("bug", "<&")
    root = ET.fromstring(svg)  # well-formed even with XML characters in the text
    assert root.tag.endswith("svg")
    assert tray.COLORS["bug"] in svg
    assert "".join(root.itertext()) == "<&"


def test_badge_icon_written_once_per_state_and_initials(tmp_path):
    a = tray.badge_icon(tmp_path, "idle", "CW")
    b = tray.badge_icon(tmp_path, "bug", "CW")
    assert a != b and (tmp_path / f"{a}.svg").exists()
    assert tray.badge_icon(tmp_path, "idle", "CW") == a
    assert tray.badge_icon(tmp_path, "idle", "É").isascii()  # safe file names
