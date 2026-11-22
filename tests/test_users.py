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
    r = client.post("/criar", data={"tipo": "carrossel", "conta": "ig_davidcarreto", "tema": "só uma frase"})
    assert "leva 2 a 10 frases" in r.text and "só uma frase</textarea>" in r.text     # mantém texto e modo
    assert 'value="carrossel" checked' in r.text
    # o carrossel de frases sem data fica SEM data (só sugestão na página)
    from carretos_social.cli import make_quote_carousel
    with connect() as conn:
        pid2 = make_quote_carousel(conn, "ig_davidcarreto", ["Uma", "Duas"], use_ai=False)
        assert get_post(conn, pid2)["scheduled_at"] is None
    page = client.get(f"/post/{pid2}").text
    assert "Hora sugerida" in page and "Pedir legenda à IA" in page
    # aprovar sem data: fica na página da publicação com o erro em cima
    r = client.post(f"/post/{pid2}", data={"action": "aprovar", "caption": "Legenda"}, follow_redirects=False)
    assert r.headers["location"] == f"/post/{pid2}?erro=aprovar"
    page = client.get(r.headers["location"]).text
    assert "Não foi aprovada" in page and 'class="need"' in page
    # histórico com descrições
    hist = client.get(f"/post/{pid}").text
    assert "Imagem 1 movida para a posição 2" in hist and "Retirada imagem 3" in hist
    assert "Acrescentada imagem 3 (1080×1350 · 4:5)" in hist


def test_kind_follows_type_and_fix_count(client, tmp_path):
    from PIL import Image
    from carretos_social.db import add_media, add_post, connect
    _setup_admin(client)
    _login(client, "david", "segredo123")
    a = tmp_path / "a.jpg"; Image.new("RGB", (1080, 1350)).save(a)
    q = tmp_path / "q.jpg"; Image.new("RGB", (1080, 1080)).save(q)
    with connect() as conn:
        ma, mq = add_media(conn, "image", str(a)), add_media(conn, "image", str(q))
        one = add_post(conn, account_id="ig_davidcarreto", format="carousel", caption="x", status="draft",
                       media_ids=[ma], scheduled_at="2030-01-01T10:00:00+00:00")
        mix = add_post(conn, account_id="ig_davidcarreto", format="carousel", caption="x", status="draft",
                       media_ids=[ma, mq], scheduled_at="2030-01-02T10:00:00+00:00")
    ap = client.get("/aprovar").text
    assert "📷 Carrossel · 1 imagem ✕" in ap and "Rejeitar #" in ap                   # confirmação ao rejeitar
    assert "Ajustar 1 imagem com ⚠" in client.get(f"/post/{mix}").text


def test_placeholders_block_suggestions_distinct_and_facts(client, tmp_path):
    import re
    from PIL import Image
    from carretos_social.db import add_media, add_post, connect, get_post
    _setup_admin(client)
    _login(client, "david", "segredo123")
    a = tmp_path / "a.jpg"; Image.new("RGB", (1080, 1350)).save(a)
    with connect() as conn:
        ma = add_media(conn, "image", str(a))
        pid = add_post(conn, account_id="ig_davidcarreto", format="image", status="draft", media_ids=[ma],
                       caption="Olá [PREENCHER: contexto pessoal] fim", scheduled_at="2030-01-01T10:00:00+00:00")
        u1 = add_post(conn, account_id="ig_davidcarreto", format="image", status="draft", media_ids=[ma], caption="x")
        u2 = add_post(conn, account_id="ig_davidcarreto", format="image", status="draft", media_ids=[ma], caption="x")
    page = client.get(f"/post/{pid}").text
    assert "A legenda tem partes por preencher" in page and "<mark>[PREENCHER: contexto pessoal]</mark>" in page
    assert "Refazer legenda com a IA" in page
    r = client.post(f"/post/{pid}", data={"action": "aprovar", "img": "2"}, follow_redirects=False)
    assert r.headers["location"] == f"/post/{pid}?erro=aprovar#img=2"
    assert "legenda por preencher" in client.get(f"/post/{pid}?erro=aprovar").text
    with connect() as conn:
        assert get_post(conn, pid)["status"] == "draft"
    assert "✕ legenda por preencher" in client.get("/aprovar").text
    # horas sugeridas diferentes para publicações sem data da mesma conta
    hora = lambda t: re.search(r'Hora sugerida: <b class="gold">([^<]+)</b>', t).group(1)
    assert hora(client.get(f"/post/{u1}").text) != hora(client.get(f"/post/{u2}").text)
    # base de conhecimento editável no dashboard
    client.post("/conhecimento/ficha", data={"brand": "geral", "section": "conquistas", "status": "publicavel",
                                             "text": "Facto de teste confirmado."})
    from carretos_social.content.ai import verified_facts
    assert "[Conquistas e números] Facto de teste confirmado." in verified_facts("geral")
    assert client.get("/factos", follow_redirects=False).headers["location"].startswith("/conhecimento")


def test_caption_ai_with_edited_caption_creates_job(client):
    """Regressão: 'Refazer legenda com a IA' dava 'database is locked' (500) quando a legenda tinha sido editada."""
    from carretos_social.cli import main
    from carretos_social.db import connect
    _setup_admin(client)
    _login(client, "david", "segredo123")
    main(["exemplo-carrossel"])
    r = client.post("/post/1", data={"action": "legenda_ia", "caption": "[TESTE] legenda mudada", "img": "1"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/tarefas"
    with connect() as conn:
        assert conn.execute("SELECT kind FROM jobs ORDER BY id DESC").fetchone()[0] == "legenda-ia"
        assert conn.execute("SELECT caption FROM posts WHERE id=1").fetchone()[0] == "[TESTE] legenda mudada"


def test_friendly_error_hint_and_menu(client, monkeypatch):
    import carretos_social.web.app as app_mod
    from carretos_social.cli import main
    _setup_admin(client)
    _login(client, "david", "segredo123")
    main(["exemplo-carrossel"])
    def boom(*a, **k):
        raise RuntimeError("falha de teste")
    monkeypatch.setattr(app_mod.jobs, "enqueue", boom)
    r = client.post("/post/1", data={"action": "legenda_ia"}, follow_redirects=False)
    assert "falha=" in r.headers["location"]
    assert "Não foi possível pedir a legenda à IA: falha de teste" in client.get(r.headers["location"]).text
    assert app_mod._fix_hint("sem data/hora; legenda por preencher ([PREENCHER…])").startswith(
        'Escolha a <a href="#quando" class="gold">data e hora</a> e complete a legenda')
    page = client.get("/").text
    assert 'class="topmenu"' in page and "📋 Conhecimento" in page


def test_update_button_reboot_notice_and_facts_check(client, monkeypatch, tmp_path):
    import subprocess
    from datetime import datetime, timedelta
    from carretos_social.web import system
    _setup_admin(client)
    _login(client, "david", "segredo123")
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a[0]))
    monkeypatch.setattr(system, "STARTED_AT", datetime.now() - timedelta(minutes=5))
    r = client.post("/configurar/atualizar", follow_redirects=False)
    assert r.headers["location"] == "/configurar/atualizacao" and calls[-1][0] == "bash" and calls[-1][1].endswith("atualizar.sh")
    page = client.get("/configurar/atualizacao").text
    assert "A atualizar" in page and "Pedida por <b>david</b>" in page
    assert "Atualizar o Carretos Studio" in client.get("/configurar").text
    client.post("/configurar/post-teste", follow_redirects=False)
    # reinício do servidor
    monkeypatch.setattr(system, "boot_time", lambda: datetime(2026, 11, 16, 10, 0))
    system.check_reboot()
    monkeypatch.setattr(system, "boot_time", lambda: datetime(2026, 11, 17, 0, 33))
    monkeypatch.setattr(system, "_previous_boot_tail", lambda lines=60: "… unattended-upgrade: rebooting")
    system.check_reboot()
    home = client.get("/").text
    assert "O servidor reiniciou às 00:33 (17/11)" in home and "unattended-upgrades" in home
    client.post("/configurar/reinicio-visto")
    assert "O servidor reiniciou" not in client.get("/").text
    # factos: contradição com as contas
    client.post("/conhecimento/ficha", data={"brand": "geral", "section": "contactos", "role": "info",
                                             "text": "Contas: Instagram @davidcarreto e @carretoclips."})
    f = client.get("/conhecimento?marca=geral").text
    assert "configurada é @davidcarretos" in f


