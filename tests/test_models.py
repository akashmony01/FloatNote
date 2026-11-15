import pytest

from floatnote import cli, models


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    system, data = tmp_path / "system", tmp_path / "data"
    monkeypatch.setenv("FLOATNOTE_SYSTEM_MODELS", str(system))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setattr(models, "_in_hf_cache", lambda name: None)
    return system, data / "floatnote" / "models"


def fake_download(calls):
    def download_model(name, output_dir=None, **kw):
        calls.append((name, output_dir))
        (models.Path(output_dir) / "model.bin").write_text("x")
        return output_dir
    return download_model


def put(base, name, complete=True):
    (base / name).mkdir(parents=True)
    (base / name / "model.bin").write_text("x")
    if complete:
        (base / name / models.COMPLETE).write_text(name)


def test_system_folder_wins_then_user_folder(dirs):
    system, user = dirs
    assert models.local_path("small.en") is None
    put(user, "small.en")
    assert models.local_path("small.en") == user / "small.en"
    put(system, "small.en")
    assert models.local_path("small.en") == system / "small.en"


def test_interrupted_download_is_not_used(dirs):
    _, user = dirs
    put(user, "base.en", complete=False)
    assert models.local_path("base.en") is None and not models.is_downloaded("base.en")


def test_resolve_downloads_missing_model_into_user_folder(dirs, monkeypatch):
    _, user = dirs
    calls = []
    monkeypatch.setattr("faster_whisper.utils.download_model", fake_download(calls))
    assert models.resolve("base.en") == str(user / "base.en")
    assert models.local_path("base.en") == user / "base.en"
    assert models.resolve("base.en") == str(user / "base.en") and len(calls) == 1  # no second download


def test_resolve_uses_old_hugging_face_cache(dirs, monkeypatch):
    monkeypatch.setattr(models, "_in_hf_cache", lambda name: "/home/u/.cache/hf/snap")
    monkeypatch.setattr("faster_whisper.utils.download_model", lambda *a, **k: pytest.fail("no download"))
    assert models.resolve("small.en") == "/home/u/.cache/hf/snap"


def test_download_models_command(dirs, monkeypatch):
    system, user = dirs
    calls = []
    monkeypatch.setattr("faster_whisper.utils.download_model", fake_download(calls))
    assert cli.main(["download-models"]) == 0
    assert [c[0] for c in calls] == ["small.en", "base.en"]
    assert models.local_path("base.en") == user / "base.en"
    assert cli.main(["download-models"]) == 0 and len(calls) == 2  # already there
    assert cli.main(["download-models", "--system", "base.en"]) == 0
    assert models.local_path("base.en") == system / "base.en"


def test_download_models_failure_is_reported(dirs, monkeypatch, capsys):
    def offline(*a, **k):
        raise OSError("no internet")

    monkeypatch.setattr("faster_whisper.utils.download_model", offline)
    assert cli.main(["download-models", "base.en"]) == 1
    assert "first start" in capsys.readouterr().err
