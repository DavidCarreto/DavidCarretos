# Meta · Verificação da Empresa e Revisão da App (preparação, NÃO submetido)

Objetivo: receber e responder (sempre com aprovação do David) a comentários e mensagens de **clientes reais**
no Instagram e nas Páginas de Facebook. Hoje a app está em **modo de desenvolvimento**: só chegam dados de quem
tem função na app.

Fontes (documentação oficial da Meta, lida a 27/11/2026): "Business Verification", "App Review",
"App Review Submission Guide", "Permissions Reference", "Webhooks for Pages".

> **Ponto de situação (28/11/2026):** ao carregar em "Adicionar à revisão da app", a Meta exige que a empresa passe a
> **Fornecedor de Tecnologia** (decisão irreversível). O David decidiu NÃO o fazer: a revisão (Advanced Access) fica
> parada. Alternativa a testar: pôr a app em Live com Standard Access (reversível) e testar com uma conta sem função
> na app (ver o prompt "Teste Live" na conversa de 28/11). Os vídeos e textos ficam guardados para o caso de se
> retomar a revisão.

## Estado (28/11/2026)
- ✓ Definições básicas na app: política de privacidade, termos, URL de instruções de eliminação de dados, ícone
  1024×1024, categoria, email de contacto e encarregado da proteção de dados (feito pelo Claude no Chrome, autorizado).
- ✓ Callback de eliminação de dados: **não é obrigatório** (a Meta exige que a política de privacidade explique como
  pedir a eliminação — feito; o callback é opcional: "apps can implement").
- ✓ **Verificação da Empresa feita**: "ANTÓNIO DAVID GROU CARRETO, UNIPESSOAL, LDA", verificada a 17/08/2026,
  portefólio "Carreto's" (id 959299140915335). Falta só a **Revisão da App (Advanced Access)**.
- Diagnóstico (dashboard → Mensagens → "Diagnóstico da Meta"): webhooks Page (feed, messages) e Instagram
  (comments, messages) subscritos; app instalada em todas as Páginas.

## O que ainda falta preparar (por ordem)
1. ✓ **Política de privacidade atualizada** (aprovada pelo David a 28/11/2026, PT + EN, guarda máx. 12 meses com
   limpeza automática diária): https://carretosstudio.duckdns.org/privacidade
2. **Instruções de eliminação de dados** (App Dashboard → Settings → Basic → "Data deletion instructions URL"):
   https://carretosstudio.duckdns.org/privacidade#data-deletion
3. **Ícone da app 1024×1024** sem marcas da Meta (Settings → Basic → App icon) — confirmar se já existe.
4. **1 chamada com sucesso por autorização nos últimos 30 dias** (senão "Request advanced access" fica cinzento;
   o registo aparece até 2 dias depois). Já houve leituras e subscrições; FALTAM envios reais:
   - `pages_manage_engagement`: aprovar 1 resposta a um comentário de teste numa Página de Facebook;
   - `instagram_manage_comments`: aprovar 1 resposta a um comentário de teste no Instagram;
   - `pages_messaging` e `instagram_manage_messages`: aprovar 1 resposta a uma mensagem privada de teste (Messenger
     e Instagram Direct), vinda de uma conta com função na app.
   (Feito pelo David, no dashboard, com conteúdo de teste; aproveita-se para gravar os vídeos.)
5. **Acesso para os revisores**: criar no Carretos Studio um utilizador "meta-review" (Equipa → convidar) com acesso
   só a uma Página/Instagram de teste, e escrever no formulário como entrar (URL + utilizador; a palavra-passe vai no
   campo próprio do formulário, nunca em emails ou nesta documentação).
6. **Vídeos**: interface em português → pôr legendas em inglês (ou mudar os textos para inglês durante a gravação).
7. **Perguntas de tratamento de dados** (aparecem no formulário depois da verificação): respostas sugeridas na secção 6.
8. Só depois de aprovado: passar a app para **Live** (antes disso, a publicação e as respostas deixariam de funcionar).

