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
