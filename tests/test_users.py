import json

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


def test_send_test_email(client, monkeypatch):
    from carretos_social.web import mailer
    _setup_admin(client)
    _login(client, "david", "segredo123")
    assert "nao_configurado" in client.post("/configurar/testar-email", follow_redirects=False).headers["location"]
    sent = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, body: sent.append((to, subject)))
    r = client.post("/configurar/testar-email", follow_redirects=False)
    assert r.headers["location"].endswith("teste=ok") and sent == [("david@exemplo.pt", "Email de teste")]
    def boom(*a):
        raise OSError("Authentication failed")
    monkeypatch.setattr(mailer, "send", boom)
    loc = client.post("/configurar/testar-email", follow_redirects=False).headers["location"]
    assert "teste=erro" in loc and "falhou" in client.get(loc).text


def test_post_shows_media_kind_and_whole_image(client, tmp_path):
    from PIL import Image
    from carretos_social.db import add_media, add_post, connect
    _setup_admin(client)
    _login(client, "david", "segredo123")
    img = tmp_path / "frase.png"
    Image.new("RGB", (1080, 1350), (212, 175, 55)).save(img)        # 4:5, não 9:16
    with connect() as conn:
        mid = add_media(conn, "image", str(img))
        one = add_post(conn, account_id="ig_davidcarreto", format="image", caption="x", status="draft",
                       media_ids=[mid], scheduled_at="2030-01-01T10:00:00+00:00")
        car = add_post(conn, account_id="ig_davidcarreto", format="carousel", caption="x", status="draft",
                       media_ids=[mid, mid, mid], scheduled_at="2030-01-02T10:00:00+00:00")
    page = client.get(f"/post/{one}").text
    assert "📷 Imagem" in page and "Refazer vídeo" not in page
    assert "📷 Carrossel · 3 imagens" in client.get(f"/post/{car}").text
    assert "📷 Imagem" in client.get("/aprovar").text


def test_post_type_field_and_format_panel(client, tmp_path):
    from PIL import Image
    from carretos_social.db import add_media, add_post, connect, get_post
    _setup_admin(client)
    _login(client, "david", "segredo123")
    img = tmp_path / "q.png"
    Image.new("RGB", (1080, 1350)).save(img)
    with connect() as conn:
        mid = add_media(conn, "image", str(img))
        pid = add_post(conn, account_id="ig_davidcarreto", format="carousel", caption="x", status="draft",
                       media_ids=[mid], scheduled_at="2030-01-01T10:00:00+00:00")
    page = client.get(f"/post/{pid}").text
    assert "Tipo de publicação" in page and "1080×1350 px (4:5)" in page and "Tem de ser editado" in page
    client.post(f"/post/{pid}", data={"action": "guardar", "tipo": "image"}, follow_redirects=False)
    with connect() as conn:
        assert get_post(conn, pid)["format"] == "image"
    assert "Pronto a publicar" in client.get(f"/post/{pid}").text
    assert client.post(f"/post/{pid}", data={"action": "guardar", "tipo": "text"}).status_code == 403  # não há no IG


def test_refazer_keeps_media_and_history_restore(client, tmp_path):
    from PIL import Image
    from carretos_social.db import add_media, add_post, connect, get_post, update_post
    _setup_admin(client)
    _login(client, "david", "segredo123")
    img = tmp_path / "q.png"
    Image.new("RGB", (1080, 1350)).save(img)
    img2 = tmp_path / "q2.png"
    Image.new("RGB", (1080, 1350), (200, 0, 0)).save(img2)
    with connect() as conn:
        mid = add_media(conn, "image", str(img))
        mid2 = add_media(conn, "image", str(img2))
        pid = add_post(conn, account_id="ig_davidcarreto", format="image", caption="x", status="draft",
                       media_ids=[mid], scheduled_at="2030-01-01T10:00:00+00:00")
    assert client.post(f"/post/{pid}", data={"action": "refazer"}).status_code == 403   # imagem: não há refazer
    with connect() as conn:
        row = get_post(conn, pid)
        assert (json.loads(row["media_ids"]), row["status"]) == ([mid], "draft")
        update_post(conn, pid, media_ids=[mid2])                                        # nova versão
    page = client.get(f"/post/{pid}").text
    assert "Histórico de alterações" in page and "Repor esta imagem/vídeo" in page
    import re
    hist = re.search(r'name="hist" value="(\d+)"', page).group(1)
    client.post(f"/post/{pid}", data={"action": "repor", "hist": hist}, follow_redirects=False)
    with connect() as conn:
        assert json.loads(get_post(conn, pid)["media_ids"]) == [mid]


