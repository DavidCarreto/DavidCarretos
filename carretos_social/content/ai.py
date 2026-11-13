"""Geração de conteúdo com Claude: ideias, guiões, legendas, recomendações e escolha de cortes.

Requer ANTHROPIC_API_KEY no .env. Todas as respostas são JSON validado por esquema.
"""
from __future__ import annotations

import json
import os

import anthropic

from ..config import Account, brand

MODEL = os.environ.get("CARRETOS_MODEL", "claude-opus-5-5")

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _system() -> str:
    b = brand()
    pillars = "\n".join(f"- {p['id']}: {p['name']} — {p['description']}" for p in b["pillars"])
    voices = "\n".join(f"- {k}: {v}" for k, v in b["voices"].items())
    rules = "\n".join(f"- {r}" for r in b["rules"])
    return f"""És o diretor de conteúdo e social media de {b['owner']}, dono da {b['company']} \
({b['workshops_count']} oficinas). Especialidade: {b['specialty']}.
Escreves sempre em {b['language']} (português de Portugal).

Pilares de conteúdo:
{pillars}

Tom de voz por tipo de conta:
{voices}

Regras obrigatórias:
{rules}

Conheces a fundo o que funciona em cada rede: Reels/TikTok (gancho visual e verbal nos 2 primeiros \
segundos, legendas no ecrã, 15–45 s, ritmo rápido, loop no fim), carrosséis (slide 1 = promessa forte, \
1 ideia por slide, último slide = CTA), LinkedIn (primeira linha que obriga a "ver mais", frases curtas, \
história → lição → pergunta), Facebook (comunidade, emoção, histórias mais longas)."""


