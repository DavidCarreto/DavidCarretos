import json
import shutil
import subprocess
from datetime import date

import pytest

from carretos_social.analytics import analyzer, connectors
from carretos_social.content import planner
from carretos_social.db import add_media, add_post, connect, get_post
from carretos_social.scheduler import due_posts, publish_post, ready_problems


def test_weighted_sequence_respects_mix():
    seq = planner._weighted_sequence({"a": 60, "b": 20, "c": 20}, 10)
    assert seq.count("a") == 6 and seq.count("b") == 2 and seq.count("c") == 2


def test_plan_matches_posts_per_week_and_no_duplicates():
    with connect() as conn:
        plan = planner.build_plan(conn, date(2026, 11, 16), 7)
        again = planner.build_plan(conn, date(2026, 11, 16), 7)
    by_acc = {}
    for s in plan:
        by_acc[s["account_id"]] = by_acc.get(s["account_id"], 0) + 1
    assert by_acc["tt_carretoclips"] == 7
    assert by_acc["li_carretosgroup"] == 2
    assert again == []


def test_csv_import_and_best_times(tmp_path):
    csv = tmp_path / "m.csv"
    rows = ["id,date,description,views,likes,comments,shares"]
    for i in range(12):
        hour = 20 if i % 2 else 9
        likes = 300 if hour == 20 else 20
        rows.append(f"p{i},2026-11-0{1 + i % 9}T{hour}:00:00+00:00,post {i},\"1,000\",{likes},5,2")
    csv.write_text("\n".join(rows))
    parsed = connectors.import_csv(csv)
    assert parsed[0]["views"] == 1000
    with connect() as conn:
        analyzer.import_metrics(conn, "tt_davidcarreto", csv)
        assert analyzer.best_times(conn, "tt_davidcarreto")[0] == "20:00"


def test_publish_requires_media_and_dry_run_works(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    with connect() as conn:
        pid = add_post(conn, account_id="tt_carretoclips", format="video", caption="Olá",
                       scheduled_at="2020-01-01T10:00:00+00:00", status="approved")
        assert "sem vídeo/imagem associado" in ready_problems(get_post(conn, pid))
        mid = add_media(conn, "video", str(f))
        conn.execute("UPDATE posts SET media_ids=? WHERE id=?", (json.dumps([mid]), pid))
        assert [r["id"] for r in due_posts(conn)] == [pid]
        assert "simulação" in publish_post(conn, pid, dry_run=True)


def test_assist_publisher_builds_package(tmp_path, monkeypatch):
    import carretos_social.publishers.assist as assist
    monkeypatch.setattr(assist, "DATA_DIR", tmp_path)
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    with connect() as conn:
        mid = add_media(conn, "image", str(img))
        pid = add_post(conn, account_id="fb_davidcarreto", format="image", caption="Obrigado equipa!",
                       media_ids=[mid], title="equipa", status="approved",
                       scheduled_at="2020-01-01T10:00:00+00:00")
        out = publish_post(conn, pid)
        assert "assist_sent" in out
    assert (next((tmp_path / "prontos_a_publicar").iterdir()) / "legenda.txt").read_text() == "Obrigado equipa!"


def test_images_render(tmp_path):
    from PIL import Image
    from carretos_social.media import image_gen
    c = image_gen.cover(None, "O erro que destrói caixas", tmp_path / "c.jpg")
    assert Image.open(c).size == (1080, 1920)
    slides = image_gen.carousel(["Título", "Ponto\ndetalhe"], tmp_path / "car")
    assert len(slides) == 3


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg em falta")
def test_video_pipeline(tmp_path):
    from carretos_social.media.video_editor import auto_edit, probe
    src = tmp_path / "in.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=8",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=8", "-af",
                    "volume='if(between(t,3,5),0,1)':eval=frame", "-shortest", str(src)], check=True)
    res = auto_edit(src, tmp_path / "out", width=540, height=960, use_transcription=False, use_ai=False,
                    music=None, hook_text="Teste")
    info = probe(res["video"])
    assert (info.width, info.height) == (540, 960)
    assert info.duration < 7.5


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg em falta")
def test_create_video_from_zero_without_voice(tmp_path):
    from carretos_social.media.creator import create_video
    from carretos_social.media.video_editor import probe
    sb = {"title": "Teste", "scenes": [
        {"type": "hook", "title": "O erro que destrói caixas", "seconds": 2},
        {"type": "list", "title": "Sinais", "items": ["Trancos", "Fumo"], "seconds": 2},
        {"type": "stat", "value": "5", "title": "oficinas", "seconds": 2},
        {"type": "cta", "title": "Segue", "seconds": 2}]}
    res = create_video(sb, tmp_path, size=(360, 640), narration=False, music=None, handle="carretoclips",
                       stock_footage=False)
    info = probe(res["video"])
    assert (info.width, info.height) == (360, 640)
    assert 7.5 < info.duration < 9


def test_library_match(tmp_path, monkeypatch):
    from carretos_social.media import stock
    monkeypatch.setattr(stock, "LIBRARY", tmp_path)
    (tmp_path / "oficina_elevador_mecanico.jpg").write_bytes(b"x")
    (tmp_path / "equipa_reuniao.mp4").write_bytes(b"x")
    assert stock.library_match("mechanic workshop").name == "oficina_elevador_mecanico.jpg"
    assert stock.library_match("team meeting", "video").name == "equipa_reuniao.mp4"
    assert stock.library_match("praia") is None


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg em falta")
def test_prepare_voice_sample_from_audio_only(tmp_path):
    from carretos_social.media.voice import prepare_sample
    src = tmp_path / "rec.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=6",
                    "-af", "volume='if(between(t,2,3),0,1)':eval=frame", str(src)], check=True)
    info = prepare_sample(src, tmp_path / "ref.wav", max_seconds=4)
    assert 3 <= info["speech_seconds"] <= 4.5


def test_narrator_falls_back_to_generic_without_sample(monkeypatch):
    from carretos_social.media import voice
    monkeypatch.setattr(voice, "brand", lambda: {"narrators": {
        "david": {"engine": "chatterbox", "sample": "nao/existe.wav"},
        "generica": {"engine": "piper", "voice": "pt_PT-tugão-medium"}}})
    assert voice.narrator("david")["engine"] == "piper"


def test_next_free_slot_and_no_date_blocks_approval():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from carretos_social.content.planner import next_free_slot
    tz = ZoneInfo("Europe/Lisbon")
    base = datetime(2030, 1, 7, 8, 0, tzinfo=tz)            # segunda-feira
    with connect() as conn:
        first = next_free_slot(conn, "li_carretosgroup", after=base)   # estratégia: ter/qui às 09:00
        assert first.startswith("2030-01-08T09:00")
        add_post(conn, account_id="li_carretosgroup", format="image", caption="x", scheduled_at=first)
        second = next_free_slot(conn, "li_carretosgroup", after=base)
        assert second.startswith("2030-01-10T09:00")           # o slot ocupado é saltado
        pid = add_post(conn, account_id="li_carretosgroup", format="text", caption="sem data")
        assert "sem data/hora" in ready_problems(get_post(conn, pid))
