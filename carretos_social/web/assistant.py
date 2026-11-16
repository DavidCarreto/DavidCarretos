"""Assistente do dashboard: conversa em português e age sobre o sistema através de ferramentas.

Usa a chave própria das redes sociais (SOCIAL_ANTHROPIC_API_KEY). Pode consultar e alterar a agenda,
aprovar, editar legendas, pedir relatórios e pôr vídeos/planos a criar na fila de tarefas.
Não altera o código do sistema nem toca no sistema de avaliações Google.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime

import anthropic
from anthropic import beta_tool

from ..config import accounts, brand
from ..db import connect, get_post, update_post
from . import jobs

MODEL = os.environ.get("CARRETOS_MODEL", "claude-opus-5-5")


def _fmt(row) -> dict:
    return {"id": row["id"], "conta": row["account_id"], "quando": (row["scheduled_at"] or "")[:16],
            "estado": row["status"], "formato": row["format"], "tema": row["pillar"], "titulo": row["title"],
            "legenda": (row["caption"] or "")[:300], "tem_media": row["media_ids"] not in (None, "", "[]")}


@beta_tool
def listar_publicacoes(dias: int = 14, estado: str = "", conta: str = "") -> str:
    """Lista publicações agendadas a partir de hoje.

    Args:
        dias: quantos dias para a frente (padrão 14).
        estado: filtrar por estado (idea, draft, approved, published, failed) ou vazio para todos.
        conta: filtrar por id de conta (ex.: ig_davidcarreto) ou vazio para todas.
    """
    with connect() as conn:
        rows = conn.execute("SELECT * FROM posts WHERE scheduled_at >= ? ORDER BY scheduled_at",
                            (date.today().isoformat(),)).fetchall()
    limit = datetime.now().timestamp() + dias * 86400
    out = [_fmt(r) for r in rows if datetime.fromisoformat(r["scheduled_at"][:19]).timestamp() <= limit
           and (not estado or r["status"] == estado) and (not conta or r["account_id"] == conta)]
    return json.dumps(out[:60], ensure_ascii=False)


@beta_tool
def ver_publicacao(id: int) -> str:
    """Mostra todos os detalhes de uma publicação (legenda completa, guião, hashtags).

    Args:
        id: número da publicação.
    """
    with connect() as conn:
        r = dict(get_post(conn, id))
    return json.dumps(r, ensure_ascii=False, default=str)


@beta_tool
def reagendar(id: int, quando: str) -> str:
    """Muda a data/hora de uma publicação.

    Args:
        id: número da publicação.
        quando: data e hora no formato AAAA-MM-DDTHH:MM (hora de Lisboa).
    """
    from ..scheduler import parse_dt
    with connect() as conn:
        update_post(conn, id, scheduled_at=parse_dt(quando).isoformat())
    return f"Publicação #{id} reagendada para {quando}"


@beta_tool
def alterar_legenda(id: int, legenda: str) -> str:
    """Substitui a legenda de uma publicação.

    Args:
        id: número da publicação.
        legenda: nova legenda completa.
    """
    with connect() as conn:
        update_post(conn, id, caption=legenda)
    return f"Legenda da publicação #{id} atualizada"


@beta_tool
def aprovar(id: int) -> str:
    """Aprova uma publicação para sair automaticamente à hora marcada (só se o David pediu).

    Args:
        id: número da publicação.
    """
    from ..scheduler import ready_problems
    with connect() as conn:
        problems = ready_problems(get_post(conn, id))
        if problems:
            return f"Não aprovada: {', '.join(problems)}"
        update_post(conn, id, status="approved", error=None)
    return f"Publicação #{id} aprovada"


@beta_tool
def rejeitar(id: int) -> str:
    """Rejeita uma publicação (não será publicada).

    Args:
        id: número da publicação.
    """
    with connect() as conn:
        update_post(conn, id, status="rejected")
    return f"Publicação #{id} rejeitada"


@beta_tool
def criar_video(conta: str, tema: str, segundos: int = 35, data_hora: str = "") -> str:
    """Põe na fila a criação de um vídeo do zero (guião IA + fotos/vídeos do David + texto + música).

    Args:
        conta: id da conta (ex.: ig_davidcarreto).
        tema: tema ou mensagem do vídeo, em português.
        segundos: duração aproximada.
        data_hora: opcional, AAAA-MM-DDTHH:MM para agendar já.
    """
    if conta not in accounts():
        return f"Conta desconhecida. Opções: {', '.join(accounts())}"
    args = ["--account", conta, "--topic", tema, "--seconds", str(segundos)]
    if data_hora:
        args += ["--schedule", data_hora]
    job = jobs.enqueue("create-video", args, f"Vídeo: {tema[:60]}")
    return f"Tarefa #{job} criada: o vídeo aparece em 'Para aprovar' daqui a alguns minutos."


@beta_tool
def planear_semana(inicio: str = "", contas: str = "") -> str:
    """Cria a agenda de uma semana (slots) e põe a IA a escrever os conteúdos.

    Args:
        inicio: data AAAA-MM-DD (padrão: amanhã).
        contas: ids separados por vírgula, ou vazio para todas.
    """
    args = ["--days", "7"] + (["--start", inicio] if inicio else [])
    acc = [c.strip() for c in contas.split(",") if c.strip()]
    if acc:
        args += ["--accounts", *acc]
    j1 = jobs.enqueue("plan", args, "Planear semana")
    j2 = jobs.enqueue("generate", (["--accounts", *acc] if acc else []), "Escrever conteúdos da semana")
    return f"Tarefas #{j1} (agenda) e #{j2} (conteúdos) criadas."


@beta_tool
def relatorio(dias: int = 30) -> str:
    """Resumo de desempenho por conta (envolvimento, melhores horas, temas e publicações de topo).

    Args:
        dias: período em dias.
    """
    from ..analytics.analyzer import full_report
    with connect() as conn:
        return json.dumps(full_report(conn, dias), ensure_ascii=False)


@beta_tool
def estado_tarefas() -> str:
    """Mostra as últimas tarefas da fila (vídeos a criar, planos) e o seu estado."""
    with connect() as conn:
        rows = conn.execute("SELECT id, label, status, post_id, created_at FROM jobs ORDER BY id DESC LIMIT 10")
        return json.dumps([dict(r) for r in rows], ensure_ascii=False)


TOOLS = [listar_publicacoes, ver_publicacao, reagendar, alterar_legenda, aprovar, rejeitar, criar_video,
         planear_semana, relatorio, estado_tarefas]


def _system() -> str:
    acc = "\n".join(f"- {a.id}: {a.name} ({a.platform})" for a in accounts().values())
    return f"""És o assistente das redes sociais de {brand()['owner']}, dentro do dashboard dele.
