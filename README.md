# Carretos Social

Sistema de gestão automática das redes sociais de **David Carreto** e da **Carretos Group**:
analisa métricas, cria planos e agendas de conteúdo, escreve guiões e legendas com IA,
**edita os teus vídeos automaticamente**, gera imagens e capas de alta qualidade e
**publica sozinho** na hora certa em cada plataforma.

| Conta | Plataforma | Métricas | Publicação |
|---|---|---|---|
| David Carreto | Instagram | ✅ API | ✅ automática |
| Carreto Clips | Instagram | ✅ API | ✅ automática |
| David Carreto | Facebook pessoal | 📄 importação CSV | 📲 assistida (ver nota) |
| David Carreto | TikTok | ✅ API | ✅ automática* |
| Carreto Clips | TikTok | ✅ API | ✅ automática* |
| David Carreto | LinkedIn pessoal | 📄 CSV (API limitada) | ✅ automática |
| Carretos Group | LinkedIn empresa | ✅ API | ✅ automática |

> **Facebook pessoal:** desde 2018 a Meta não permite publicar em perfis pessoais por API (a
> nenhuma ferramenta). O sistema prepara tudo (vídeo editado, capa, legenda) e envia-te para o
> telemóvel via Telegram para publicares em 1 toque. Alternativa: criar uma Página "David Carreto"
> — páginas têm publicação automática.
>
> **\*TikTok:** até a tua app TikTok passar a auditoria, o TikTok só aceita publicações privadas
> por API. Depois de aprovada, muda `TIKTOK_PRIVACY=PUBLIC_TO_EVERYONE`.

---

## Como funciona (o ciclo semanal)

```
 métricas ──► análise ──► plano/agenda ──► IA cria guiões ──► gravas ──► edição automática ──► aprovas ──► publica sozinho
   ▲                                                                                                          │
   └──────────────────────────────────────────── recolha de resultados ◄──────────────────────────────────────┘
```

1. **`carretos sync`**: recolhe as métricas de todas as contas (o agendador faz isto de 6 em 6 horas).
2. **`carretos report --ai`**: envolvimento por conta, formato e tema, melhores horas e dias, top publicações e recomendações da IA.
3. **`carretos plan`**: cria a agenda da semana conforme a estrutura acordada em `config/strategy.yaml` (frequência, formatos, mistura de temas). As horas ajustam-se sozinhas às horas com mais envolvimento de cada conta.
4. **`carretos generate --context "..."`**: a IA escreve cada publicação: gancho, guião cena a cena, textos para o ecrã, legenda adaptada à plataforma, hashtags, texto da capa, slides de carrossel e dicas de gravação.
5. **Gravas** nas oficinas, seguindo o guião.
6. **`carretos edit-video`** ou **`carretos repurpose`**: edição automática (ver abaixo).
7. **`carretos approve`**: aprovas (ou ligas `auto_approve: true` nas contas onde confias).
8. **`carretos run`**: o agendador publica à hora certa, recolhe métricas e lembra-te do que falta aprovar.

## Edição automática de vídeo

`carretos edit-video meu_video.mp4 --account tt_carretoclips --post 21`

- **Transcreve** o que dizes (faster-whisper, em português).
- **A IA escolhe os melhores momentos** para a duração pedida: abre com a frase mais forte e corta hesitações, repetições e tempos mortos. Sem IA, faz remoção automática de silêncios.
- **Reenquadra** para o formato de cada rede (9:16 para Reels e TikTok, 4:5 para o LinkedIn), com fundo desfocado ou recorte.
- **Legendas grandes "estilo Reels"** com a palavra a ser dita em destaque, mais um **texto de gancho** nos primeiros 3 segundos.
- **Logótipo, música de fundo** que baixa sozinha quando falas, **áudio normalizado** a −14 LUFS e **intro/outro** da marca.
- Exporta em **H.264 de alta qualidade** (CRF 18, 1080p, 30 fps, faststart).
- **Capa automática**: escolhe o frame mais nítido e bem exposto e aplica o texto da capa com o design da marca.

`carretos repurpose video.mp4` faz o mesmo para **todas as contas de vídeo** de uma vez: renderiza cada formato uma só vez, adapta a legenda ao tom de cada conta e coloca cada versão no próximo slot livre.

## Imagens e capas

```bash
carretos cover "Nunca faças isto ao teu Mercedes" --video clip.mp4 --highlight mercedes
carretos image carousel --post 7 --account ig_carretoclips     # usa os slides gerados pela IA
carretos image quote --text "Liderar é ..." --photo equipa.jpg
carretos image photo --photo oficina.jpg --text "Abrimos a 5.ª oficina" --tag Conquista
```

