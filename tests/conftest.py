import pytest


@pytest.fixture(autouse=True)
def isolated_marvis_home(tmp_path, monkeypatch):
    home = tmp_path / "marvis-home"
    home.mkdir()
    monkeypatch.setenv("MARVIS_HOME", str(home))
    monkeypatch.delenv("MARVIS_MODE", raising=False)
    return home
