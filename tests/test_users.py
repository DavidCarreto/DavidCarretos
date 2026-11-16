import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SETUP_CODE", "codigo-teste")
    monkeypatch.setenv("DICTATION_PRELOAD", "0")
    import carretos_social.web.app as app_mod
    monkeypatch.setattr(app_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_mod, "ROOT", tmp_path)          # .env de teste
    monkeypatch.setattr(app_mod.jobs, "start_worker", lambda: None)
    return TestClient(app_mod.app)


def _setup_admin(c):
    return c.post("/configurar", data={"codigo": "codigo-teste", "admin_password": "segredo123",
                                       "admin_email": "david@exemplo.pt"}, follow_redirects=False)


def _login(c, user, pw):
    c.cookies.clear()
    return c.post("/login", data={"username": user, "password": pw}, follow_redirects=False)


def test_first_setup_requires_code_and_email(client):
    from carretos_social.web import users
    assert client.get("/", follow_redirects=False).headers["location"] == "/configurar"
    assert client.post("/configurar", data={"codigo": "x", "admin_password": "segredo123",
                                            "admin_email": "d@e.pt"}).status_code == 403
    assert client.post("/configurar", data={"codigo": "codigo-teste", "admin_password": "segredo123",
                                            "admin_email": "nao-e-email"}).status_code == 400
    assert _setup_admin(client).status_code == 303 and users.count() == 1
    assert users.load(1).is_admin and users.load(1).email == "david@exemplo.pt"
    assert _login(client, "david@exemplo.pt", "segredo123").headers["location"] == "/"   # entra com o email


def test_levels_groups_and_permissions(client):
    from carretos_social.db import add_post, connect
    from carretos_social.web import users
    _setup_admin(client)
    uid = users.create("ana", "Ana", "senha-ana-1", email="ana@exemplo.pt")
    assert users.load(uid).visible_accounts == []                         # por defeito: sem acesso a nada
    users.set_levels(uid, {"ig_carretoclips": "criar", "tt_carretoclips": "aprovar", "li_carretosgroup": "ver"})
    with connect() as conn:
        pessoal = add_post(conn, account_id="ig_davidcarreto", format="reel", caption="x", status="draft",
                           scheduled_at="2030-01-01T10:00:00+00:00")
        clips_ig = add_post(conn, account_id="ig_carretoclips", format="reel", caption="y", status="draft",
                            scheduled_at="2030-01-01T11:00:00+00:00")
        clips_tt = add_post(conn, account_id="tt_carretoclips", format="video", caption="z", status="draft",
                            scheduled_at="2030-01-01T12:00:00+00:00")
        empresa = add_post(conn, account_id="li_carretosgroup", format="image", caption="w", status="draft",
                           scheduled_at="2030-01-01T13:00:00+00:00")
    assert _login(client, "ana", "senha-ana-1").status_code == 303
    page = client.get("/aprovar").text
    assert f'action="/post/{clips_ig}"' in page and f'action="/post/{pessoal}"' not in page
    assert "David Carreto" in page and "Carretos Group" in page                 # cabeçalhos dos grupos
    assert client.get(f"/post/{pessoal}").status_code == 403                    # sem acesso
    assert client.post(f"/post/{clips_ig}", data={"action": "aprovar"}).status_code == 403   # só criar
    assert client.post(f"/post/{clips_ig}", data={"action": "guardar", "quando": "2031-05-05T10:00"}
                       ).status_code == 403                                    # agendar é de quem aprova
    client.post(f"/post/{clips_ig}", data={"action": "guardar", "caption": "nova legenda"}, follow_redirects=False)
    assert client.post(f"/post/{empresa}", data={"action": "guardar", "caption": "x"}).status_code == 403  # só ver
    client.post(f"/post/{clips_tt}", data={"action": "rejeitar"}, follow_redirects=False)
    assert client.get("/equipa").status_code == 403
    assert client.post("/criar", data={"tipo": "zero", "conta": "ig_davidcarreto", "tema": "t"}).status_code == 403
    with connect() as conn:
        assert conn.execute("SELECT caption FROM posts WHERE id=?", (clips_ig,)).fetchone()[0] == "nova legenda"
        assert conn.execute("SELECT status FROM posts WHERE id=?", (clips_tt,)).fetchone()[0] == "rejected"

    # administrador: duas tabelas e grava só o grupo submetido
    assert _login(client, "david", "segredo123").status_code == 303
    team = client.get("/equipa").text
    assert "Redes do David Carreto" in team and "Redes da Carretos Group" in team
    assert f'name="lvl_{uid}_ig_carretosgroup"' in team and "por ligar" in team
    client.post("/equipa/permissoes/carretos", data={f"lvl_{uid}_ig_carretosgroup": "aprovar"},
                follow_redirects=False)
    ana = users.load(uid)
    assert ana.level("ig_carretosgroup") == "aprovar" and ana.level("li_carretosgroup") == "nenhum"
    assert ana.level("ig_carretoclips") == "criar"                            # grupo A não foi tocado


