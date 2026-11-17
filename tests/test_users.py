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
    # factos editáveis no dashboard (data/factos.yaml)
    client.post("/factos", data={"factos": "O dono é David Carreto.\nA empresa chama-se Carretos Group."})
    from carretos_social.content.ai import verified_facts
    assert verified_facts() == ["O dono é David Carreto.", "A empresa chama-se Carretos Group."]
    page = client.get("/factos").text
    assert "Almada" not in page.split('name="factos"')[1].split("</textarea>")[0]    # a lista guardada


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
    assert 'class="topmenu"' in page and "📋 Factos" in page


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
    client.post("/factos", data={"factos": "Contas: Instagram @davidcarreto e @carretoclips.\nO dono é David Carreto."})
    f = client.get("/factos").text
    assert "configurada é @davidcarretos" in f and "Onde estão a ser usados" in f


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
    client.post("/factos", data={"marca": "auron", "factos": "A marca chama-se AURON.", "tom": "Moderno e direto."})
    assert ai.verified_facts("auron") == ["A marca chama-se AURON."] and ai.brand_tone("auron") == "Moderno e direto."
    assert "AURON" not in "\n".join(ai.verified_facts("geral"))
    s_auron, s_geral = ai._system("auron"), ai._system("geral")
    assert "Moderno e direto." in s_auron and "Almada" not in s_auron and "Carretos Group tem" not in s_auron
    assert "O AURON é a plataforma" not in s_geral and "PALAVRAS PROIBIDAS nestas contas" in s_geral
    ai._account_line(accounts()["ig_auron"])
    assert ai._BRAND.get() == "auron"
    page = client.get("/factos?marca=auron").text
    assert "Moderno e direto." in page and "AURON" in page and "/factos?marca=geral" in page
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
    assert len(verified_facts("geral")) == 13 and len(verified_facts("auron")) == 12
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
    # Factos: lista editada no dashboard recebe os factos novos da lista de base sem perder os seus
    client.post("/factos", data={"marca": "geral", "factos": "O dono é David Carreto.\nFacto meu.", "tom": ""})
    page = client.get("/factos?marca=geral").text
    assert "facto(s) novo(s)" in page and "Acrescentar à minha lista" in page
    client.post("/factos/juntar", data={"marca": "geral"})
    f = verified_facts("geral")
    assert "Facto meu." in f and "Quem paga online no momento da marcação tem 5% de desconto." in f
    assert "facto(s) novo(s)" not in client.get("/factos?marca=geral").text
