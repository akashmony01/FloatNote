from floatnote.store import Store, format_paste


def test_session_ideas_edit_delete(tmp_path):
    s = Store(tmp_path / "n.db")
    a = s.add("bug", "first", 2.0)
    b = s.add("bug", "second")
    i = s.add("idea", "an idea")
    assert [n.text for n in s.session_notes()] == ["first", "second"]
    assert s.update_text(a, "first fixed")
    assert s.get(a).updated_at is not None
    assert s.delete(b)
    assert s.set_kind(a, "idea")
    assert s.session_notes() == []
    assert [n.id for n in s.ideas()] == [i, a]  # newest first (by creation)
    assert s.set_done(i, True)
    assert [n.id for n in s.ideas()] == [a]
    assert len(s.ideas(include_done=True)) == 2
    assert not s.delete(999)


def test_undo_restores_latest_batch_only(tmp_path):
    s = Store(tmp_path / "n.db")
    one = s.add("bug", "one")
    s.archive_session([one])
    two = s.add("bug", "two")
    s.archive_session([two])
    assert s.undo_last_batch() == 1
    assert [n.text for n in s.session_notes()] == ["two"]
    assert s.undo_last_batch() == 1
    assert len(s.session_notes()) == 2
    assert s.undo_last_batch() == 0


def test_archive_ignores_ideas(tmp_path):
    s = Store(tmp_path / "n.db")
    i = s.add("idea", "keep me")
    s.archive_session([i])
    assert s.get(i).archived_at is None


def test_persists_and_readonly(tmp_path):
    path = tmp_path / "n.db"
    s = Store(path)
    s.add("bug", "survives")
    s.close()
    ro = Store(path, readonly=True)
    assert ro.session_notes()[0].text == "survives"


def test_format_paste():
    s = Store.__new__(Store)  # format only needs notes
    from floatnote.store import Note
    notes = [Note(1, "bug", "a", "", None, False, None, None, None),
             Note(2, "bug", "b", "", None, False, None, None, None)]
    assert format_paste("Intro:", notes) == "Intro:\n\n1. a\n2. b\n"
    assert format_paste("", notes) == "1. a\n2. b\n"


def test_ideas_markdown_export(tmp_path):
    md = tmp_path / "ideas.md"
    s = Store(tmp_path / "n.db", export_path=md)
    assert "## Open (0)" in md.read_text()
    i = s.add("idea", "dark mode toggle")
    s.add("bug", "not exported")
    assert "- [ ] dark mode toggle" in md.read_text()
    s.set_done(i, True)
    text = md.read_text()
    assert "- [x] dark mode toggle" in text and "not exported" not in text


def test_resample_length_and_passthrough():
    import numpy as np
    from floatnote.recorder import resample
    a = np.ones(48000, dtype=np.float32)
    assert len(resample(a, 48000, 16000)) == 16000
    assert resample(a, 16000, 16000) is a