Hoje é {date.today().isoformat()} (hora de Lisboa). Responde em português de Portugal, curto e direto.

Contas:
{acc}

Usa as ferramentas para consultar e agir. Regras:
- Só aprovas, rejeitas ou alteras quando o David pede claramente. Na dúvida, mostra e pergunta.
- Para criar vídeos ou planear, usa as ferramentas (ficam na fila e aparecem em "Para aprovar").
- Nunca inventes factos sobre o David ou a empresa; nunca respondas a avaliações Google (outro sistema).
- Não podes alterar o código do sistema; para funcionalidades novas, diz-lhe para pedir no Claude Code.
- Indica sempre o número (#id) das publicações de que falas."""


def reply(message: str) -> str:
    key = os.environ.get("SOCIAL_ANTHROPIC_API_KEY")
    if not key:
        return "Falta configurar a chave da IA (SOCIAL_ANTHROPIC_API_KEY)."
    with connect() as conn:
        conn.execute("INSERT INTO chat(role, content, created_at) VALUES ('user', ?, ?)",
                     (message, datetime.now().isoformat(timespec="seconds")))
        history = [dict(r) for r in conn.execute("SELECT role, content FROM chat ORDER BY id DESC LIMIT 20")][::-1]
    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    client = anthropic.Anthropic(api_key=key)
    runner = client.beta.messages.tool_runner(
        model=MODEL, max_tokens=8000, system=_system(), tools=TOOLS, messages=messages,
        thinking={"type": "adaptive"}, output_config={"effort": "medium"},
    )
    final = None
    for msg in runner:
        final = msg
    if final is None or final.stop_reason == "refusal":
        text = "Não consegui responder a isso. Podes reformular?"
    else:
        text = "\n".join(b.text for b in final.content if b.type == "text").strip() or "Feito."
    with connect() as conn:
        conn.execute("INSERT INTO chat(role, content, created_at) VALUES ('assistant', ?, ?)",
                     (text, datetime.now().isoformat(timespec="seconds")))
    return text
