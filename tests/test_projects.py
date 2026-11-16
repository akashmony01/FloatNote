import sqlite3

import pytest

from floatnote.store import GENERAL_ID, Store


def test_old_database_moves_bugs_into_general(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)  # a version-1 database, as created by FloatNote before projects
    db.executescript("""
        CREATE TABLE notes (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT, done INTEGER NOT NULL DEFAULT 0,
          archived_at TEXT, batch_id TEXT, duration_s REAL);
        INSERT INTO notes (kind, text, created_at) VALUES ('bug', 'old bug', '2026-11-12T10:00:00');
        INSERT INTO notes (kind, text, created_at) VALUES ('idea', 'old idea', '2026-11-12T10:00:00');
        PRAGMA user_version=1;
    """)
    db.close()
    s = Store(path)
    assert [p.name for p in s.projects()] == ["General"]
    assert s.session_notes(GENERAL_ID)[0].text == "old bug"
    assert s.todos()[0].project_id is None
    assert s.active_project_id() == GENERAL_ID


def test_bugs_are_per_project_and_ideas_shared(tmp_path):
    s = Store(tmp_path / "n.db")
    web = s.add_project("Client website")
    s.add("bug", "general bug")
    s.add("bug", "web bug", project_id=web)
    s.add("todo", "shared idea", project_id=web)  # ideas ignore projects
    assert [n.text for n in s.session_notes(web)] == ["web bug"]
    assert [n.text for n in s.session_notes(GENERAL_ID)] == ["general bug"]
    assert len(s.session_notes()) == 2
    assert s.todos()[0].project_id is None
    assert s.bug_counts() == {GENERAL_ID: 1, web: 1}


def test_project_names_unique_and_general_protected(tmp_path):
    s = Store(tmp_path / "n.db")
    s.add_project("App")
    with pytest.raises(ValueError):
        s.add_project("app")
    with pytest.raises(ValueError):
        s.add_project("  ")
    with pytest.raises(ValueError):
        s.delete_project(GENERAL_ID)
    s.rename_project(GENERAL_ID, "Inbox")
    assert s.project(GENERAL_ID).name == "Inbox"


def test_delete_project_moves_or_deletes_bugs(tmp_path):
    s = Store(tmp_path / "n.db")
    a, b = s.add_project("A"), s.add_project("B")
    s.add("bug", "a1", project_id=a)
    s.add("bug", "b1", project_id=b)
    s.set_active_project(a)
    s.delete_project(a)  # default: move to General
    assert [n.text for n in s.session_notes(GENERAL_ID)] == ["a1"]
    assert s.active_project_id() == GENERAL_ID
    s.delete_project(b, move_bugs_to=None)
    assert all(n.text != "b1" for n in s.session_notes())


def test_folder_matching(tmp_path):
    s = Store(tmp_path / "n.db")
    code = tmp_path / "code"
    (code / "site" / "src").mkdir(parents=True)
    outer = s.add_project("Code", folder=str(code))
    site = s.add_project("Site", folder=str(code / "site"))
    assert s.project_for_folder(str(code / "site" / "src")).id == site  # closest wins
    assert s.project_for_folder(str(code)).id == outer
    assert s.project_for_folder(str(tmp_path)) is None


def test_moving_bug_to_idea_drops_project(tmp_path):
    s = Store(tmp_path / "n.db")
    web = s.add_project("Web")
    n = s.add("bug", "x", project_id=web)
    s.set_kind(n, "todo")
    assert s.get(n).project_id is None


def _cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))  # no daemon running here
    from floatnote import paths
    return Store(paths.db_file())


def test_cli_list_picks_project_by_name_folder_then_active(tmp_path, monkeypatch, capsys):
    from floatnote import cli

    s = _cli_env(tmp_path, monkeypatch)
    site = tmp_path / "site"
    (site / "src").mkdir(parents=True)
    web = s.add_project("Web", folder=str(site))
    s.add("bug", "general bug")
    s.add("bug", "web bug", project_id=web)
    s.close()

    monkeypatch.chdir(site / "src")  # linked folder (a subfolder of it)
    cli.main(["list"])
    assert capsys.readouterr().out == "Project: Web\n1. web bug\n"

    monkeypatch.chdir(tmp_path)  # not linked: the active project (General)
    cli.main(["list"])
    assert "1. general bug" in capsys.readouterr().out

    cli.main(["list", "--project", "web", "--json"])
    assert '"bugs": [\n    "web bug"\n  ]' in capsys.readouterr().out


def test_cli_take_archives_and_project_switch(tmp_path, monkeypatch, capsys):
    from floatnote import cli

    s = _cli_env(tmp_path, monkeypatch)
    s.add_project("Web")
    s.add("bug", "general bug")
    s.close()
    monkeypatch.chdir(tmp_path)
    cli.main(["list", "--take"])
    assert "1. general bug" in capsys.readouterr().out
    cli.main(["list"])
    assert "No bugs waiting" in capsys.readouterr().out

    assert cli.main(["project", "web"]) == 0
    cli.main(["project"])
    assert capsys.readouterr().out.strip().endswith("Web")
    cli.main(["projects"])
    out = capsys.readouterr().out
    assert "* Web" in out and "  General" in out
    assert cli.main(["project", "nope"]) == 1


def test_bar_label_shortens_long_names():
    from floatnote.tray import bar_label
    assert bar_label("Client website") == "Client website"
    assert bar_label("My very long project name") == "My very long pr…"
    assert len(bar_label("My very long project name")) == 16
    assert bar_label("  spaced   out  ") == "spaced out"


def test_interrupted_migration_can_be_rerun(tmp_path):
    path = tmp_path / "n.db"
    Store(path).close()
    db = sqlite3.connect(path)  # pretend the version bump was lost after the ALTER
    db.execute("PRAGMA user_version=1")
    db.commit()
    db.close()
    s = Store(path)  # must not fail with "duplicate column name"
    assert s.projects()[0].name == "General"


def test_cli_take_reports_daemon_errors(tmp_path, monkeypatch, capsys):
    from floatnote import cli, client

    s = _cli_env(tmp_path, monkeypatch)
    s.add("bug", "a bug")
    s.close()
    monkeypatch.chdir(tmp_path)

    def timeout(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(client, "send", timeout)
    assert cli.main(["list", "--take"]) == 1
    assert "Undo" in capsys.readouterr().err

    monkeypatch.setattr(client, "send", lambda *a, **k: {"ok": False, "error": "no such project"})
    assert cli.main(["list", "--take"]) == 1
    assert "no such project" in capsys.readouterr().err
