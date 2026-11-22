# Carretos Studio (sistema de redes sociais): instruções para quem trabalha neste repositório

Este projeto é o **sistema de redes sociais** (análise, criação, edição e publicação de conteúdos).
Trabalha-se apenas na branch `claude/social-media-management-system-goj30w`.

## ⛔ NÃO MEXER: pertence ao sistema de avaliações Google (outro projeto)

Não alterar, não apagar, não reutilizar e não mudar definições de:

**GitHub**
- Repositório `DavidCarreto/carretos-avaliacoes` (privado): todo o conteúdo, branches, workflows
  ("Responder avaliações Google"), issues, etiquetas (`avaliacao-negativa`, `resumo-diario`),
  `DASHBOARD.md` e `dados/`.
- Os secrets e as variáveis desse repositório.
- Neste repositório: a branch `claude/google-reviews-auto-response-f5f1ad` (cópia antiga, não apagar).
- O acesso da aplicação Claude do GitHub ao repositório `carretos-avaliacoes` (não remover).

**Anthropic (Claude Console)**
- As chaves de API "carretos-github" e "carretos-avaliacoes". O sistema de redes sociais usa
  uma chave **própria e separada** (sugestão de nome: "carretos-redes-sociais").

**Google**
- O projeto Google Cloud "carretos-reviews": não usar para outros fins.
- A palavra-passe de aplicação "carretos-avaliacoes" do Gmail das oficinas.
- Fichas Google das oficinas: **este sistema NÃO responde a avaliações Google**, para evitar respostas duplicadas.

**Emails**
- Os emails com assunto "[Carretos] …" e "📬 Resumo diário Carretos" são do sistema de avaliações.
  Este sistema (Carretos Studio) só envia emails de convite, de reposição de palavra-passe e com as legendas dos
  vídeos enviados para os rascunhos do TikTok, com assunto "Carretos Studio · …", a partir de uma conta de email
  PRÓPRIA (SMTP no ⚙), nunca a "carretos-avaliacoes".

## Separação entre os dois sistemas (convenções deste projeto)

| | Redes sociais (este) | Avaliações Google (outro) |
|---|---|---|
| Repositório / branch | `DavidCarretos` · `claude/social-media-management-system-goj30w` | `carretos-avaliacoes` |
| Chave da IA | `SOCIAL_ANTHROPIC_API_KEY` ("carretos-redes-sociais") | `ANTHROPIC_API_KEY` ("carretos-github") |
| Notificações | Telegram "📣 Carretos Studio · "; emails "Carretos Studio · …" (conta própria) | Email "[Carretos] …" |
| Google | não usa nenhuma API Google | Business Profile, projeto "carretos-reviews" |

## Voz e gravações do David
Ler `docs/VOZ.md` antes de usar qualquer áudio ou vídeo de voz. As gravações servem só para a voz;
o conteúdo não é factual. Os vídeos do YouTube, a gravação do telemóvel e os 45 vídeos curtos partilhados **não se usam sem
autorização explícita do David**: propor primeiro e esperar pela aprovação.

## Não inventar factos (base de conhecimento)
A IA só afirma factos concretos que estejam na **base de conhecimento** (dashboard → Conhecimento; fichas
"publicáveis" e válidas da marca da conta). As fichas de partida estão em `config/conhecimento.yaml` (só
servem para criar/propor fichas; o que vale é o que está no dashboard). O resto sai como `[PREENCHER: ...]`
e a publicação fica bloqueada até ser completada. Fichas "interno"/"em desenvolvimento" nunca se publicam e
as suas palavras bloqueiam a aprovação.

## Marcas separadas (AURON)
A AURON é uma 3.ª marca (grupo `auron`, só Página de Facebook e Instagram @_auron_2026, portefólio Meta
"RibaMotor"). Tem fichas e tom próprios (dashboard → Conhecimento → AURON) e a IA
nunca mistura os factos da AURON com os do David/Carretos Group (nem o contrário).