Tudo é renderizado a 2× e reduzido no fim, para texto perfeito. As cores e as fontes vêm de `config/brand.yaml`.
Coloca o teu logótipo em `assets/brand/logo.png`, a intro e o outro em `assets/brand/intro.mp4` e `assets/brand/outro.mp4`,
e música livre de direitos em `assets/music/`.

---

## Instalação

Requisitos: Python 3.10+ e [ffmpeg](https://ffmpeg.org/download.html).

```bash
pip install -e ".[legendas]"       # + ".[s3]" se usares S3/R2 para alojar imagens
carretos init                      # cria a base de dados e o .env
# preenche o .env (ver abaixo)
carretos status                    # confirma as credenciais de cada conta
```

### Credenciais (uma vez)

| O quê | Onde obter |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| Instagram (as 2 contas) | Converte as contas em **Profissional/Criador** e liga cada uma a uma Página do Facebook. Cria uma app em developers.facebook.com, adiciona o produto *Instagram Graph API* e gera um token de longa duração com `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights` e `pages_show_list`. O `USER_ID` é o *Instagram Business Account ID*. |
| TikTok (as 2 contas) | developers.tiktok.com → app com **Content Posting API** (Direct Post) e **Display API**; permissões `video.publish`, `video.list` e `user.info.stats`; autoriza cada conta (OAuth) e copia o access token. Pede a auditoria para publicar como público. |
| LinkedIn pessoal | linkedin.com/developers → app com *Share on LinkedIn* (`w_member_social`) e *Sign In with OpenID* (para obter o teu `urn:li:person:…`). |
| LinkedIn Carretos Group | Na mesma app, pede a **Community Management API** (`w_organization_social`, `r_organization_social`); o URN é `urn:li:organization:<id da página>`. |
| Alojamento de imagens | O Instagram exige URL público para imagens e capas: um bucket S3 ou Cloudflare R2 (barato) com `MEDIA_BASE_URL` público. |
| Telegram (recomendado) | Fala com o @BotFather, cria um bot e põe o token e o teu chat id no `.env`. Recebes pedidos de aprovação, alertas de falha e os pacotes do Facebook. |

Os tokens da Meta, do TikTok e do LinkedIn expiram (de 60 dias a 1 ano). O `carretos status` e os alertas de falha avisam-te quando for preciso renovar.

### Métricas sem API (Facebook pessoal, LinkedIn pessoal)

Exporta o CSV na própria plataforma (Painel profissional do Facebook, Analytics do LinkedIn) e corre:
`carretos import-csv fb_davidcarreto export.csv`. As colunas são reconhecidas em português e em inglês.

## Pôr a correr sozinho

Num computador sempre ligado, num mini-PC ou num servidor (4 €/mês chegam):

```bash
carretos run          # publica, recolhe métricas e envia lembretes
```

Também podes usar o cron: `* * * * * cd /caminho && carretos publish-due`

## Painel

`carretos dashboard` gera `data/painel.html`, com o desempenho de cada conta e a agenda de 4 semanas
(cada publicação aparece com o estado: ideia, rascunho, aprovado, publicado ou falhou).

## Configuração

- `config/accounts.yaml`: as 7 contas, o modo de publicação e o `auto_approve`.
- `config/brand.yaml`: pilares (Mercedes, Carretos Group e as 5 oficinas, pessoas, liderança, conquistas, dificuldades), tom de voz, regras, hashtags e identidade visual.
- `config/strategy.yaml`: a **estrutura acordada**: publicações por semana, formatos, mistura de temas, dias, horas e tamanhos de exportação por plataforma.

## Referência de comandos

```
carretos status | sync | import-csv | report [--ai]
carretos plan [--start AAAA-MM-DD --days 7] | generate [--context ...] | show <id> | calendar
carretos edit-video <ficheiro> --account <conta> [--post id | --schedule data] [--seconds 45]
carretos repurpose <ficheiro> | cover | image quote|photo|carousel | attach <id> <ficheiros>
carretos edit <id> | schedule <id> <data> | approve <ids> | reject <ids> [--regenerate]
carretos publish <id> [--dry-run] | publish-due | run | dashboard
```

## Segurança

- As credenciais ficam só no `.env`, que está no `.gitignore` e nunca é enviado para o GitHub.
- Por omissão **nada é publicado sem a tua aprovação** (`auto_approve: false`).
- Publicações com `[PREENCHER]` na legenda (factos que a IA não sabe) são bloqueadas até as completares.