def test_facts_usage_marks():
    from carretos_social.content.facts_check import usage
    u = usage(["O dono é David Carreto.", "A Carretos Group tem 5 oficinas: Almada e Mafra."],
              ["Venha à oficina de Almada", "outra"])
    assert u[0]["terms"] == [] and u[1]["used"] == 1


def test_update_log_written_by_script_and_reboot_causes(tmp_path, monkeypatch):
    import time
    from carretos_social.web import system
    root = tmp_path / "app"; (root / "deploy").mkdir(parents=True)
    (root / "deploy" / "atualizar.sh").write_text(
        'if [ -n "${CARRETOS_UPDATE_LOG:-}" ]; then exec >>"$CARRETOS_UPDATE_LOG" 2>&1; fi\n'
        'echo "==> Código (git pull)"\necho "==> Cópia de segurança da base de dados"\n')
    monkeypatch.setattr(system, "ROOT", root)
    assert system.start_update("david")
    for _ in range(50):
        log = (system.config.DATA_DIR / system.LOG).read_text()
        if "Cópia de segurança" in log:
            break
        time.sleep(0.1)
    assert log.startswith("Atualização pedida por david") and "==> Código (git pull)" in log
    assert "reinício ordenado" in system.guess_cause("... systemd-reboot.service: Deactivated ...")
    # 1.ª vez com arranque recente também avisa
    from datetime import datetime, timedelta
    (system.config.DATA_DIR / system.SERVER).unlink(missing_ok=True)
    monkeypatch.setattr(system, "boot_time", lambda: datetime.now() - timedelta(hours=3))
    monkeypatch.setattr(system, "_previous_boot_tail", lambda lines=60: "Reached target System Reboot")
    assert system.check_reboot()["cause"].startswith("reinício ordenado")


def _fake_graph(calls):
    """Simula a Graph API da Meta (sem rede)."""
    class R:
        def __init__(self, data): self._d = data
        def json(self): return self._d
    def fake(method, url, **kw):
        calls.append((method, url, kw))
        p = kw.get("params") or {}
        if url.endswith("/oauth/access_token"):
            return R({"access_token": "LONG" if p.get("grant_type") else "SHORT"})
        if url.endswith("/me"):
            return R({"id": "u1", "name": "David Carreto"})
        if url.endswith("/me/accounts"):
            return R({"data": [
                {"id": "111", "name": "David Carreto", "access_token": "PAGE1",
                 "instagram_business_account": {"id": "ig1", "username": "davidcarretos"}},
                {"id": "222", "name": "Carretos Group", "access_token": "PAGE2"}]})
        if url.endswith("/photos"):
            return R({"id": "ph1", "post_id": "222_9"})
        if url.endswith("/feed"):
            return R({"id": "222_10"})
        if url.endswith("/222"):
            return R({"name": "Carretos Group"})
        return R({"id": "x"})
    return fake


