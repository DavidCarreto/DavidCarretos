# Carretos Social: instruções para quem trabalha neste repositório

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
  Este sistema notifica por Telegram e não usa esses assuntos.

## Separação entre os dois sistemas (convenções deste projeto)

| | Redes sociais (este) | Avaliações Google (outro) |
|---|---|---|
| Repositório / branch | `DavidCarretos` · `claude/social-media-management-system-goj30w` | `carretos-avaliacoes` |
| Chave da IA | `SOCIAL_ANTHROPIC_API_KEY` ("carretos-redes-sociais") | `ANTHROPIC_API_KEY` ("carretos-github") |
| Notificações | Telegram, prefixo "📣 Redes Sociais · " | Email "[Carretos] …" |
| Google | não usa nenhuma API Google | Business Profile, projeto "carretos-reviews" |

## Voz e gravações do David
Ler `docs/VOZ.md` antes de usar qualquer áudio ou vídeo de voz. As gravações servem só para a voz;
o conteúdo não é factual. Os vídeos do YouTube e a gravação do telemóvel **não se usam sem
autorização explícita do David**: propor primeiro e esperar pela aprovação.

## Não inventar factos
A IA só afirma factos concretos que estejam em `config/factos.yaml`; o resto sai como
`[PREENCHER: ...]` e a publicação fica bloqueada até ser completada.
