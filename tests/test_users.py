import importlib

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    monkeypatch.setenv("SETUP_CODE", "codigo-teste")
    import carretos_social.web.app as app_mod
    monkeypatch.setattr(app_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_mod, "ROOT", tmp_path)          # .env de teste
    monkeypatch.setattr(app_mod.jobs, "start_worker", lambda: None)
    return TestClient(app_mod.app)


def _login(c, user, pw):
    return c.post("/login", data={"username": user, "password": pw}, follow_redirects=False)


def test_first_setup_and_permissions(client):
    from carretos_social.db import add_post, connect
    from carretos_social.web import users

    # 1.ª configuração: sem código certo não entra
    assert client.get("/", follow_redirects=False).headers["location"] == "/configurar"
    assert client.post("/configurar", data={"codigo": "x", "admin_password": "segredo123"}).status_code == 403
    r = client.post("/configurar", data={"codigo": "codigo-teste", "admin_password": "segredo123"},
                    follow_redirects=False)
    assert r.status_code == 303 and users.count() == 1

    # colaboradora: cria no Carreto Clips (Instagram), aprova só no TikTok do Carreto Clips
    uid = users.create("ana", "Ana", "senha-ana-1")
    users.set_perms(uid, {"ig_carretoclips": {"create": True}, "tt_carretoclips": {"create": True, "approve": True}})
    with connect() as conn:
        pessoal = add_post(conn, account_id="ig_davidcarreto", format="reel", caption="x", status="draft",
                           scheduled_at="2030-01-01T10:00:00+00:00")
        clips_ig = add_post(conn, account_id="ig_carretoclips", format="reel", caption="y", status="draft",
                            scheduled_at="2030-01-01T11:00:00+00:00")
        clips_tt = add_post(conn, account_id="tt_carretoclips", format="video", caption="z", status="draft",
                            scheduled_at="2030-01-01T12:00:00+00:00")

    ana = client
    ana.cookies.clear()
    assert _login(ana, "ana", "senha-ana-1").status_code == 303
    page = ana.get("/aprovar").text
    assert f'action="/post/{clips_ig}"' in page and f'action="/post/{pessoal}"' not in page  # não vê as pessoais
    assert ana.get(f"/post/{pessoal}").status_code == 403
    assert ana.post(f"/post/{pessoal}", data={"action": "aprovar"}).status_code == 403
    assert ana.post(f"/post/{clips_ig}", data={"action": "aprovar"}).status_code == 403   # só cria aqui
    ana.post(f"/post/{clips_tt}", data={"action": "rejeitar"}, follow_redirects=False)     # aqui pode
    assert ana.get("/equipa").status_code == 403                         # não gere a equipa
    assert ana.post("/criar", data={"tipo": "zero", "conta": "ig_davidcarreto", "tema": "t"}).status_code == 403
    with connect() as conn:
        assert conn.execute("SELECT status FROM posts WHERE id=?", (clips_tt,)).fetchone()[0] == "rejected"

    # administrador vê tudo
    ana.cookies.clear()
    assert _login(client, "david", "segredo123").status_code == 303
    assert client.get(f"/post/{pessoal}").status_code == 200
    assert client.get("/equipa").status_code == 200
    _ = importlib  # mantém import


def test_password_hashing():
    from carretos_social.web.users import check_pw, hash_pw
    h = hash_pw("abc12345")
    assert check_pw("abc12345", h) and not check_pw("errada", h)


def test_config_rejects_wrong_formats(client):
    import os
    r = client.post("/configurar", data={
        "codigo": "codigo-teste", "admin_password": "segredo123",
        "SOCIAL_ANTHROPIC_API_KEY": "root",                    # o Chrome preencheu o utilizador
        "ELEVENLABS_VOICE_ID": "palavra passe com espacos",
        "PIXABAY_API_KEY": "12345678-0123456789abcdef0123456789abcdef",
    }, follow_redirects=False)
    loc = r.headers["location"]
    assert "erro=" in loc and "SOCIAL_ANTHROPIC_API_KEY" in loc and "ELEVENLABS_VOICE_ID" in loc
    assert "PIXABAY_API_KEY" not in loc.split("erro=")[1]
    assert os.environ.get("PIXABAY_API_KEY") == "12345678-0123456789abcdef0123456789abcdef"
    assert os.environ.get("SOCIAL_ANTHROPIC_API_KEY", "") != "root"
    page = client.get(loc).text
    assert "Não guardei estes campos" in page and 'autocomplete="new-password"' in page


def test_pixabay_provider_cache_and_source(tmp_path, monkeypatch):
    import json as _json
    from carretos_social.media import stock
    monkeypatch.setattr(stock, "DATA_DIR", tmp_path)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.setenv("PIXABAY_API_KEY", "1-abc")
    calls = []

    class R:
        def __init__(self, data=None, content=b"x"):
            self._d, self.content = data, content

        def json(self):
            return self._d

    def fake_request(method, url, **kw):
        calls.append(url)
        if url == stock.PIXABAY_VID:
            return R({"hits": [{"id": 7, "duration": 10, "pageURL": "https://pixabay.com/videos/id-7/",
                                "user": "autor", "downloads": 5,
                                "videos": {"large": {"url": "https://cdn.pixabay.com/v.mp4", "width": 1080,
                                                     "height": 1920}}}]})
        return R(content=b"VIDEO")
    monkeypatch.setattr(stock, "request", fake_request)
    assert stock.stock_provider() == "pixabay"
    p1 = stock.find_visual("mechanic workshop", "video")
    assert p1 and p1.read_bytes() == b"VIDEO"                     # descarregado (sem hotlink)
    assert stock.source_of(p1)["fonte"] == "Pixabay"
    n = len(calls)
    stock.pixabay_video("mechanic workshop")                       # 2.ª vez: API vem da cache de 24 h
    assert len(calls) == n
    monkeypatch.setenv("PEXELS_API_KEY", "x" * 56)
    assert stock.stock_provider() == "pexels"                      # Pexels tem prioridade se existir
    _ = _json