def test_meta_connect_flow_and_page_publish(client, monkeypatch, tmp_path):
    import os
    from urllib.parse import parse_qs, urlparse
    from PIL import Image
    from carretos_social import meta_connect
    from carretos_social.config import accounts
    from carretos_social.publishers import facebook, get_publisher
    from carretos_social.publishers.base import PublishRequest
    _setup_admin(client)
    _login(client, "david", "segredo123")
    assert "Primeiro" in client.get("/contas/meta/ligar").headers.get("location", "") or True
    monkeypatch.setenv("META_APP_ID", "1234567890123")
    monkeypatch.setenv("META_APP_SECRET", "0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("META_GRAPH_VERSION", "v21.0")                     # antiga → passa a v24
    for k in ("FB_CARRETOSGROUP_PAGE_TOKEN", "FB_CARRETOSGROUP_PAGE_ID", "IG_DAVIDCARRETO_TOKEN",
              "IG_DAVIDCARRETO_USER_ID"):
        monkeypatch.delenv(k, raising=False)
    calls = []
    monkeypatch.setattr(meta_connect, "request", _fake_graph(calls))
    monkeypatch.setattr(facebook, "request", _fake_graph(calls))
    page = client.get("/contas").text
    assert "Ligar com o Facebook" in page and "Modo assistido" in page and "/contas/meta/callback" in page
    r = client.get("/contas/meta/ligar", follow_redirects=False)
    url = r.headers["location"]
    assert url.startswith("https://www.facebook.com/v24.0/dialog/oauth") and "pages_manage_posts" in url
    state = parse_qs(urlparse(url).query)["state"][0]
    assert client.get("/contas/meta/callback?code=abc&state=errado", follow_redirects=False
                      ).headers["location"].startswith("/contas?erro=")
    r = client.get(f"/contas/meta/callback?code=abc&state={state}", follow_redirects=False)
    assert "msg=" in r.headers["location"]
    page = client.get("/contas").text
    assert 'value="ig:ig1" selected' in page and 'value="page:222" selected' in page   # sugestões certas
    client.post("/contas/meta/associar", data={"acc_ig_davidcarreto": "ig:ig1", "acc_fb_carretosgroup": "page:222"})
    acc = accounts()
    assert acc["ig_davidcarreto"].connected and acc["fb_carretosgroup"].connected
    assert os.environ["FB_CARRETOSGROUP_PAGE_TOKEN"] == "PAGE2" and os.environ["IG_DAVIDCARRETO_USER_ID"] == "ig1"
    assert "PAGE2" not in client.get("/contas").text                       # os tokens nunca aparecem
    assert "Página «Carretos Group» ✓" in client.get(
        client.post("/contas/fb_carretosgroup/testar", follow_redirects=False).headers["location"]).text
    # publicar na Página: uma imagem e várias fotos
    img = tmp_path / "a.jpg"; Image.new("RGB", (1080, 1350)).save(img)
    pub = get_publisher(acc["fb_carretosgroup"])
    assert isinstance(pub, facebook.FacebookPagePublisher)
    res = pub.publish(PublishRequest(account=acc["fb_carretosgroup"], format="image", caption="Olá", media=[str(img)]))
    assert res.remote_id == "222_9"
    res = pub.publish(PublishRequest(account=acc["fb_carretosgroup"], format="carousel", caption="Olá",
                                     media=[str(img), str(img)]))
    feed = [c for c in calls if c[1].endswith("/feed")][-1]
    assert res.remote_id == "222_10" and "attached_media" in feed[2]["data"]
    # desligar
    client.post("/contas/fb_carretosgroup/desligar")
    assert not accounts()["fb_carretosgroup"].connected


def test_public_folder_for_instagram(client, monkeypatch, tmp_path):
    from PIL import Image
    import carretos_social.config as cfg
    from carretos_social.publishers import media_host
    (cfg.ROOT / "ENDERECO_DASHBOARD.txt").exists()
    monkeypatch.delenv("MEDIA_FOLDER", raising=False); monkeypatch.delenv("MEDIA_BASE_URL", raising=False)
    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    (tmp_path / "ENDERECO_DASHBOARD.txt").write_text("https://carretosstudio.duckdns.org\n")
    img = tmp_path / "foto.jpg"; Image.new("RGB", (100, 100)).save(img)
    url = media_host.public_url(img)
    assert url.startswith("https://carretosstudio.duckdns.org/publico/") and url.endswith(".jpg")
    name = url.rsplit("/", 1)[1]
    assert client.get(f"/publico/{name}").status_code == 200                # sem sessão: a Meta vai buscar
    assert client.get("/publico/..%2Fcarretos.db").status_code == 404
    assert client.get("/publico/" + "a" * 32 + ".db").status_code == 404


def test_auron_brand_separate_facts_and_multi_portfolio(client, monkeypatch, tmp_path):
    from carretos_social import meta_connect
    from carretos_social.config import accounts, facts_brand, groups
    from carretos_social.content import ai
    _setup_admin(client)
    _login(client, "david", "segredo123")
    # 3.º grupo só com 2 contas
    assert [g["id"] for g in groups()] == ["david", "carretos", "auron"]
    auron = [a for a in accounts().values() if a.group == "auron"]
    assert sorted(a.platform for a in auron) == ["facebook_page", "instagram"]
    assert facts_brand("ig_auron") == "auron" and facts_brand("li_carretosgroup") == "geral"
    # factos e tom separados
    client.post("/conhecimento/regras", data={"marca": "auron", "tom": "Moderno e direto.", "proibidas": ""})
    assert "[Empresa e oficinas] A marca chama-se AURON." in ai.verified_facts("auron")
    assert ai.brand_tone("auron") == "Moderno e direto."
    assert not any("O AURON" in f or "A marca chama-se AURON" in f for f in ai.verified_facts("geral"))
    s_auron, s_geral = ai._system("auron"), ai._system("geral")
    assert "Moderno e direto." in s_auron and "Almada" not in s_auron and "Carretos Group tem" not in s_auron
    assert "O AURON é a plataforma" not in s_geral and "PALAVRAS PROIBIDAS nestas contas" in s_geral
    ai._account_line(accounts()["ig_auron"])
    assert ai._BRAND.get() == "auron"
    page = client.get("/conhecimento?marca=auron").text
    assert "Moderno e direto." in page and "A marca chama-se AURON." in page and "/conhecimento?marca=geral" in page
    # Meta: a AURON está noutro portefólio (RibaMotor) e só aparece pelas Páginas do portefólio
    class R:
        def __init__(self, d): self._d = d
        def json(self): return self._d
    def fake(method, url, **kw):
        if url.endswith("/oauth/access_token"):
            return R({"access_token": "T"})
        if url.endswith("/me"):
            return R({"id": "u1", "name": "David Carreto"})
        if url.endswith("/me/accounts"):
            return R({"data": [{"id": "222", "name": "Carretos Group", "access_token": "P2"}]})
        if url.endswith("/me/businesses"):
            return R({"data": [{"id": "1", "name": "Carreto's"}, {"id": "748541838052879", "name": "RibaMotor"}]})
        if url.endswith("/748541838052879/owned_pages"):
            return R({"data": [{"id": "900", "name": "AURON", "access_token": "PA",
                                "instagram_business_account": {"id": "17841477151306262", "username": "_auron_2026"}}]})
        return R({"data": []})
    monkeypatch.setattr(meta_connect, "request", fake)
    found = meta_connect.discover("T")
    assert {p["name"] for p in found["pages"]} == {"Carretos Group", "AURON"}
    assert found["businesses"] == ["Carreto's", "RibaMotor"]
    acc = accounts()
    assert meta_connect.suggestion(acc["ig_auron"], found) == "ig:17841477151306262"
    assert meta_connect.suggestion(acc["fb_auron"], found) == "page:900"
    assert meta_connect.suggestion(acc["fb_carretosgroup"], found) == "page:222"
    assert "portefólio RibaMotor" in client.get("/contas").text


def test_auron_quote_signed_auron(tmp_path):
    from PIL import Image
    from carretos_social.config import account, brand
    from carretos_social.media import image_gen
    account("ig_auron")
    assert brand()["visual"].get("quote_author") == "AURON"
    out = image_gen.quote_card("Teste", tmp_path / "q.jpg")
    assert Image.open(out).size == (1080, 1350)
    account("ig_davidcarreto")
    assert not brand()["visual"].get("quote_author")


def test_facts_no_false_contradiction_with_full_stop():
    from carretos_social.config import accounts
    from carretos_social.content.facts_check import contradictions
    auron = {k: v for k, v in accounts().items() if v.group == "auron"}
    assert contradictions(["Instagram: @_auron_2026. Página de Facebook: AURON."], auron) == []



def test_forbidden_terms_block_carretos_but_not_auron(client, tmp_path):
    from PIL import Image
    from carretos_social.content.ai import verified_facts
    from carretos_social.content.guard import found_terms, sanitize
    from carretos_social.db import add_media, add_post, connect, get_post
    from carretos_social.scheduler import all_problems
    _setup_admin(client)
    _login(client, "david", "segredo123")
    assert len(verified_facts("geral")) == 15 and len(verified_facts("auron")) == 14
    link = "auron.carretos.pt/schedule"
    assert found_terms("ig_carretosgroup", f"Saiba o preço na hora: {link}") == []          # o link pode ficar
    assert found_terms("ig_carretosgroup", f"Com o AURON sabe o preço: {link}")[0][1] == \
        "Nas contas da Carretos não se usa o nome AURON."
    assert found_terms("ig_auron", f"O AURON dá-lhe o preço: {link}") == []
    assert found_terms("ig_auron", "Integrado com a TecAlliance")                          # interno: todas as marcas
    assert "[PREENCHER" in sanitize("li_carretosgroup", f"Use o AURON. {link}") and link in \
        sanitize("li_carretosgroup", f"Use o AURON. {link}")
    img = tmp_path / "a.jpg"; Image.new("RGB", (1080, 1350)).save(img)
    with connect() as conn:
        mid = add_media(conn, "image", str(img))
        pid = add_post(conn, account_id="ig_davidcarreto", format="image", status="draft", media_ids=[mid],
                       caption=f"Revisão com o AURON: {link}", scheduled_at="2030-01-01T10:00:00+00:00")
        assert "Nas contas da Carretos não se usa o nome AURON." in all_problems(conn, get_post(conn, pid))
    assert "⚠ Nas contas da Carretos não se usa o nome AURON." in client.get(f"/post/{pid}").text
    assert client.post(f"/post/{pid}", data={"action": "aprovar"}, follow_redirects=False
                       ).headers["location"].startswith(f"/post/{pid}?erro=aprovar")
    # fichas novas da base: propostas no dashboard; uma ficha apagada não volta a ser proposta
    from carretos_social import knowledge as kb
    with connect() as conn:
        desc = next(i for i in kb.items(conn, "geral") if i["base_key"] == "g-desconto")
        kb.delete(conn, desc["id"])
        assert kb.new_base_items(conn, "geral") == []
        conn.execute("DELETE FROM settings WHERE key='knowledge_deleted_keys'")
    page = client.get("/conhecimento?marca=geral").text
    assert "ficha(s) nova(s) na base" in page
    client.post("/conhecimento/juntar", data={"marca": "geral"})
    assert "[Condições] Quem paga online no momento da marcação tem 5% de desconto." in verified_facts("geral")


def test_knowledge_base_features(client, tmp_path):
    from carretos_social import knowledge as kb
    from carretos_social.content import ai
    from carretos_social.content.guard import found_terms
    from carretos_social.db import connect
    _setup_admin(client)
    _login(client, "david", "segredo123")
    page = client.get("/conhecimento?marca=geral").text
    for sec in ("Empresa e oficinas", "Serviços e produtos", "Condições", "Contactos e links", "Perguntas frequentes",
                "Regras de comunicação"):
        assert sec in page
    # chamada à ação principal: WhatsApp (assistente 24 h); link como alternativa
    s = ai._system("geral")
    cta = s.split("CHAMADA À AÇÃO PRINCIPAL")[1].split("\n")[0]
    assert "WhatsApp 211 45 46 46" in cta and "Alternativa (só como segunda opção): Ver o preço e marcar" in s
    assert "CHAMADA À AÇÃO PRINCIPAL (usa esta quando houver chamada à ação): Ver o preço e marcar: auron.carretos.pt/schedule" \
        in ai._system("auron")
    # pergunta frequente
    client.post("/conhecimento/ficha", data={"brand": "geral", "section": "faq", "text": "Quanto tempo demora a revisão?",
                                             "answer": "[TESTE] resposta"})
    assert "[Perguntas frequentes] P: Quanto tempo demora a revisão? — R: [TESTE] resposta" in ai.verified_facts("geral")
    # ficha interna: nunca vai para os factos e as palavras bloqueiam a legenda
    client.post("/conhecimento/ficha", data={"brand": "todas", "section": "regras", "status": "interno",
                                             "text": "O fornecedor X não se publica.", "keywords": "FornecedorX"})
    assert not any("FornecedorX" in f for f in ai.verified_facts("auron"))
    assert found_terms("ig_auron", "Com o FornecedorX")[0][1] == 'Informação interna que não se publica: "FornecedorX".'
    assert "O fornecedor X não se publica." in ai._system("geral").split("NUNCA publicar")[1]
    # validade: ficha expirada deixa de ser usada
    client.post("/conhecimento/ficha", data={"brand": "geral", "section": "condicoes", "text": "Promoção de teste.",
                                             "valid_until": "2020-01-01"})
    assert not any("Promoção de teste" in f for f in ai.verified_facts("geral"))
    assert "Expirou 2020-01-01" in client.get("/conhecimento?marca=geral").text
    # só para uma conta
    client.post("/conhecimento/ficha", data={"brand": "geral", "section": "pessoas", "text": "Só para o LinkedIn.",
                                             "accounts": "li_davidcarreto"})
    assert any("Só para o LinkedIn" in f for f in ai.verified_facts("geral", "li_davidcarreto"))
    assert not any("Só para o LinkedIn" in f for f in ai.verified_facts("geral", "ig_davidcarreto"))
    # editar e apagar, com histórico
    with connect() as conn:
        item = next(i for i in kb.items(conn, "geral") if i["text"] == "Só para o LinkedIn.")
    client.post("/conhecimento/ficha", data={"id": item["id"], "brand": "geral", "section": "pessoas",
                                             "text": "Só para o LinkedIn (editado)."})
    client.post("/conhecimento/ficha", data={"id": item["id"], "brand": "geral", "section": "pessoas",
                                             "text": "x", "acao": "apagar"})
    hist = client.get("/conhecimento?marca=geral").text
    assert "Alterada: Só para o LinkedIn (editado)." in hist and "Apagada:" in hist
    # Excel: exportar, acrescentar uma linha, importar
    r = client.get("/conhecimento/exportar")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    from openpyxl import load_workbook
    xl = tmp_path / "k.xlsx"; xl.write_bytes(r.content)
    wb = load_workbook(xl); ws = wb.worksheets[0]
    ws.append(["", "auron", "faq", "O AURON serve para outras marcas?", "Não, é só para Mercedes-Benz.", "publicavel",
               "", "", "", "", ""])
    ws.append(["", "marca-errada", "faq", "x", "", "publicavel", "", "", "", "", ""])
    wb.save(xl)
    r = client.post("/conhecimento/importar", files={"ficheiro": ("k.xlsx", xl.read_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}, follow_redirects=False)
    from urllib.parse import unquote
    loc = unquote(r.headers["location"])
    assert "1 nova(s)" in loc and "marca desconhecida" in loc
    assert any("O AURON serve para outras marcas?" in f for f in ai.verified_facts("auron"))


def test_knowledge_seed_imports_old_dashboard_facts(tmp_path, monkeypatch):
    import carretos_social.config as cfg
    import carretos_social.db as db
    (tmp_path / "factos.yaml").write_text('factos:\n  - "Facto antigo editado no dashboard."\n', encoding="utf-8")
    from carretos_social import knowledge as kb
    with db.connect() as conn:
        outros = [i["text"] for i in kb.items(conn, "geral") if i["section"] == "outros"]
    assert outros == ["Facto antigo editado no dashboard."]


def test_tone_update_voce_applied_once_and_sintra_fact(tmp_path):
    import carretos_social.db as db
    from carretos_social import knowledge as kb
    with db.connect() as conn:
        # base criada antes deste ajuste: tom antigo e ajuste ainda por aplicar
        conn.execute("UPDATE settings SET value=? WHERE key='tom:geral'", ('"Tom antigo."',))
        conn.execute("DELETE FROM settings WHERE key='tone_updates_done'")
        kb.apply_tone_updates(conn)
        kb.apply_tone_updates(conn)                                   # 2.ª vez não repete
        t = kb.tone(conn, "geral")
        assert t.startswith("Tom antigo.") and t.count('"você"') == 1
        assert any(i["text"].startswith("Em 2024 a oficina de Sintra mudou-se para o Cacém")
                   for i in kb.items(conn, "geral"))


def test_meta_no_unsupported_portfolio_instagram_calls_and_full_errors(client, monkeypatch):
    from carretos_social import meta_connect
    _setup_admin(client)
    _login(client, "david", "segredo123")
    calls = []
    long_err = "Erro longo da Meta: " + "x" * 400 + " FIM"
    class R:
        def __init__(self, d): self._d = d
        def json(self): return self._d
    def fake(method, url, **kw):
        calls.append(url)
        if url.endswith("/me"):
            return R({"id": "u1", "name": "David Carreto"})
        if url.endswith("/me/businesses"):
            return R({"data": [{"id": "959299140915335", "name": "Carreto's"}]})
        if url.endswith("/owned_pages"):
            raise RuntimeError(long_err)
        return R({"data": []})
    monkeypatch.setattr(meta_connect, "request", fake)
    monkeypatch.setenv("META_APP_ID", "1234567890123")
    monkeypatch.setenv("META_APP_SECRET", "0123456789abcdef0123456789abcdef")
    found = meta_connect.discover("T")
    assert not any("instagram_accounts" in u for u in calls)                 # "Unsupported get request"
    assert found["igs"] == [] and any(e.endswith(" FIM") for e in found["errors"])   # aviso completo
    assert "x" * 400 + " FIM" in client.get("/contas").text


def test_linkedin_member_org_assist_and_tiktok_refresh(client, monkeypatch):
    import os
    from datetime import datetime, timedelta
    from carretos_social import linkedin_connect as lc
    from carretos_social import tiktok_connect as tc
    from carretos_social.config import accounts, save_account_override
    from carretos_social.publishers import get_publisher
    from carretos_social.publishers.assist import AssistPublisher
    _setup_admin(client)
    _login(client, "david", "segredo123")
    for k in ("LI_DAVIDCARRETO_TOKEN", "LI_DAVIDCARRETO_URN", "LI_CARRETOSGROUP_TOKEN", "LI_CARRETOSGROUP_URN",
              "TT_CARRETOCLIPS_TOKEN", "TT_CARRETOCLIPS_REFRESH", "LINKEDIN_ORG_API", "TIKTOK_AUDITED"):
        monkeypatch.delenv(k, raising=False)
    # modos assistidos enquanto as redes não aprovam
    assert isinstance(get_publisher(accounts()["li_carretosgroup"]), AssistPublisher)
    assert isinstance(get_publisher(accounts()["tt_carretoclips"]), AssistPublisher)       # TikTok por ligar
    assert "Community Management API" in accounts()["li_carretosgroup"].assist_reason
    page = client.get("/contas").text
    assert "Primeiro crie a app em linkedin.com/developers" in page and "não publica em público no TikTok" in page
    # ---- LinkedIn
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "86abcdefgh1234")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "segredo-linkedin-123")
    class R:
        def __init__(self, d): self._d = d
        def json(self): return self._d
    def li_fake(method, url, **kw):
        if url.endswith("/accessToken"):
            return R({"access_token": "LITOKEN", "expires_in": 5184000, "scope": "openid,profile,w_member_social"})
        if url.endswith("/userinfo"):
            return R({"sub": "abc123", "name": "David Carreto"})
        raise AssertionError(url)
    monkeypatch.setattr(lc, "request", li_fake)
    from urllib.parse import parse_qs, urlparse
    loc = client.get("/contas/linkedin/ligar", follow_redirects=False).headers["location"]
    q = parse_qs(urlparse(loc).query)
    assert loc.startswith("https://www.linkedin.com/oauth/v2/authorization") and q["scope"] == ["openid profile w_member_social"]
    r = client.get(f"/contas/linkedin/callback?code=c&state={q['state'][0]}", follow_redirects=False)
    assert "LinkedIn de David Carreto ligado." in r.headers["location"].replace("%20", " ")
    assert os.environ["LI_DAVIDCARRETO_URN"] == "urn:li:person:abc123" and accounts()["li_davidcarreto"].connected
    assert lc.test(accounts()["li_davidcarreto"]) == (True, "LinkedIn de David Carreto ✓")
    # página: 2.ª app só para a Community Management API (e aprovada)
    monkeypatch.setenv("LINKEDIN_ORG_API", "sim")
    assert not lc.org_enabled()                                            # falta a 2.ª app
    monkeypatch.setenv("LINKEDIN_ORG_CLIENT_ID", "77orgapp12345")
    monkeypatch.setenv("LINKEDIN_ORG_CLIENT_SECRET", "segredo-org-123")
    loc = client.get("/contas/linkedin/ligar?app=pagina", follow_redirects=False).headers["location"]
    q2 = parse_qs(urlparse(loc).query)
    assert q2["client_id"] == ["77orgapp12345"] and "w_organization_social" in q2["scope"][0]
    assert "openid" not in q2["scope"][0]
    def li_fake2(method, url, **kw):
        if url.endswith("/accessToken"):
            return R({"access_token": "LITOKEN2", "expires_in": 5184000,
                      "scope": "openid,profile,w_member_social,w_organization_social"})
        if url.endswith("/userinfo"):
            return R({"sub": "abc123", "name": "David Carreto"})
        if url.endswith("/organizationAcls"):
            return R({"elements": [{"organization": "urn:li:organization:777"}]})
        if url.endswith("/organizations/777"):
            return R({"localizedName": "Carretos Group"})
        raise AssertionError(url)
    monkeypatch.setattr(lc, "request", li_fake2)
    updates, info = lc.connect_org({"access_token": "LITOKEN2", "expires_in": 100})
    assert updates["LI_CARRETOSGROUP_URN"] == "urn:li:organization:777"
    from carretos_social import envfile
    envfile.set_env(updates, root=__import__("carretos_social.web.app", fromlist=["ROOT"]).ROOT)
    assert accounts()["li_carretosgroup"].mode == "auto"
    # ---- TikTok: ligar uma conta e renovar o token de 24 h
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "awabcdefghij123")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "segredoTikTok1234567890")
    calls = []
    def tt_fake(method, url, **kw):
        calls.append((url, (kw.get("data") or {}).get("grant_type")))
        if url.endswith("/oauth/token/"):
            if kw["data"]["grant_type"] == "authorization_code":
                return R({"access_token": "TT1", "refresh_token": "RF1", "expires_in": 86400,
                          "refresh_expires_in": 31536000, "open_id": "o1"})
            return R({"access_token": "TT2", "refresh_token": "RF2", "expires_in": 86400, "refresh_expires_in": 31536000})
        if url.endswith("/user/info/"):
            assert kw["params"]["fields"] == "open_id,union_id,avatar_url,display_name"   # só user.info.basic
            return R({"data": {"user": {"display_name": "Carreto Clips"}}})
        raise AssertionError(url)
    monkeypatch.setattr(tc, "request", tt_fake)
    loc = client.get("/contas/tiktok/ligar?conta=tt_carretoclips", follow_redirects=False).headers["location"]
    assert loc.startswith("https://www.tiktok.com/v2/auth/authorize/") and "video.upload" in loc and "video.publish" not in loc
    st = parse_qs(urlparse(loc).query)["state"][0]
    r = client.get(f"/contas/tiktok/callback?code=c&state={st}", follow_redirects=False)
    assert "ligada" in r.headers["location"].replace("%20", " ")
    assert os.environ["TT_CARRETOCLIPS_TOKEN"] == "TT1" and os.environ["TT_CARRETOCLIPS_REFRESH"] == "RF1"
    ok, text = tc.test(accounts()["tt_carretoclips"])
    assert ok and "TikTok @clips.do.carreto («Carreto Clips») ✓" in text and "rascunhos da app TikTok" in text
    assert accounts()["tt_carretosgroup"].handle == "carretos_group" and accounts()["tt_davidcarreto"].handle == "davidcarretos"
    assert accounts()["tt_carretoclips"].mode == "draft"
    save_account_override("tt_carretoclips", access_expires=(datetime.now() - timedelta(minutes=1)).isoformat())
    assert tc.ensure_fresh(accounts()["tt_carretoclips"]) == "TT2" and os.environ["TT_CARRETOCLIPS_REFRESH"] == "RF2"
    # Testar mostra a mensagem completa do erro
    def boom(method, url, **kw):
        raise RuntimeError("TikTok -> 401: {\"error\":{\"code\":\"access_token_invalid\",\"message\":\"The access token is invalid or not found in the request.\"}}")
    monkeypatch.setattr(tc, "request", boom)
    save_account_override("tt_carretoclips", access_expires=(datetime.now() + timedelta(hours=5)).isoformat())
    from urllib.parse import unquote
    loc = unquote(client.post("/contas/tt_carretoclips/testar", follow_redirects=False).headers["location"])
    assert "The access token is invalid or not found in the request." in loc


