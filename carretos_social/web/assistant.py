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

from contextvars import ContextVar

from ..config import accounts, brand
from ..db import connect, get_post, update_post
from . import jobs

_USER: ContextVar = ContextVar("user", default=None)


def _me():
    return _USER.get()


def _deny(account_id: str, action: str = "ver") -> str | None:
    me = _me()
    if me is None:
        return "Sem utilizador."
    ok = {"ver": me.can_see, "criar": me.can_create, "aprovar": me.can_approve}[action](account_id)
    return None if ok else f"Não tens permissão para {action} na conta {account_id}."

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
    me = _me()
    out = [_fmt(r) for r in rows if datetime.fromisoformat(r["scheduled_at"][:19]).timestamp() <= limit
           and (not estado or r["status"] == estado) and (not conta or r["account_id"] == conta)
           and me and me.can_see(r["account_id"])]
    return json.dumps(out[:60], ensure_ascii=False)


@beta_tool
def ver_publicacao(id: int) -> str:
    """Mostra todos os detalhes de uma publicação (legenda completa, guião, hashtags).

    Args:
        id: número da publicação.
    """
    with connect() as conn:
        r = dict(get_post(conn, id))
    if (err := _deny(r["account_id"])):
        return err
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
        if (err := _deny(get_post(conn, id)["account_id"], "criar")) and (err := _deny(get_post(conn, id)["account_id"], "aprovar")):
            return err
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
        acc = get_post(conn, id)["account_id"]
        if _deny(acc, "criar") and (err := _deny(acc, "aprovar")):
            return err
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
        row = get_post(conn, id)
        if (err := _deny(row["account_id"], "aprovar")):
            return err
        problems = ready_problems(row)
        if problems:
            return f"Não aprovada: {', '.join(problems)}"
        update_post(conn, id, status="approved", error=None, approved_by=_me().id)
    return f"Publicação #{id} aprovada"


@beta_tool
def rejeitar(id: int) -> str:
    """Rejeita uma publicação (não será publicada).

    Args:
        id: número da publicação.
    """
    with connect() as conn:
        if (err := _deny(get_post(conn, id)["account_id"], "aprovar")):
            return err
        update_post(conn, id, status="rejected", approved_by=_me().id)
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
        return f"Conta desconhecida. Opções: {', '.join(_me().creatable_accounts)}"
    if (err := _deny(conta, "criar")):
        return err
    args = ["--account", conta, "--topic", tema, "--seconds", str(segundos)]
    if data_hora:
        args += ["--schedule", data_hora]
    job = jobs.enqueue("create-video", args, f"Vídeo: {tema[:60]}", user_id=_me().id)
    return f"Tarefa #{job} criada: o vídeo aparece em 'Para aprovar' daqui a alguns minutos."


@beta_tool
def planear_semana(inicio: str = "", contas: str = "") -> str:
    """Cria a agenda de uma semana (slots) e põe a IA a escrever os conteúdos.

    Args:
        inicio: data AAAA-MM-DD (padrão: amanhã).
        contas: ids separados por vírgula, ou vazio para todas.
    """
    args = ["--days", "7"] + (["--start", inicio] if inicio else [])
    me = _me()
    acc = [c.strip() for c in contas.split(",") if c.strip()] or me.creatable_accounts
    acc = [a for a in acc if me.can_create(a)]
    if not acc:
        return "Não tens contas onde possas criar."
    args += ["--accounts", *acc]
    j1 = jobs.enqueue("plan", args, "Planear semana", user_id=me.id)
    j2 = jobs.enqueue("generate", ["--accounts", *acc], "Escrever conteúdos da semana", user_id=me.id)
    return f"Tarefas #{j1} (agenda) e #{j2} (conteúdos) criadas."


@beta_tool
def relatorio(dias: int = 30) -> str:
    """Resumo de desempenho por conta (envolvimento, melhores horas, temas e publicações de topo).

    Args:
        dias: período em dias.
    """
    from ..analytics.analyzer import summary
    with connect() as conn:
        return json.dumps([summary(conn, a, dias) for a in _me().visible_accounts], ensure_ascii=False)


@beta_tool
def estado_tarefas() -> str:
    """Mostra as últimas tarefas da fila (vídeos a criar, planos) e o seu estado."""
    with connect() as conn:
        rows = conn.execute("SELECT id, label, status, post_id, created_at FROM jobs WHERE created_by=? "
                            "ORDER BY id DESC LIMIT 10", (_me().id,))
        return json.dumps([dict(r) for r in rows], ensure_ascii=False)


TOOLS = [listar_publicacoes, ver_publicacao, reagendar, alterar_legenda, aprovar, rejeitar, criar_video,
         planear_semana, relatorio, estado_tarefas]


def _system(me) -> str:
    acc = "\n".join(f"- {a.id}: {a.name} ({a.platform}) — "
                    f"{'criar' if me.can_create(a.id) else ''}{' + ' if me.can_create(a.id) and me.can_approve(a.id) else ''}"
                    f"{'aprovar' if me.can_approve(a.id) else ''}"
                    for a in accounts().values() if me.can_see(a.id))
    return f"""És o assistente do sistema de redes sociais de {brand()['owner']} e da {brand()['company']}.
Estás a falar com: {me.name}{' (administrador)' if me.is_admin else ''}.
Hoje é {date.today().isoformat()} (hora de Lisboa). Responde em português de Portugal, curto e direto.

Contas a que esta pessoa tem acesso (e o que pode fazer):
{acc}
Nunca fales de contas fora desta lista.

Usa as ferramentas para consultar e agir. Regras:
- Só aprovas, rejeitas ou alteras quando o David pede claramente. Na dúvida, mostra e pergunta.
- Para criar vídeos ou planear, usa as ferramentas (ficam na fila e aparecem em "Para aprovar").
- Nunca inventes factos sobre o David ou a empresa; nunca respondas a avaliações Google (outro sistema).
- Não podes alterar o código do sistema; para funcionalidades novas, diz-lhe para pedir no Claude Code.
- Indica sempre o número (#id) das publicações de que falas."""


def reply(message: str, user) -> str:
    _USER.set(user)
    key = os.environ.get("SOCIAL_ANTHROPIC_API_KEY")
    if not key:
        return "Falta configurar a chave da IA (SOCIAL_ANTHROPIC_API_KEY)."
    with connect() as conn:
        conn.execute("INSERT INTO chat(role, content, created_at, user_id) VALUES ('user', ?, ?, ?)",
                     (message, datetime.now().isoformat(timespec="seconds"), user.id))
        history = [dict(r) for r in conn.execute("SELECT role, content FROM chat WHERE user_id=? ORDER BY id DESC "
                                                 "LIMIT 20", (user.id,))][::-1]
    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    client = anthropic.Anthropic(api_key=key)
    runner = client.beta.messages.tool_runner(
        model=MODEL, max_tokens=8000, system=_system(user), tools=TOOLS, messages=messages,
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
        conn.execute("INSERT INTO chat(role, content, created_at, user_id) VALUES ('assistant', ?, ?, ?)",
                     (text, datetime.now().isoformat(timespec="seconds"), user.id))
    return text