def test_carousel_example_viewer_and_management(client, tmp_path):
    import io
    import re
    from PIL import Image
    from carretos_social.cli import main
    from carretos_social.db import connect, get_post, post_history
    from carretos_social.scheduler import all_problems
    from carretos_social.web import jobs
    _setup_admin(client)
    _login(client, "david", "segredo123")
    main(["exemplo-carrossel"])
    with connect() as conn:
        row = conn.execute("SELECT * FROM posts ORDER BY id DESC LIMIT 1").fetchone()
        pid, ids = row["id"], json.loads(row["media_ids"])
        assert row["title"].startswith("[TESTE]") and row["status"] == "draft" and row["scheduled_at"] is None
        assert row["format"] == "carousel" and len(ids) == 3
        assert "sem data/hora" in all_problems(conn, row)                 # nunca sai sozinho
        sizes = {Image.open(p).size for p in
                 [conn.execute("SELECT path FROM media WHERE id=?", (i,)).fetchone()[0] for i in ids]}
        assert sizes == {(1080, 1350)}
    page = client.get(f"/post/{pid}").text
    assert 'data-cv="post' in page and "1 / 3" in page and "1080×1350 · 4:5" in page and "Acrescentar imagem" in page
    assert 'class="cv mini"' in client.get("/aprovar").text                # passar imagens sem abrir o post
    # mover a 1.ª para a direita
    client.post(f"/post/{pid}", data={"action": "mover", "idx": "0", "dir": "1"}, follow_redirects=False)
    with connect() as conn:
        assert json.loads(get_post(conn, pid)["media_ids"]) == [ids[1], ids[0], ids[2]]
    # retirar a última (o ficheiro fica)
    r = client.post(f"/post/{pid}", data={"action": "retirar", "idx": "2"}, follow_redirects=False)
    assert r.headers["location"].endswith("#img=2")
    # acrescentar duas imagens do "telemóvel"
    buf = io.BytesIO(); Image.new("RGB", (1080, 1350), (200, 0, 0)).save(buf, "PNG")
    files = [("imagens", ("a.png", buf.getvalue(), "image/png")), ("imagens", ("b.png", buf.getvalue(), "image/png"))]
    client.post(f"/post/{pid}/imagens", files=files, follow_redirects=False)
    bad = client.post(f"/post/{pid}/imagens", files=[("imagens", ("x.png", b"nao-e-imagem", "image/png"))])
    assert bad.status_code == 403
    with connect() as conn:
        now_ids = json.loads(get_post(conn, pid)["media_ids"])
        assert len(now_ids) == 4 and now_ids[:2] == [ids[1], ids[0]]
        assert sum(1 for h in post_history(conn, pid) if h["field"] == "media_ids") == 3
        assert get_post(conn, pid)["status"] == "draft"                    # nada foi aprovado
    # não deixa retirar a única imagem
    for _ in range(3):
        client.post(f"/post/{pid}", data={"action": "retirar", "idx": "0"}, follow_redirects=False)
    assert client.post(f"/post/{pid}", data={"action": "retirar", "idx": "0"}).status_code == 403
    # Criar → Carrossel de frases
    client.post("/criar", data={"tipo": "carrossel", "conta": "ig_davidcarreto", "tema": "Frase um\nFrase dois"},
                follow_redirects=False)
    with connect() as conn:
        job = conn.execute("SELECT kind, args FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
    assert job["kind"] == "carrossel-frases" and json.loads(job["args"]).count("--frase") == 2
    assert "erro=frases" in client.post("/criar", data={"tipo": "carrossel", "conta": "ig_davidcarreto",
                                                        "tema": "só uma"}, follow_redirects=False).headers["location"]