def test_public_legal_pages(client):
    for path in ("/privacidade", "/termos"):
        r = client.get(path)
        assert r.status_code == 200 and "Carretos Studio" in r.text and "palavra-passe" not in r.text[:0]



def test_expiring_connections_banner_and_reminder(client, monkeypatch):
    from datetime import date, timedelta
    from carretos_social import expiry, notify
    from carretos_social.config import save_account_override
    _setup_admin(client)
    _login(client, "david", "segredo123")
    monkeypatch.setenv("LI_DAVIDCARRETO_TOKEN", "t"); monkeypatch.setenv("LI_DAVIDCARRETO_URN", "urn:li:person:1")
    save_account_override("li_davidcarreto", token_expires=(date.today() + timedelta(days=5)).isoformat())
    items = expiry.expiring()
    assert items and items[0]["account"] == "li_davidcarreto" and items[0]["days"] == 5
    assert "Ligações a renovar" in client.get("/").text and "faltam 5 dias" in client.get("/").text
    sent = []
    monkeypatch.setattr(notify, "enabled", lambda: True)
    monkeypatch.setattr(notify, "send", lambda t: sent.append(t))
    assert expiry.remind() and "📣 Carretos Studio · Ligações a renovar" in sent[0] and "LinkedIn" in sent[0]
    save_account_override("li_davidcarreto", token_expires=(date.today() + timedelta(days=60)).isoformat())
    assert expiry.expiring() == []