## 0. O que a Meta diz (resumo)
- **Advanced Access exige Verificação da Empresa** (desde 1/2/2023). Sem ela, utilizadores de outras empresas não
  conseguem dar as autorizações e as funcionalidades ficam inativas.
- A Revisão da App é obrigatória se a app for usada por quem **não tem função** na app.
- Para cada autorização pedida é preciso: **1 chamada à API com sucesso nos últimos 30 dias** (senão o botão
  "Request advanced access" fica cinzento; o registo da chamada aparece até 2 dias depois), uma **descrição própria**
  (a Meta pede para não copiar e colar entre autorizações) e uma **gravação de ecrã**.
- Decisão: "você deve receber uma decisão dentro de uma semana" (Submission Guide).
- Limites: até 3 submissões em curso e 15 (programador) / 30 (portefólio) em 30 dias.
- **Só passar a app para "Live" depois de aprovada.** Em Live, só funcionam as autorizações aprovadas — para
  TODOS, incluindo o David. Por isso é preciso pedir também as autorizações de publicação e métricas que o
  Carretos Studio já usa, senão a publicação no Instagram/Facebook deixa de funcionar.

## 1. Verificação da Empresa (Carretos Group)
Passos (documentação "Business Verification"):
1. App Dashboard → **Settings → Basic → Verification → Start Verification** e ligar a app ao portefólio da
   Carreto's / Carretos Group (quem tem função de administrador na app pode ligá-la).
2. A verificação em si faz-se no **Gestor de Negócios (Business Manager)**, por um **administrador do portefólio**:
   "Start Business Verification".
3. Documentos: a Meta remete para a página de ajuda "About Business Verification" do Business Help Center, que
   **não consegui abrir daqui**. O que costuma ser pedido (confirmar nessa página antes de preparar):
   - documento oficial da empresa com nome e morada (ex.: certidão permanente do registo comercial);
   - documento com o NIF / morada da empresa (ex.: fatura de serviços em nome da empresa);
   - confirmação de contacto: email do **domínio carretos.pt** (ex.: davidcarreto@carretos.pt), telefone ou
     verificação do domínio carretos.pt (registo DNS ou ficheiro no site).
   - O nome legal e a morada têm de coincidir exatamente com os documentos.