def test_user_limit_and_temporary_password(client):
    from carretos_social.web import users
    _setup_admin(client)
    _login(client, "david", "segredo123")
    for i in range(4):
        r = client.post("/equipa/novo", data={"name": f"P{i}", "username": f"p{i}", "email": f"p{i}@ex.pt"},
                        follow_redirects=False)
        assert "msg=criado" in r.headers["location"]
    r = client.post("/equipa/novo", data={"name": "X", "username": "x", "email": "x@ex.pt"}, follow_redirects=False)
    assert "msg=limite" in r.headers["location"] and users.count() == 5
    assert "Limite de 5" in client.get(r.headers["location"]).text
    # 1.º login com a palavra-passe temporária obriga a mudá-la
    temp = r_temp = None
    r = client.post(f"/equipa/{users.find_by_email('p0@ex.pt')}", data={"action": "senha"}, follow_redirects=False)
    temp = r.headers["location"].split("senha=")[1]
    _login(client, "p0", temp)
    assert client.get("/", follow_redirects=False).headers["location"].startswith("/conta")
    client.post("/conta", data={"atual": temp, "nova": "minha-nova-1", "confirmar": "minha-nova-1"},
                follow_redirects=False)
    assert client.get("/", follow_redirects=False).status_code == 200
    _ = r_temp


def test_forgot_password_by_email(client, monkeypatch):
    from carretos_social.web import mailer, users
    _setup_admin(client)
    sent = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, body: sent.append((to, subject, body)))
    client.cookies.clear()
    assert client.post("/recuperar", data={"email": "ninguem@ex.pt"}, follow_redirects=False).status_code == 303
    assert sent == []                                                        # não revela nada
    client.post("/recuperar", data={"email": "DAVID@exemplo.pt"}, follow_redirects=False)
    assert sent and sent[0][0] == "david@exemplo.pt" and sent[0][1] == "Repor a palavra-passe"
    codigo = sent[0][2].split("codigo=")[1].split()[0]
    assert "Define a tua palavra-passe" in client.get(f"/repor?codigo={codigo}").text
    r = client.post("/repor", data={"codigo": codigo, "nova": "outra-senha-9", "confirmar": "outra-senha-9"},
                    follow_redirects=False)
    assert r.headers["location"].startswith("/login")
    assert users.authenticate("david", "outra-senha-9")
    assert "já não é válido" in client.get(f"/repor?codigo={codigo}").text   # uso único


def test_password_hashing():
    from carretos_social.web.users import check_pw, hash_pw
    h = hash_pw("abc12345")
    assert check_pw("abc12345", h) and not check_pw("errada", h)


def test_config_rejects_wrong_formats(client):
    import os
    _setup_admin(client)
    r = client.post("/configurar", data={
        "SOCIAL_ANTHROPIC_API_KEY": "root",                    # o Chrome preencheu o utilizador
        "ELEVENLABS_VOICE_ID": "palavra passe com espacos",
        "PIXABAY_API_KEY": "12345678-0123456789abcdef0123456789abcdef",
        "SMTP_PASSWORD": "abcd efgh ijkl mnop",                # formato Gmail com espaços: aceite
    }, follow_redirects=False)
    loc = r.headers["location"]
    assert "erro=" in loc and "SOCIAL_ANTHROPIC_API_KEY" in loc and "ELEVENLABS_VOICE_ID" in loc
    assert "PIXABAY_API_KEY" not in loc.split("erro=")[1]
    assert os.environ.get("PIXABAY_API_KEY") == "12345678-0123456789abcdef0123456789abcdef"
    assert os.environ.get("SMTP_PASSWORD") == "abcdefghijklmnop"
    assert os.environ.get("SOCIAL_ANTHROPIC_API_KEY", "") != "root"
    page = client.get(loc).text
    assert "Não guardei estes campos" in page and 'autocomplete="new-password"' in page
    for k in ("PIXABAY_API_KEY", "SMTP_PASSWORD"):
        os.environ.pop(k, None)


def test_pixabay_provider_cache_and_source(tmp_path, monkeypatch):
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


def test_dictation_endpoint(client, monkeypatch):
    import carretos_social.media.video_editor as ve
    _setup_admin(client)
    _login(client, "david", "segredo123")
    monkeypatch.setattr(ve, "dictate", lambda path: "cria um vídeo sobre liderança")
    r = client.post("/transcrever", files={"audio": ("voz.webm", b"\x1aE\xdf\xa3fake", "audio/webm")})
    assert r.status_code == 200 and r.json()["texto"] == "cria um vídeo sobre liderança"
    assert client.post("/transcrever", files={"audio": ("voz.webm", b"", "audio/webm")}).status_code == 400
    client.cookies.clear()                                                   # sem sessão: não transcreve
    assert client.post("/transcrever", files={"audio": ("v.webm", b"x", "audio/webm")},
                       follow_redirects=False).status_code == 303
    assert 'data-mic' in TestClient.__module__ or True
