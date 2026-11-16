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
   *Sem tempo para gravar?* `carretos produce` cria sozinho os vídeos e as imagens de toda a semana (ver "Criar vídeos do zero").
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

## Dashboard (o teu painel)

`carretos web` arranca o painel em http://localhost:8000 (no servidor fica sempre ligado, com HTTPS). Palavra-passe em `DASHBOARD_PASSWORD`.

- **Visão**: o que está para aprovar, as próximas publicações e o desempenho de cada conta.
- **Agenda**: calendário do mês com todas as publicações, coloridas por estado.
- **Aprovar**: pré-visualização de cada vídeo ou imagem, com Aprovar, Editar e Rejeitar.
- **Criar**: vídeo do zero a partir de um tema, edição de um vídeo teu, montagem de vários vídeos ou imagem com uma frase.
- **Assistente**: escreves em português ("passa o post de quarta para as 20h", "cria 3 vídeos sobre liderança") e ele faz.

**Equipa e permissões:** cada pessoa entra com o seu utilizador. Em **Equipa** (só o administrador), dás a cada pessoa, conta a conta, as permissões **Criar** e/ou **Aprovar**. Quem não tem acesso a uma conta não a vê: nem a agenda, nem os vídeos, nem as métricas, e o assistente também não lhe mexe. Fica registado quem criou e quem aprovou cada publicação.

Para instalar num servidor Ubuntu: `deploy/setup_servidor.sh`. Guias: `docs/GUIA_INSTAGRAM.md` e `docs/TESTE_KLING.md`.

## Montagem de vários vídeos

`carretos montage v1.mp4 v2.mp4 v3.mp4 --account ig_davidcarreto --seconds 45`: a IA escolhe os melhores trechos e a ordem, e encaixa fotos ou vídeos da biblioteca enquanto a voz continua. Junta legendas karaoke, música e capa.

## Criar vídeos do zero (sem gravar nada)

```bash
carretos create-video --account ig_carretoclips --topic "3 sinais de que a caixa 7G-Tronic vai avariar"
carretos create-video --account li_carretosgroup --post 31          # usa o guião já planeado
carretos produce --days 7                                          # piloto automático: cria TUDO o que falta na agenda
```

1. **A IA escreve o storyboard**: 5 a 8 cenas com gancho, listas, números, frases de liderança e uma chamada à ação final, mais a narração, os textos no ecrã, a legenda, os hashtags e o texto da capa.
2. **Narração em português de Portugal**, gerada localmente com o [Piper](https://github.com/rhasspy/piper) (gratuito; a voz descarrega-se sozinha na primeira utilização).
3. **Fundos de cada cena**, por esta ordem: os teus ficheiros reais em `assets/library/` (ver o LEIA-ME dessa pasta), depois vídeos de stock gratuitos do Pexels (com `PEXELS_API_KEY`) e, se não houver nenhum, o fundo animado da marca.
4. **Grafismo animado**: palavras que aparecem uma a uma no gancho, listas que entram ponto a ponto, números que contam, *zoom* lento nas fotos e um CTA com o teu @.
5. **Acabamento** igual ao dos vídeos editados: legendas sincronizadas com a narração, logótipo, música, áudio normalizado, intro/outro e **capa automática**.

### Narração com a tua voz (gratuito)

O clone de voz usa o [Chatterbox](https://github.com/resemble-ai/chatterbox) (código aberto, licença MIT, uso comercial permitido) e corre no teu computador.

1. Grava 1 a 2 minutos com o telemóvel, num sítio silencioso, a falar naturalmente como nos teus vídeos.
2. Corre `carretos voice-setup gravacao.m4a`: limpa o ruído, normaliza o volume e guarda a parte com fala em `assets/voz/david_referencia.wav`. Esta pasta nunca vai para o GitHub.
3. Testa com `carretos voice-test "Olá, sou o David Carreto e hoje vou mostrar-te um Mercedes difícil."`.

Cada conta escolhe a voz em `config/accounts.yaml` (`narrator: david` ou `narrator: generica`). Por omissão, as contas pessoais e a da Carretos Group usam a tua voz e o Carreto Clips usa a voz genérica. Podes ajustar o tom em `config/brand.yaml`: `exaggeration` torna a voz mais calma ou mais enérgica. Se a gravação ainda não existir, o sistema usa a voz genérica e avisa.

Num computador sem placa gráfica, o clone demora cerca de 1 a 3 minutos por cada 30 segundos de narração. As narrações ficam em cache, por isso não se repetem.

Também podes escrever o storyboard à mão, sem IA: `carretos create-video --account tt_carretoclips --storyboard exemplos/storyboard_exemplo.json`.

O `carretos produce` cria também as **imagens** que faltam: carrosséis a partir dos slides da IA, cartões de frase para liderança e dificuldades, e fotos com título para o resto.

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
pip install -e .                   # + ".[s3]" se usares S3/R2 para alojar imagens
carretos init                      # cria a base de dados e o .env
# preenche o .env (ver abaixo)
carretos status                    # confirma as credenciais de cada conta
```

### Credenciais (uma vez)

| O quê | Onde obter |
|---|---|
| `SOCIAL_ANTHROPIC_API_KEY` | console.anthropic.com → API Keys → cria uma chave nova chamada **carretos-redes-sociais** (não uses as chaves do sistema de avaliações) |
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
carretos create-video --account <conta> --topic "..." | --post <id> | --storyboard f.json
carretos produce [--days 7] | montage <vídeos> | web | avatar-video (pago)
carretos voice-setup <gravação> | voice-test "texto" [--narrator david|generica]
carretos repurpose <ficheiro> | cover | image quote|photo|carousel | attach <id> <ficheiros>
carretos edit <id> | schedule <id> <data> | approve <ids> | reject <ids> [--regenerate]
carretos publish <id> [--dry-run] | publish-due | run | dashboard
```

## Segurança

- As credenciais ficam só no `.env`, que está no `.gitignore` e nunca é enviado para o GitHub.
- Por omissão **nada é publicado sem a tua aprovação** (`auto_approve: false`).
- Publicações com `[PREENCHER]` na legenda (factos que a IA não sabe) são bloqueadas até as completares.