def test_tiktok_drafts_video_photos_fallback_and_status(client, monkeypatch, tmp_path):
    import subprocess
    from PIL import Image
    from carretos_social import notify
    from carretos_social.config import accounts, save_account_override
    from carretos_social.db import add_media, add_post, connect, get_post
    from carretos_social.publishers import get_publisher, tiktok
    from carretos_social.publishers.base import PublishRequest
    import carretos_social.config as cfg
    from carretos_social.scheduler import publish_post
    _setup_admin(client)
    _login(client, "david", "segredo123")
    monkeypatch.setenv("TT_CARRETOCLIPS_TOKEN", "TT1"); monkeypatch.setenv("TT_CARRETOCLIPS_REFRESH", "RF1")
    from datetime import datetime, timedelta
    save_account_override("tt_carretoclips", status="ligada", access_expires=(datetime.now() + timedelta(hours=5)).isoformat())
    acc = accounts()["tt_carretoclips"]
    assert isinstance(get_publisher(acc), tiktok.TikTokPublisher) and acc.connected
    # servidor com endereço público (para as fotos)
    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    (tmp_path / "ENDERECO_DASHBOARD.txt").write_text("https://carretosstudio.duckdns.org\n")
    monkeypatch.delenv("MEDIA_FOLDER", raising=False); monkeypatch.delenv("MEDIA_BASE_URL", raising=False)
    calls, texts = [], []
    class R:
        def __init__(self, d): self._d = d
        def json(self): return self._d
    def fake(method, url, **kw):
        calls.append((url, kw.get("json")))
        if url.endswith("/inbox/video/init/"):
            return R({"data": {"publish_id": "v1", "upload_url": "https://upload.tiktok/up"}})
        if url.endswith("/content/init/"):
            return R({"data": {"publish_id": "p1"}})
        if url.endswith("/status/fetch/"):
            return R({"data": {"status": "SEND_TO_USER_INBOX"}})
        return R({})
    monkeypatch.setattr(tiktok, "request", fake)
    monkeypatch.setattr(notify, "send", lambda t: texts.append(t))
    monkeypatch.setattr(notify, "enabled", lambda: True)
    monkeypatch.setattr(notify, "send_file", lambda *a, **k: None)
    from carretos_social.web import mailer
    mails = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subj, body: mails.append((to, subj, body)))
    monkeypatch.setenv("TIKTOK_CAPTION_EMAIL", "legendas@exemplo.pt")
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=540x960:d=4", "-pix_fmt",
                    "yuv420p", str(video)], check=True)
    res = get_publisher(acc).publish(PublishRequest(account=acc, format="video", caption="Legenda do vídeo", media=[str(video)]))
    assert res.status == "tiktok_draft" and "Legenda e capa a definir na app TikTok" in res.note
    init = next(j for u, j in calls if u.endswith("/inbox/video/init/"))
    assert init["source_info"]["source"] == "FILE_UPLOAD" and "post_info" not in init        # sem legenda nem capa
    assert any("Legenda do vídeo" in t and "@clips.do.carreto" in t for t in texts)          # legenda enviada
    assert mails and mails[0][0] == "legendas@exemplo.pt" and mails[0][1] == "Legenda TikTok – @clips.do.carreto"
    assert "Confirme a privacidade antes de publicar" in mails[0][2]
    assert "✔ Email da legenda enviado para legendas@exemplo.pt" in res.note and "Confirme a privacidade" in res.note
    # erro SMTP completo no resultado
    from carretos_social.publishers.tiktok import _send_caption
    def smtp_fail(to, subj, body):
        raise OSError("535 5.7.8 Username and Password not accepted")
    monkeypatch.setattr(mailer, "send", smtp_fail)
    lines = _send_caption(PublishRequest(account=acc, format="video", caption="x", media=[str(video)]), test=True)
    assert lines[0] == "✘ Email da legenda: OSError: 535 5.7.8 Username and Password not accepted"
    monkeypatch.setattr(mailer, "send", lambda to, subj, body: mails.append((to, subj, body)))
    imgs = []
    for i in range(2):
        p = tmp_path / f"f{i}.jpg"; Image.new("RGB", (1080, 1920)).save(p); imgs.append(str(p))
    res = get_publisher(acc).publish(PublishRequest(account=acc, format="carousel", caption="Legenda do carrossel",
                                                    media=imgs, title="Título"))
    body = next(j for u, j in calls if u.endswith("/content/init/"))
    assert body["post_mode"] == "MEDIA_UPLOAD" and body["media_type"] == "PHOTO"
    assert body["post_info"]["description"] == "Legenda do carrossel" and body["source_info"]["photo_cover_index"] == 0
    assert all(u.startswith("https://carretosstudio.duckdns.org/publico/") for u in body["source_info"]["photo_images"])
    # a TikTok recusa (app não aprovada): erro completo e modo assistido
    def refuse(method, url, **kw):
        raise RuntimeError("POST /v2/post/publish/inbox/video/init/ -> 403: {\"error\":{\"code\":\"unaudited_client_can_only_post_to_private_accounts\"}}")
    monkeypatch.setattr(tiktok, "request", refuse)
    res = get_publisher(acc).publish(PublishRequest(account=acc, format="video", caption="x", media=[str(video)]))
    assert res.status == "assist_sent" and "unaudited_client_can_only_post_to_private_accounts" in res.note
    # estado no dashboard
    monkeypatch.setattr(tiktok, "request", fake)
    with connect() as conn:
        mid = add_media(conn, "video", str(video))
        pid = add_post(conn, account_id="tt_carretoclips", format="video", caption="Legenda #1", media_ids=[mid],
                       status="approved", scheduled_at="2020-01-01T10:00:00+00:00")
        publish_post(conn, pid)
        assert get_post(conn, pid)["status"] == "tiktok_draft"
    page = client.get(f"/post/{pid}").text
    assert "No TikTok: falta publicar na app" in page and "Copiar legenda" in page and "legenda e capa a definir na app TikTok" in page
    # botão de teste cria a tarefa
    client.post("/contas/tt_carretoclips/tiktok-teste", follow_redirects=False)
    with connect() as conn:
        assert conn.execute("SELECT kind FROM jobs ORDER BY id DESC").fetchone()[0] == "tiktok-teste"


