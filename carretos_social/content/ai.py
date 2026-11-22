"""Geração de conteúdo com Claude: ideias, guiões, legendas, recomendações e escolha de cortes.

Requer SOCIAL_ANTHROPIC_API_KEY no .env (chave própria das redes sociais, separada da do
sistema de avaliações). Todas as respostas são JSON validado por esquema.
"""
from __future__ import annotations

import contextvars
import json
import os

import anthropic

from ..config import Account, brand

MODEL = os.environ.get("CARRETOS_MODEL", "claude-opus-5-5")

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = os.environ.get("SOCIAL_ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("Falta SOCIAL_ANTHROPIC_API_KEY no .env (chave 'carretos-redes-sociais').")
        _client = anthropic.Anthropic(api_key=key)
    return _client


_BRAND: contextvars.ContextVar[str] = contextvars.ContextVar("facts_brand", default="geral")
_ACCOUNT: contextvars.ContextVar[str] = contextvars.ContextVar("facts_account", default="")

_NETWORKS = """Conheces a fundo o que funciona em cada rede: Reels/TikTok (gancho visual e verbal nos 2 primeiros \
segundos, legendas no ecrã, 15–45 s, ritmo rápido, loop no fim), carrosséis (slide 1 = promessa forte, \
1 ideia por slide, último slide = CTA), LinkedIn (primeira linha que obriga a "ver mais", frases curtas, \
história → lição → pergunta), Facebook (comunidade, emoção, histórias mais longas)."""


def _knowledge_text(k: dict, name: str) -> str:
    """Bloco da base de conhecimento (dashboard → Conhecimento) para as instruções da IA."""
    facts = "\n".join(f"- {f}" for f in k["facts"]) or "- (nenhum ainda)"
    parts = [f"""FACTOS CONFIRMADOS — {name} (os ÚNICOS factos concretos que podes afirmar: pessoas, empresa,
produtos, serviços, condições, preços, números, locais, datas, contactos):
{facts}
Qualquer outro facto concreto → [PREENCHER: o que falta]."""]
    if k["cta"]:
        parts.append(f"CHAMADA À AÇÃO PRINCIPAL (usa esta quando houver chamada à ação): {k['cta']}"
                     + (f"\nAlternativa (só como segunda opção): {k['alt']}" if k["alt"] else ""))
    if k["rules"]:
        parts.append("Regras desta marca:\n" + "\n".join(f"- {r}" for r in k["rules"]))
    if k["never"]:
        parts.append("NUNCA publicar (interno ou ainda em desenvolvimento):\n" + "\n".join(f"- {r}" for r in k["never"]))
    if k["forbidden"]:
        parts.append("PALAVRAS PROIBIDAS nestas contas (nunca as escrevas; só podem aparecer dentro de um link): "
                     + ", ".join(k["forbidden"]) + ". Em vez disso descreve o benefício.")
    return "\n\n".join(parts)


def _system(brand_id: str | None = None, account_id: str | None = None) -> str:
    """Instruções da IA para a marca da conta em causa. Cada marca usa SÓ a sua base de conhecimento e o seu tom
    ('geral' = David Carreto + Carretos Group; outras, ex.: 'auron', ficam totalmente separadas)."""
    from .. import knowledge
    brand_id = brand_id or _BRAND.get()
    account_id = account_id if account_id is not None else (_ACCOUNT.get() or None)
    b = brand()
    k = knowledge.prompt_block(brand_id, account_id)
    general_rules = [r for r in b["rules"] if "Mercedes" not in r and "David" not in r]
    if brand_id != "geral":
        name = ((b.get("marcas") or {}).get(brand_id) or {}).get("nome") or brand_id.upper()
        pillars = "\n".join(f"- {p['id']}: {p['name']} — {p['description']}" for p in b["pillars"]
                            if p.get("marca") == brand_id) or "- (sem pilares definidos)"
        tone = k["tone"] or b["voices"].get(brand_id) or "neutro, profissional, frases curtas"
        rules = "\n".join(f"- {r}" for r in general_rules)
        return f"""És o diretor de conteúdo e social media da marca {name}.
Escreves sempre em {b['language']} (português de Portugal).
A {name} é uma marca à parte: NÃO fales do David Carreto, da Carretos Group, das oficinas Carretos nem de
Mercedes, a não ser que esteja nos factos da {name} abaixo.

Tom de comunicação da {name}:
{tone}

Pilares de conteúdo:
{pillars}

{_knowledge_text(k, name)}

Regras obrigatórias:
{rules}
- Nunca respondas nem cries respostas a avaliações Google (isso é feito por outro sistema).

{_NETWORKS}"""
    pillars = "\n".join(f"- {p['id']}: {p['name']} — {p['description']}" for p in b["pillars"] if not p.get("marca"))
    voices = "\n".join(f"- {k2}: {v}" for k2, v in b["voices"].items() if k2 not in (b.get("marcas") or {}))
    rules = "\n".join(f"- {r}" for r in b["rules"])
    return f"""És o diretor de conteúdo e social media de {b['owner']} e da {b['company']}.
Escreves sempre em {b['language']} (português de Portugal).

Pilares de conteúdo:
{pillars}

Tom de voz por tipo de conta:
{voices}{chr(10) + "Notas de tom: " + k["tone"] if k["tone"] else ""}

{_knowledge_text(k, "David Carreto e Carretos Group")}
Conhecimento técnico geral sobre Mercedes é permitido; factos sobre a Carretos Group só da lista acima.

Regras obrigatórias:
{rules}
- Nunca respondas nem cries respostas a avaliações Google (isso é feito por outro sistema).

{_NETWORKS}"""


def verified_facts(brand_id: str | None = None, account_id: str | None = None) -> list[str]:
    """Factos publicáveis da base de conhecimento (por secção), da marca indicada ou da conta em causa."""
    from .. import knowledge
    return knowledge.publishable_lines(brand_id or _BRAND.get(), account_id)


def brand_tone(brand_id: str | None = None) -> str:
    from .. import knowledge
    from ..db import connect
    with connect() as conn:
        return knowledge.tone(conn, brand_id or _BRAND.get())


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
    """Linha da conta no pedido à IA. Também escolhe a marca (factos e tom) das instruções desse pedido."""
    from ..config import facts_brand
    _BRAND.set(facts_brand(acc.id))
    _ACCOUNT.set(acc.id)
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


MONTAGE_SCHEMA = _obj({
    "title": STR, "hook_text": STR, "cover_text": STR, "caption": STR, "hashtags": STRS,
    "segments": {"type": "array", "items": _obj({
        "clip": {"type": "integer"}, "start": {"type": "number"}, "end": {"type": "number"}, "reason": STR})},
    "broll": {"type": "array", "items": _obj({
        "at": {"type": "number"}, "seconds": {"type": "number"}, "visual": STR, "caption": STR})},
})


def plan_montage(acc: Account, clips: list[dict], target_seconds: int, goal: str = "",
                 library: list[str] | None = None) -> dict:
    """Escolhe os melhores trechos de vários vídeos e onde encaixar imagens (b-roll).

    clips: [{"clip": i, "name": "...", "segments": [{"start","end","text"}]}]
    """
    prompt = f"""{_account_line(acc)}
Tens a transcrição de {len(clips)} vídeos do David a falar (tempos em segundos, por vídeo).
Monta UM vídeo vertical de ~{target_seconds} s. {goal}

1. segments: escolhe trechos (clip = número do vídeo; start/end dentro dos tempos desse vídeo) e põe-nos
   pela ordem que conta a melhor história: abre com a frase mais forte (gancho), desenvolve, termina com
   uma ideia marcante. Corta hesitações e repetições. Usa trechos de vários vídeos se fizer sentido.
   Cada trecho deve ser uma ou mais frases completas.
2. broll: 2–4 momentos (at = segundo na linha temporal FINAL, depois de juntar os trechos) em que a imagem
   muda para uma foto/vídeo da biblioteca durante 2–4 s enquanto a voz continua. visual = nome do ficheiro
   ou palavras-chave da biblioteca: {library or []}. caption = texto curto opcional (vazio se não houver).
3. hook_text (máx. 8 palavras, no ecrã nos primeiros segundos), cover_text (máx. 5 palavras), caption e
   hashtags prontos a publicar. Não inventes factos.

Vídeos:
{json.dumps(clips, ensure_ascii=False)}"""
    return _ask(prompt, MONTAGE_SCHEMA, effort="high")


def write_caption(acc: Account, fmt: str, brief: str) -> dict:
    """Legenda + hashtags para uma publicação já feita (ex.: carrossel de frases), sem inventar factos."""
    schema = _obj({"caption": STR, "hashtags": STRS})
    prompt = f"""{_account_line(acc)}
Formato: {fmt}.

Conteúdo da publicação (já criado; NÃO o alteres, escreve só a legenda para ele):
{brief}

Escreve:
- caption: legenda pronta a publicar, adaptada à plataforma, que acompanha este conteúdo
  (primeira linha forte). Se houver uma pergunta para o público, vem ANTES da chamada à ação. Se a
  legenda tiver um link de chamada à ação (ex.: para ver o preço e marcar), a ÚLTIMA linha é essa chamada
  com o link (no Instagram pode acrescentar "(link na bio)"); não ponhas nada depois dela. Não acrescentes
  outros contactos (ex.: WhatsApp) quando a chamada à ação já é o link. Sem factos novos:
  se precisares de um facto concreto que não está nos FACTOS CONFIRMADOS, usa [PREENCHER: ...].
  Não acrescentes dados da empresa (n.º de oficinas, localidades, serviços, números) se o conteúdo
  não falar disso: uma legenda curta e pessoal é melhor do que uma com dados a mais.
  Evita [PREENCHER] sempre que a legenda funcione sem esse facto.
  NÃO inventes afirmações sobre a vida, a experiência ou as histórias do David (ex.: "aprendi isto na
  oficina", "estas frases não são de nenhum livro", "quando comecei…"): também são factos. Só as usas se
  estiverem nos FACTOS CONFIRMADOS; caso contrário escreve a legenda sem elas (ou [PREENCHER: …]).
- hashtags: 3 a 8, relevantes."""
    return _ask(prompt, schema, max_tokens=4000, effort="low")


INTENTS = ["pergunta", "preco", "marcacao", "elogio", "reclamacao", "spam", "outro"]


def inbox_reply(acc: Account, kind: str, text: str, author: str, whatsapp: str) -> dict:
    """Resposta automática a um comentário ou mensagem, sempre a encaminhar para o assistente do WhatsApp."""
    schema = _obj({"intent": {"type": "string", "enum": INTENTS}, "reply": STR, "private_reply": STR,
                   "alert": {"type": "boolean"}})
    where = "comentário público numa publicação" if kind == "comment" else "mensagem privada (DM)"
    prompt = f"""{_account_line(acc)}
Recebemos este {where} de "{author or 'alguém'}":
\"\"\"{text[:1500]}\"\"\"

O WhatsApp {whatsapp} tem um assistente disponível 24 horas que dá o preço da revisão na hora, explica o
orçamento e os serviços e faz a marcação. Escreve a resposta automática:
- intent: pergunta | preco | marcacao | elogio | reclamacao | spam | outro
- reply: resposta curta (máximo 2 frases e cerca de 250 carateres, no tom da conta, tratar por "você"), que encaminha SEMPRE para o
  WhatsApp {whatsapp} quando há uma pergunta, pedido de preço, marcação, dúvida ou reclamação. Nunca dês preços,
  prazos, disponibilidade nem factos que não estejam nos FACTOS CONFIRMADOS: o WhatsApp responde a isso.
  Elogio: agradece de forma curta e calorosa (o WhatsApp é opcional). Spam, ofensas ou mensagens sem sentido:
  reply vazio. Nunca uses [PREENCHER] aqui: se faltar informação, encaminha para o WhatsApp.
- private_reply: (só para comentários) mensagem privada curta a enviar à pessoa, com o link {whatsapp};
  vazio se for elogio simples ou spam.
- alert: true se for reclamação, problema sério, urgência ou algo que o David deva ver pessoalmente."""
    return _ask(prompt, schema, max_tokens=2000, effort="low")

