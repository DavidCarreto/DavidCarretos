import pytest


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    import carretos_social.config as cfg
    import carretos_social.db as db
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    yield tmp_path