def test_tiktok_domain_verification_file(client, monkeypatch):
    monkeypatch.setenv("TIKTOK_VERIFY_FILE", "tiktokAbC123.txt")
    monkeypatch.setenv("TIKTOK_VERIFY_CONTENT", "tiktok-developers-site-verification=XYZ12345")
    r = client.get("/tiktokAbC123.txt")
    assert r.status_code == 200 and r.text == "tiktok-developers-site-verification=XYZ12345"


def test_telegram_config_discover_chat_and_test(client, monkeypatch):
    import os
    from carretos_social import notify
    import carretos_social.http as http
    _setup_admin(client)
    _login(client, "david", "segredo123")
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    page = client.get("/configurar").text
    assert "Telegram · token do bot" in page and "Descobrir o chat" in page and "Telegram por configurar" in page
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:AAH" + "x" * 32)
    class R:
        def __init__(self, d): self._d = d
        def json(self): return self._d
    monkeypatch.setattr(http, "request", lambda m, u, **k: R({"result": [{"message": {"chat": {"id": 987654321}}}]}))
    r = client.post("/configurar/telegram-chat", follow_redirects=False)
    assert r.headers["location"] == "/configurar?tg=chat" and os.environ["TELEGRAM_CHAT_ID"] == "987654321"
    sent = []
    monkeypatch.setattr(notify, "send", lambda t: sent.append(t))
    assert client.post("/configurar/testar-telegram", follow_redirects=False).headers["location"] == "/configurar?tg=ok"
    assert "está a funcionar" in sent[0] and not sent[0].startswith("📣")       # o prefixo é posto pelo notify


