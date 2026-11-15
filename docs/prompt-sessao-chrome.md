# Prompt para a sessão com acesso ao Chrome

Copiar tudo o que está dentro do bloco abaixo e colar numa conversa nova da aplicação
Claude para computador, com a extensão Claude in Chrome ativa.

```
Vais ajudar-me a configurar um sistema que responde automaticamente às avaliações Google
das 5 oficinas da Carretos Group. O código já está feito e testado. O que falta são
configurações em sites (GitHub, Google Cloud e Anthropic) que tens de fazer no meu Chrome,
onde já tenho as sessões abertas.

CONTEXTO
- Código: repositório GitHub DavidCarreto/DavidCarretos, branch
  claude/google-reviews-auto-response-f5f1ad. O guia completo está no README.md dessa branch.
- Oficinas (só estas 5): Carretos Almada, Carretos Cacém (a principal), Carretos Lisboa,
  Carretos Mafra (abre em março) e Carretos Santarém. A ficha "EQ - CENTER" fica de fora.
- O pedido de acesso à Google Business Profile API já foi enviado para o projeto
  Google Cloud "carretos-reviews" (pedido n.º 7-8350000042338). A aprovação demora
  7 a 10 dias úteis e chega por email.
- Há outros projetos Google Cloud criados pelas agências Inovcorp e Scale Labs.
  NÃO lhes toques. Usa só o projeto "carretos-reviews".

REGRAS
- Nunca me peças para colar chaves, passwords ou tokens no chat, e nunca os escrevas no chat.
  As chaves vão diretamente da página onde são criadas para os Secrets do GitHub.
- Antes de clicar em qualquer botão que envie, crie, publique ou apague algo, diz-me o
  que vais fazer e espera pela minha confirmação.
- Se uma página pedir login ou confirmação de identidade, pára e deixa-me tratar disso.
- No fim de cada parte, diz-me o que ficou feito e o que falta.

PARTE 1 – FAZER AGORA
1. No GitHub, cria um repositório novo, PRIVADO, chamado "carretos-avaliacoes", sem README,
   sem .gitignore e sem licença.
2. Passa para lá o código: o conteúdo da branch claude/google-reviews-auto-response-f5f1ad
   do repositório DavidCarreto/DavidCarretos deve ficar na branch "main" do repositório novo.
   Se não conseguires fazer isto, diz-me e eu peço à outra sessão.
3. No repositório novo, em Settings → Secrets and variables → Actions, cria o secret
   ANTHROPIC_API_KEY. Para isso, cria uma chave nova em https://console.anthropic.com
   (API Keys → Create Key, nome "carretos-avaliacoes", espaço de trabalho padrão,
   sem expiração) e cola-a diretamente no GitHub. Confirma em Settings → Billing que a
   conta Anthropic tem saldo.
4. Em github.com/settings/notifications, confirma que recebo emails de issues que me são
   atribuídos. É assim que chegam os alertas de avaliações de 1 a 3 estrelas.

PARTE 2 – SÓ DEPOIS DE A GOOGLE APROVAR O ACESSO
Pergunta-me primeiro se já recebi o email de aprovação. Se não recebi, pára aqui.
Usa sempre a conta Google que gere as 5 oficinas e o projeto "carretos-reviews".
1. Em APIs e serviços → Biblioteca, ativa: "My Business Account Management API",
   "My Business Business Information API" e "Google My Business API".
2. Ecrã de consentimento OAuth: tipo Externo, nome "Carretos Reviews", o meu email como
   suporte e contacto. Depois clica em "Publicar app" para ficar "Em produção".
   Se ficar em "Teste", a autorização expira ao fim de 7 dias.
3. Credenciais → Criar credenciais → ID de cliente OAuth → "Aplicação para computador",
   nome "carretos-avaliacoes". Guarda o Client ID e o Client secret diretamente como secrets
   GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no repositório carretos-avaliacoes.
4. Gerar o refresh token: no meu computador, corre
   python scripts/obter_refresh_token.py "CLIENT_ID" "CLIENT_SECRET"
   a partir do repositório carretos-avaliacoes. Abre o link que aparecer, eu faço o login
   com a conta gestora, e guarda o token diretamente como secret GOOGLE_REFRESH_TOKEN.
   Se não conseguires correr comandos no meu computador, explica-me como fazer.
5. No GitHub, em Actions → "Responder avaliações Google" → Run workflow, corre SEM marcar
   "Publicar". Mostra-me o relatório: as respostas propostas para avaliações reais e os
   alertas criados. NÃO ligues a publicação automática. Essa decisão é minha, depois de
   ler as respostas.
```