def _ask(prompt: str, schema: dict, max_tokens: int = 16000, effort: str = "medium") -> dict:
    response = client().beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=_system(),
        messages=[{"role": "user", "content": prompt}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("O modelo recusou o pedido; reformula o tema.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Resposta cortada (max_tokens); pede menos itens de cada vez.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props),
            "additionalProperties": False}


STR = {"type": "string"}
STRS = {"type": "array", "items": STR}

POST_SCHEMA = _obj({
    "title": STR,
    "pillar": STR,
    "format": STR,
    "hook": STR,
    "script": {"type": "array", "items": _obj({
        "seconds": STR, "visual": STR, "voice_or_text": STR})},
    "on_screen_texts": STRS,
    "caption": STR,
    "hashtags": STRS,
    "cover_text": STR,
    "slides": STRS,
    "filming_notes": STR,
})


def _account_line(acc: Account) -> str:
    return f"Conta: {acc.name} (@{acc.handle}) — plataforma {acc.platform} — voz '{acc.voice}'."


def generate_posts(acc: Account, slots: list[dict], insights: dict | None = None,
                   context: str = "") -> list[dict]:
    """Gera uma publicação completa para cada slot ({pillar, format, scheduled_at})."""
    schema = _obj({"posts": {"type": "array", "items": POST_SCHEMA}})
    prompt = f"""{_account_line(acc)}

Desempenho recente desta conta (usa para decidir ganchos, temas e formatos):
{json.dumps(insights or {}, ensure_ascii=False, indent=1)}

Contexto/novidades da semana dadas pelo David:
{context or '(nenhum — usa ideias perenes e deixa [PREENCHER] onde for preciso um facto real)'}

Cria exatamente {len(slots)} publicações, uma por slot, pela mesma ordem:
{json.dumps(slots, ensure_ascii=False, indent=1)}

Para cada uma:
- title: nome interno curto
- pillar e format: iguais ao slot
- hook: frase de abertura (máx. 12 palavras)
- script: para vídeo/reel, cenas com tempo, o que filmar e o que dizer/escrever; para imagem/carrossel, vazio
- on_screen_texts: textos curtos a sobrepor no vídeo (máx. 6 palavras cada)
- caption: legenda pronta a publicar, adaptada à plataforma (LinkedIn mais longo, TikTok curto)
- hashtags: 3–8, sem repetir sempre os mesmos
- cover_text: texto da capa (máx. 5 palavras, impactante)
- slides: para carrossel, o texto de cada slide (6–9); caso contrário vazio
- filming_notes: dicas práticas de gravação nas oficinas (enquadramento, luz, som)"""
    return _ask(prompt, schema, effort="high")["posts"]


def rewrite_for_account(post: dict, target: Account) -> dict:
    """Adapta uma publicação existente a outra conta/plataforma (reaproveitamento)."""
    prompt = f"""Adapta esta publicação para {_account_line(target)}
Mantém a ideia central, muda o tom, o tamanho da legenda e os hashtags para a plataforma.

Publicação original:
{json.dumps(post, ensure_ascii=False, indent=1)}"""
    return _ask(prompt, POST_SCHEMA)


def recommendations(report: list[dict]) -> dict:
    schema = _obj({
        "headline": STR,
        "per_account": {"type": "array", "items": _obj({
            "account_id": STR, "diagnosis": STR, "keep_doing": STRS, "change": STRS,
            "next_content_ideas": STRS})},
        "cross_platform": STRS,
    })
    prompt = f"""Analisa as métricas dos últimos 30 dias de todas as contas e dá recomendações \
concretas e acionáveis (o que manter, o que mudar, 3 ideias de conteúdo por conta). \
Se uma conta não tiver dados, diz como começar.

{json.dumps(report, ensure_ascii=False, indent=1)}"""
    return _ask(prompt, schema, effort="high")


def select_highlights(segments: list[dict], target_seconds: int, goal: str) -> dict:
    """Escolhe os melhores momentos de um vídeo pessoal a partir da transcrição.

    segments: [{"start": s, "end": s, "text": "..."}]
    """
    schema = _obj({
        "title": STR,
        "hook_text": STR,
        "cover_text": STR,
        "clips": {"type": "array", "items": _obj({
            "start": {"type": "number"}, "end": {"type": "number"}, "reason": STR})},
        "caption": STR,
        "hashtags": STRS,
    })
    prompt = f"""Tens a transcrição de um vídeo pessoal do David (com tempos em segundos).
Objetivo: um vídeo vertical de cerca de {target_seconds} s. {goal}

Escolhe os cortes (start/end tirados dos segmentos, por ordem cronológica) que:
1. começam com a frase mais forte possível como gancho,
2. eliminam hesitações, repetições e tempos mortos,
3. contam uma história com princípio, meio e fim.
Dá também um texto de gancho para o ecrã, um texto de capa e uma legenda.

Transcrição:
{json.dumps(segments, ensure_ascii=False)}"""
    return _ask(prompt, schema)


SCENE_SCHEMA = _obj({
    "type": {"type": "string", "enum": ["hook", "text", "list", "stat", "quote", "media", "cta"]},
    "voiceover": STR,
    "title": STR,
    "body": STR,
    "kicker": STR,
    "items": STRS,
    "value": STR,
    "highlight": STRS,
    "visual": STR,
})

STORYBOARD_SCHEMA = _obj({
    "title": STR, "cover_text": STR, "caption": STR, "hashtags": STRS,
    "scenes": {"type": "array", "items": SCENE_SCHEMA},
})


def storyboard(acc: Account, topic: str, seconds: int = 35, pillar: str = "", post: dict | None = None,
               library: list[str] | None = None) -> dict:
    """Guião em cenas para um vídeo criado do zero (narração + grafismo + imagens)."""
    prompt = f"""{_account_line(acc)}
Cria o storyboard de um vídeo vertical de ~{seconds} segundos, feito SEM filmagem: narração em voz \
sintetizada (português de Portugal), grafismo animado e imagens de fundo.

Tema: {topic}
Pilar: {pillar or '(escolhe o mais adequado)'}
{('Publicação planeada (usa o gancho, a ideia e a legenda): ' + json.dumps(post, ensure_ascii=False)) if post else ''}

Regras:
- 5 a 8 cenas. Cena 1 = "hook" (máx. 10 palavras, provoca curiosidade). Última = "cta".
- Usa variedade: "list" para passos/sinais, "stat" para um número (só números reais ou genéricos e \
verdadeiros; nunca inventes estatísticas da empresa — a empresa tem 5 oficinas), "text" para ideias, \
"quote" para lições de liderança, "media" quando a imagem fala por si.
- voiceover: frases curtas e naturais para ser lido em voz alta; ~2,6 palavras por segundo no total.
- title: texto no ecrã (máx. 8 palavras; no "hook" pode repetir a frase). body/kicker opcionais (vazio se não usar).
- items: só em "list" (2–4 itens, máx. 5 palavras cada). value: só em "stat" (ex.: "5", "90%").
- highlight: 1–2 palavras do title a destacar a azul.
- visual: palavras-chave EM INGLÊS para procurar o fundo (ex.: "mercedes engine close up", \
"mechanic workshop"); dá prioridade a estes ficheiros reais do David se fizerem sentido: {library or []}
- caption, hashtags e cover_text (máx. 5 palavras) prontos a publicar."""
    return _ask(prompt, STORYBOARD_SCHEMA, effort="high")