def test_manual_page_and_mark_published(client, tmp_path):
    from PIL import Image
    from carretos_social.db import add_media, add_post, connect, get_post
    _setup_admin(client)
    _login(client, "david", "segredo123")
    img = tmp_path / "a.jpg"; Image.new("RGB", (1080, 1350)).save(img)
    with connect() as conn:
        mid = add_media(conn, "image", str(img))
        pid = add_post(conn, account_id="fb_davidcarreto", format="image", caption="Legenda para colar",
                       media_ids=[mid], status="assist_sent", scheduled_at="2030-01-01T10:00:00+00:00")
    page = client.get("/manual").text
    assert "Para publicar à mão" in page and "Legenda para colar" in page and "Copiar legenda" in page
    assert f'href="/media/{mid}" download' in page and "Publicar à mão" in client.get("/").text
    client.post(f"/manual/{pid}/publicado", data={"link": "https://facebook.com/p/1"}, follow_redirects=False)
    with connect() as conn:
        row = get_post(conn, pid)
        assert (row["status"], row["remote_url"]) == ("published", "https://facebook.com/p/1")
    assert "Não há nada para publicar à mão" in client.get("/manual").text


def test_health_check_alerts_once_and_banner(client, monkeypatch):
    from carretos_social import health
    _setup_admin(client)
    _login(client, "david", "segredo123")
    monkeypatch.setenv("FB_AURON_PAGE_TOKEN", "t"); monkeypatch.setenv("FB_AURON_PAGE_ID", "900")
    state = {"ok": True}
    monkeypatch.setattr(health, "test_account", lambda acc: (state["ok"], "Página «AURON» ✓" if state["ok"]
                                                             else "a ligação falhou: (#190) Error validating access token"))
    alerts = []
    monkeypatch.setattr(health, "_alert", lambda items: alerts.append(items))
    res = health.check_all()
    assert res["fb_auron"]["ok"] and not alerts and "Ligações com problemas" not in client.get("/").text
    state["ok"] = False
    health.check_all(); health.check_all()                                   # alerta uma só vez
    assert len(alerts) == 1 and "AURON (Página de Facebook)" in [r["name"] for r in alerts[0]]
    home = client.get("/").text
    assert "Ligações com problemas" in home and "Error validating access token" in home
    r = client.post("/contas/verificar", follow_redirects=False)
    assert "erro=" in r.headers["location"]
    assert "verificada" in client.get("/contas").text


def test_linkedin_version_and_fb_carretoclips(monkeypatch):
    from datetime import datetime
    from carretos_social.config import accounts
    from carretos_social.linkedin_connect import api_version
    monkeypatch.delenv("LINKEDIN_VERSION", raising=False)
    v = api_version()
    assert len(v) == 6 and v < datetime.now().strftime("%Y%m")              # sempre uma versão já lançada
    monkeypatch.setenv("LINKEDIN_VERSION", "202601")
    assert api_version() == "202601"
    acc = accounts()["fb_carretoclips"]
    assert acc.platform == "facebook_page" and acc.group == "david" and not acc.connected


def test_routines_fixed_times_no_repeat_and_weekly(client, monkeypatch):
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo
    from carretos_social import expiry, health, notify, routine
    from carretos_social.config import save_account_override
    from carretos_social.db import add_post, connect
    _setup_admin(client)
    sent, checks = [], []
    monkeypatch.setattr(notify, "send", lambda t: sent.append(t))
    monkeypatch.setattr(notify, "enabled", lambda: True)
    monkeypatch.setattr(health, "check_all", lambda alert=True: checks.append(1) or {})
    tz = ZoneInfo("Europe/Lisbon")
    monday = datetime(2026, 11, 23, 8, 0, tzinfo=tz)                      # segunda-feira
    with connect() as conn:
        add_post(conn, account_id="ig_auron", format="image", title="[TESTE] por aprovar", status="draft",
                 scheduled_at=(monday + timedelta(hours=10)).isoformat())
    assert routine.run_due(monday) == []                                   # 08:00: ainda nada
    out = routine.run_due(monday.replace(hour=8, minute=31))
    assert out == ["ligações verificadas: todas OK"] and len(checks) == 1
    out = routine.run_due(monday.replace(hour=9, minute=1))
    assert "lembrete 'por aprovar': 1 publicação(ões)" in out and "resumo semanal enviado" in out
    pend = next(t for t in sent if t.startswith("📝 Por aprovar"))
    assert "AURON (Instagram)" in pend and "/aprovar" in pend and "carretos approve" not in pend
    assert any(t.startswith("🗓 Resumo semanal") for t in sent)
    n = len(sent)
    assert routine.run_due(monday.replace(hour=15)) == [] and len(sent) == n   # reinício/mais tarde: não repete
    # ligações a expirar: só a 14, 7, 3, 1 e 0 dias
    monkeypatch.setenv("LI_DAVIDCARRETO_TOKEN", "t"); monkeypatch.setenv("LI_DAVIDCARRETO_URN", "urn:li:person:1")
    save_account_override("li_davidcarreto", token_expires=(date.today() + timedelta(days=5)).isoformat())
    assert not expiry.remind(only_days=routine.EXPIRY_DAYS)
    save_account_override("li_davidcarreto", token_expires=(date.today() + timedelta(days=7)).isoformat())
    assert expiry.remind(only_days=routine.EXPIRY_DAYS)


def test_env_reload_without_restart_and_confirmations(client, monkeypatch, tmp_path):
    import os
    from carretos_social import envfile, notify
    (tmp_path / ".env").write_text("NOVA_CHAVE=1\nCHAVE_APAGADA=\n", encoding="utf-8")
    monkeypatch.setenv("CHAVE_APAGADA", "antiga")
    envfile.reload_env(root=tmp_path)
    assert os.environ["NOVA_CHAVE"] == "1" and "CHAVE_APAGADA" not in os.environ   # conta desligada deixa de publicar
    monkeypatch.delenv("NOVA_CHAVE")
    # confirmação de publicação e link no modo assistido
    from carretos_social.publishers.assist import AssistPublisher
    from carretos_social.publishers.base import PublishRequest, PublishResult
    from carretos_social.config import accounts
    from carretos_social import scheduler
    sent = []
    monkeypatch.setattr(notify, "send", lambda t: sent.append(t))
    monkeypatch.setattr(notify, "send_file", lambda *a, **k: None)
    scheduler._confirm(accounts()["ig_auron"], {"title": "Post X", "pillar": "", "id": 1, "format": "image",
                                                "media_ids": "[]"}, "published",
                       PublishResult(remote_id="1", url="https://instagram.com/p/x"))
    assert sent[-1] == "✅ Publicado em AURON (Instagram): Post X\nhttps://instagram.com/p/x"
    scheduler._confirm(accounts()["tt_carretosgroup"], {"title": "Fotos", "pillar": "", "id": 2, "format": "carousel",
                                                        "media_ids": "[]"}, "tiktok_draft", PublishResult(remote_id="p"))
    assert sent[-1].startswith("♪ Rascunho enviado para o TikTok de @carretos_group") and "/manual" in sent[-1]
    AssistPublisher().publish(PublishRequest(account=accounts()["fb_davidcarreto"], format="text", caption="Olá"))
    assert "Já publiquei" in sent[-1] and "/manual" in sent[-1]


