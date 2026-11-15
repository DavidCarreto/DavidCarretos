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