4. Verificar que a app tem: ícone 1024×1024 **sem marcas da Meta**, URL da Política de Privacidade
   (https://carretosstudio.duckdns.org/privacidade), categoria certa e email de contacto acessível.

## 2. Autorizações (pedidas hoje no "Ligar com o Facebook": carretos_social/meta_connect.py → SCOPES)

| Autorização | Para que serve no Carretos Studio | Onde se vê | Obrigatória? |
|---|---|---|---|
| pages_show_list | listar as Páginas que gerimos ao ligar (/me/accounts) | Contas → "Ligar com o Facebook" | Sim (dependência de todas) |
| business_management | Páginas dos portefólios (Carreto's e RibaMotor/AURON) que não vêm em /me/accounts | Contas | Sim (AURON está noutro portefólio) |
| pages_read_engagement | token da Página e leitura das nossas publicações (para saber a que post é cada comentário) | Mensagens (link "Publicação") | Sim |
| pages_manage_metadata | instalar a app na Página e subscrever os webhooks feed/messages | Mensagens → "Ativar na Meta" e diagnóstico | Sim |
| pages_read_user_content | ler os comentários dos clientes nas Páginas (webhook e leitura de 5 em 5 min) e confirmar se ainda existem | Mensagens | Sim |
| pages_manage_engagement | publicar a resposta aprovada como Página no fio do comentário | Mensagens → "Aprovar e enviar" | Sim |
| pages_messaging | responder às mensagens do Messenger (depois de aprovadas) e ver se já houve resposta | Mensagens | Sim (para mensagens) |
| instagram_basic | identificar as nossas contas Instagram (id, @) | Contas | Sim |
| instagram_manage_comments | ler os comentários no Instagram e publicar a resposta aprovada no fio | Mensagens | Sim |
| instagram_manage_messages | ler e responder às mensagens Direct (depois de aprovadas) | Mensagens | Sim (para mensagens) |
| pages_manage_posts | publicar nas Páginas (fotos, vídeos, texto) depois de aprovado | Calendário / publicação | Sim, para a publicação continuar a funcionar em Live |
| instagram_content_publish | publicar no Instagram depois de aprovado | Calendário / publicação | Sim, idem |
| instagram_manage_insights | estatísticas das nossas publicações no Instagram | Painel / métricas | Sim, idem (pode sair se o David abdicar das métricas do Instagram) |

Não usadas (não pedir): read_insights, pages_manage_ads, ads_management, leads_retrieval, instagram_shopping_*,
publish_video, user_* e quaisquer outras.

## 2b. Textos para o formulário ("How will your app use this permission?") — inglês, um por autorização
(Descrição geral, para o campo da app:)
> Carretos Studio is the internal social media tool of Carretos Group, a network of five Mercedes-Benz repair workshops in Portugal. It is used only by our own team to manage our own Facebook Pages and Instagram professional accounts (Carretos Group, Carreto Clips and AURON). It publishes our posts after internal approval and helps the team answer customer comments and messages: for each new comment or message the AI suggests a reply, and the reply is only sent after a team member explicitly approves it in the dashboard (or opens it from a Telegram notification and approves it there in the dashboard). Nothing is ever published or sent without human approval.

**pages_show_list** — After Facebook Login (Accounts → "Connect with Facebook") we list the Pages the administrator manages so they can choose which of our own Pages to connect. Reviewer: open Accounts, click "Connect with Facebook", grant access and see the Pages listed. Required as a dependency of the Page permissions below.

**business_management** — Some of our Pages belong to our business portfolios (e.g. AURON in a second portfolio) and are not returned by /me/accounts. We read the Pages owned by or shared with our portfolios to connect them. Reviewer: after connecting, the Accounts page shows the Pages from both portfolios.

**pages_read_engagement** — We read the posts published by our own Pages so that each customer comment shown in Carretos Studio is linked to the post it belongs to (post link next to the comment). Reviewer: open Messages; each comment has a "Publication" link to the Page post.

**pages_manage_metadata** — Used only to install our app on our Pages and subscribe them to the "feed" and "messages" webhooks ("Activate on Meta" button), so new comments and messages reach the team immediately. Reviewer: Messages → "Activate on Meta" on a Page shows the success message; the diagnostic shows feed and messages subscribed.

**pages_read_user_content** — We read comments left by people on our Page posts (text, name, time) and show them to the team in Messages with a suggested reply; before sending an approved reply we check that the comment still exists. Reviewer: comment on a Page post with a test account; within minutes it appears in Messages as "awaiting approval".

**pages_manage_engagement** — After a team member reviews (and optionally edits) the suggested reply and clicks "Approve and send", we publish it as a comment from our Page in the customer's thread. Reviewer: open the comment in Messages, click "Approve and send", confirm, and see the Page reply under the comment on Facebook.

**pages_messaging** — Customers ask our Pages about prices, quotes and appointments through Messenger. Carretos Studio shows each message with a suggested answer and sends it only after a team member approves it (customer-initiated conversations only, within the standard messaging window). Reviewer: send a Messenger message to the Page from a test account, approve the suggested answer in Messages and see it arrive in Messenger.

**instagram_basic** — We read the ID and username of our own Instagram professional accounts (linked to our Pages) to know which account each comment or message belongs to and to avoid replying to our own accounts. Reviewer: Accounts shows the connected Instagram accounts with their @username.

**instagram_manage_comments** — We receive new comments on posts of our Instagram professional accounts, show them in Messages with a suggested reply, and publish the reply in the comment thread from our account only after a team member approves it. Reviewer: comment on one of our Instagram posts from a test account, approve the suggestion in Messages and see the reply on Instagram.

**instagram_manage_messages** — Customers send Instagram Direct messages to our business accounts. Carretos Studio shows each message with a suggested answer and sends it only after approval, so the team manages the Instagram inbox in one place. Reviewer: send a Direct message to our account, approve the answer in Messages and see it arrive in the Instagram inbox.

**pages_manage_posts** — The team prepares posts in Carretos Studio; after a person approves a post and its date, Carretos Studio publishes it to our Facebook Page (photo, video/Reel or text). Reviewer: open an approved post in the calendar and see it published on the Page at the scheduled time.

**instagram_content_publish** — Same as above for our Instagram professional accounts: approved posts (image, carousel or Reel) are published at the scheduled time. Reviewer: an approved post appears on the Instagram account.

**instagram_manage_insights** — We read the statistics of our own Instagram posts (reach, views, likes, comments, saves) to plan content and choose the best times to post. Reviewer: the dashboard metrics show the statistics of our recent Instagram posts.

## 2c. Instruções de teste para o revisor (campo "How to access your app")
> URL: https://carretosstudio.duckdns.org — log in with the reviewer user provided in the credentials field. The reviewer user has access only to the test account(s) listed there. Messages (top menu) shows comments and messages awaiting approval; open one, edit if needed, click "Approve and send" and confirm. Accounts shows the connected Pages and Instagram accounts and the "Connect with Facebook" button. Nothing is ever sent without clicking "Approve and send". Privacy policy and data deletion: https://carretosstudio.duckdns.org/privacidade (English section and #data-deletion).
(O que é preciso criar: um utilizador "meta-review" no Carretos Studio, com acesso só à conta escolhida pelo David; a palavra-passe vai só no campo de credenciais do formulário.)

## 3. Vídeos prontos (28/11/2026)
Os 10 vídeos `01_ligacao.mp4` … `10_privacidade.mp4` (MP4 1080p, legendas em inglês gravadas no vídeo, a partir
dos GIFs gravados pelo Claude no Chrome) estão na pasta "meta-review" do Google Drive. As legendas usadas estão em
`docs/meta/*.srt` (com os tempos finais).

## 3a. Guião das gravações (uma por autorização; pode ser a mesma sequência cortada)
Preparação: legendas em inglês (o dashboard está em português); Mensagens filtrado para a conta de teste e o dia
da gravação (Mensagens → "Mostrar: <conta> desde <data>") para não aparecerem comentários de clientes reais;
1080p; sem áudio; cursor grande.
1. **Ligação** (pages_show_list, business_management, instagram_basic): Contas → "Ligar com o Facebook" → janela da
   Meta → escolher as Páginas e Instagrams → ver a lista de autorizações → voltar ao Carretos Studio com as contas ligadas.
2. **Webhooks** (pages_manage_metadata): Mensagens → "Ativar na Meta" numa Página → mensagem de sucesso → diagnóstico com feed e messages.
3. **Comentário no Facebook** (pages_read_user_content, pages_read_engagement): a conta de teste comenta num post →
   aparece em Mensagens "por responder" com o texto, o autor, o link da publicação e a proposta. Legenda: "Nothing is published without approval".
4. **Aprovar e publicar** (pages_manage_engagement): abrir o comentário → editar → "Aprovar e enviar" → confirmar →
   no Facebook aparece a resposta da Página no fio.
5. **Messenger** (pages_messaging): a conta de teste envia mensagem à Página → aparece com proposta → aprovar → mostrar o Messenger da conta de teste a receber.
6. **Instagram** (instagram_manage_comments, instagram_manage_messages): o mesmo para um comentário e para uma mensagem Direct.
7. **Ignorar**: "Ignorar" num comentário (nada é publicado; o comentário fica sem resposta). O aviso do Telegram não
   entrou no vídeo (não é uma autorização da Meta).
8. **Publicação** (pages_manage_posts, instagram_content_publish): um post aprovado sai na Página e no Instagram.
9. **Métricas** (instagram_manage_insights): painel com as estatísticas das publicações do Instagram.
10. **Eliminação de dados**: abrir /privacidade#data-deletion.

O que o David faz pessoalmente: gravar o ecrã; comentar e enviar mensagens a partir de uma conta de teste (com função
na app, ex.: uma conta pessoal secundária) e aprovar as respostas; escolher a conta usada nos vídeos e para o revisor.

## 4. Prazos e motivos habituais de recusa
- Decisão da revisão: **até cerca de uma semana** (Submission Guide). A página da Verificação da Empresa **não
  indica prazo**.
- Recusas que a própria Meta indica:
  - não conseguirem aceder à app para testar (recusa de toda a submissão);
  - autorização sem gravação de ecrã, ou gravação que não mostra o login e o uso;
  - uso que não corresponde ao "Allowed Usage" da autorização;
  - descrições copiadas entre autorizações;
  - ícone com marcas da Meta ou Política de Privacidade em falta;
  - pedir autorizações que a app não usa;
  - mudar definições da app depois de submeter (pode obrigar a nova revisão).


## 5. Política de privacidade (APROVADA pelo David a 28/11/2026 e publicada em /privacidade)

**PT**
1. O Carretos Studio é a ferramenta interna da Carretos Group (ANTÓNIO DAVID GROU CARRETO, UNIPESSOAL, LDA) para criar,
   agendar e publicar conteúdos nas suas próprias contas de redes sociais e para gerir os comentários e as mensagens
   que essas contas recebem.
2. Que dados tratamos: quando alguém comenta ou envia uma mensagem a uma conta nossa (Facebook, Instagram, LinkedIn),
   recebemos o texto, o nome público ou nome de utilizador, o identificador da conta e a data. Usamos estes dados só
   para mostrar o comentário/mensagem à nossa equipa e responder (cada resposta é aprovada por uma pessoa). Não os
   vendemos, não os partilhamos com terceiros e não os usamos para publicidade.
3. As autorizações das redes sociais (chaves de acesso) ficam guardadas só no nosso servidor e não são partilhadas.
4. Guardamos os comentários e mensagens enquanto forem úteis para o atendimento e no máximo 12 meses.
5. Eliminação de dados: pode pedir a eliminação dos seus dados (comentários/mensagens) enviando um email para
   davidcarreto@carretos.pt com o assunto "Eliminar dados" e a conta/rede em causa; apagamos no prazo de 30 dias e
   confirmamos por email. Também pode apagar o seu comentário na própria rede social.
6. Contacto: davidcarreto@carretos.pt · WhatsApp 211 45 46 46.

**EN** (for the reviewers)
1. Carretos Studio is the internal tool of Carretos Group (ANTÓNIO DAVID GROU CARRETO, UNIPESSOAL, LDA) to create,
   schedule and publish content on its own social media accounts and to manage the comments and messages those
   accounts receive.
2. Data we process: when someone comments on or messages one of our accounts (Facebook, Instagram, LinkedIn), we
   receive the text, the public name or username, the account ID and the date. We use this data only to show the
   comment/message to our team and to reply (every reply is approved by a person). We do not sell or share it with
   third parties and do not use it for advertising.
3. Social network access tokens are stored only on our server and are never shared.
4. We keep comments and messages while useful for customer support, for a maximum of 12 months.
5. Data deletion: you can request deletion of your data by emailing davidcarreto@carretos.pt with the subject
   "Delete my data" and the account/network concerned; we delete it within 30 days and confirm by email. You can also
   delete your comment on the social network itself.
6. Contact: davidcarreto@carretos.pt · WhatsApp +351 211 45 46 46.

(Prazo de 12 meses aprovado; o agendador apaga uma vez por dia os comentários e mensagens com mais de 12 meses.)

## 6. Respostas sugeridas às perguntas de tratamento de dados (confirmar no formulário)
- Data processors / service providers with access to Platform Data: none besides our own server host (Hetzner, EU).
- Responsible entity: ANTÓNIO DAVID GROU CARRETO, UNIPESSOAL, LDA (Portugal).
- Requests from public authorities in the last 12 months: none.
- Policies for handling such requests: we only disclose data when legally required, after review by the company owner.