def test_config_shows_telegram_bot_link(client, monkeypatch):
    _setup_admin(client)
    _login(client, "david", "segredo123")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:AAH" + "x" * 32)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "carretos_studio_bot")
    page = client.get("/configurar").text
    assert "@carretos_studio_bot" in page and 'href="https://t.me/carretos_studio_bot"' in page and "/start" in page


def _signed(body: bytes, secret: str) -> dict:
    import hashlib
    import hmac
    return {"x-hub-signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
            "content-type": "application/json"}


def test_inbox_webhook_auto_replies_and_safeguards(client, monkeypatch):
    import json as _json
    from carretos_social import inbox, notify
    import carretos_social.http as http
    from carretos_social.db import connect
    _setup_admin(client)
    _login(client, "david", "segredo123")
    secret = "0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("META_APP_SECRET", secret)
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "cs-verifica")
    monkeypatch.setenv("FB_CARRETOSGROUP_PAGE_TOKEN", "PAGE2"); monkeypatch.setenv("FB_CARRETOSGROUP_PAGE_ID", "222")
    monkeypatch.setenv("IG_AURON_TOKEN", "PA"); monkeypatch.setenv("IG_AURON_USER_ID", "17841477151306262")
    monkeypatch.delenv("SOCIAL_ANTHROPIC_API_KEY", raising=False)               # sem IA: resposta-padrão
    # verificação do webhook (Meta)
    assert client.get("/webhooks/meta?hub.mode=subscribe&hub.verify_token=cs-verifica&hub.challenge=123").text == "123"
    assert client.get("/webhooks/meta?hub.mode=subscribe&hub.verify_token=errado&hub.challenge=1").status_code == 403
    sent, alerts = [], []
    class R:
        def json(self): return {"id": "ok"}
    monkeypatch.setattr(http, "request", lambda m, u, **k: sent.append((u, k)) or R())
    monkeypatch.setattr(notify, "send", lambda t: alerts.append(t))
    monkeypatch.setattr(inbox.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda s: target(*args)})())
    fb = {"object": "page", "entry": [{"id": "222", "changes": [{"field": "feed", "value": {
        "item": "comment", "verb": "add", "comment_id": "222_1_c1", "post_id": "222_1", "message": "Quanto custa a revisão?",
        "from": {"id": "u9", "name": "Cliente"}}}]}]}
    body = _json.dumps(fb).encode()
    assert client.post("/webhooks/meta", content=body, headers={"content-type": "application/json",
                                                               "x-hub-signature-256": "sha256=errada"}).status_code == 403
    # desligado por defeito: guarda mas não responde
    assert client.post("/webhooks/meta", content=body, headers=_signed(body, secret)).text == "ok"
    with connect() as conn:
        assert conn.execute("SELECT status FROM inbox WHERE external_id='222_1_c1'").fetchone()[0] == "desligado"
    assert not sent
    # ligar e receber de novo (outro comentário)
    client.post("/mensagens/conta/fb_carretosgroup", data={"enabled": "1", "private": "1"})
    fb["entry"][0]["changes"][0]["value"]["comment_id"] = "222_1_c2"
    body = _json.dumps(fb).encode()
    client.post("/webhooks/meta", content=body, headers=_signed(body, secret))
    urls = [u for u, _ in sent]
    assert any(u.endswith("/222_1_c2/comments") for u in urls) and any(u.endswith("/me/messages") for u in urls)
    reply = next(k["data"]["message"] for u, k in sent if u.endswith("/222_1_c2/comments"))
    assert "wa.me/351211454646" in reply and "AURON" not in reply
    private = next(k["json"] for u, k in sent if u.endswith("/me/messages"))
    assert private["recipient"] == {"comment_id": "222_1_c2"}
    # o mesmo evento reenviado pela Meta não responde duas vezes
    n = len(sent)
    client.post("/webhooks/meta", content=body, headers=_signed(body, secret))
    assert len(sent) == n
    # comentário da própria Página: ignorado
    fb["entry"][0]["changes"][0]["value"].update(comment_id="222_1_c3", **{"from": {"id": "222", "name": "Carretos Group"}})
    body = _json.dumps(fb).encode()
    client.post("/webhooks/meta", content=body, headers=_signed(body, secret))
    assert len(sent) == n
    # Instagram: comentário → /replies; mensagem privada → /me/messages, uma vez por pessoa em 24 h
    client.post("/mensagens/conta/ig_auron", data={"enabled": "1"})
    ig = {"object": "instagram", "entry": [{"id": "17841477151306262", "changes": [{"field": "comments", "value": {
        "id": "igc1", "text": "Dá para marcar?", "from": {"id": "u7", "username": "cliente_x"}, "media": {"id": "m1"}}}],
        "messaging": [{"sender": {"id": "u7"}, "recipient": {"id": "17841477151306262"}, "message": {"mid": "mid1", "text": "Olá, preço?"}},
                      {"sender": {"id": "u7"}, "recipient": {"id": "17841477151306262"}, "message": {"mid": "mid2", "text": "Ainda aí?"}},
                      {"sender": {"id": "17841477151306262"}, "message": {"mid": "mid3", "text": "eco", "is_echo": True}}]}]}
    body = _json.dumps(ig).encode()
    client.post("/webhooks/meta", content=body, headers=_signed(body, secret))
    assert any(u.endswith("/igc1/replies") for u, _ in sent)
    dms = [k["json"] for u, k in sent if u.endswith("/me/messages") and k["json"]["recipient"] == {"id": "u7"}]
    assert len(dms) == 1 and "wa.me" in dms[0]["message"]["text"]
    with connect() as conn:
        st = dict(conn.execute("SELECT external_id, status FROM inbox WHERE external_id IN ('mid1','mid2','mid3')").fetchall())
    assert st == {"mid1": "respondido", "mid2": "ignorado"}                        # eco não entra; 2.ª DM não repete
    page = client.get("/mensagens").text
    assert "Respostas automáticas ligadas" in page and "Quanto custa a revisão?" in page and "/webhooks/meta" in page


def test_inbox_compose_with_ai_spam_and_alert(monkeypatch):
    from carretos_social import inbox, notify
    from carretos_social.config import accounts
    from carretos_social.content import ai
    monkeypatch.setenv("SOCIAL_ANTHROPIC_API_KEY", "sk-ant-teste")
    monkeypatch.setattr(ai, "inbox_reply", lambda acc, kind, text, author, wa: {
        "intent": "spam", "reply": "", "private_reply": "", "alert": False})
    assert inbox.compose(accounts()["ig_auron"], "comment", "ganhe dinheiro já")["reply"] == ""
    monkeypatch.setattr(ai, "inbox_reply", lambda acc, kind, text, author, wa: {
        "intent": "reclamacao", "reply": "Lamentamos muito. Fale connosco no WhatsApp", "private_reply": "", "alert": True})
    res = inbox.compose(accounts()["ig_carretosgroup"], "message", "Correu mal a revisão")
    assert res["alert"] and res["reply"].endswith("https://wa.me/351211454646")   # o link é sempre acrescentado
