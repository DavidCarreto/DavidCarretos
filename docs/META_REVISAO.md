# Meta · Verificação da Empresa e Revisão da App (preparação, NÃO submetido)

Objetivo: receber e responder (sempre com aprovação do David) a comentários e mensagens de **clientes reais**
no Instagram e nas Páginas de Facebook. Hoje a app está em **modo de desenvolvimento**: só chegam dados de quem
tem função na app.

Fontes (documentação oficial da Meta, lida a 27/11/2026): "Business Verification", "App Review",
"App Review Submission Guide", "Permissions Reference", "Webhooks for Pages".

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

## 2. Autorizações a pedir (Advanced Access) e justificações (inglês, prontas a colar)

Para respostas a comentários e mensagens:

**pages_show_list**
> Carretos Studio is the internal social media tool of Carretos Group (Mercedes-Benz repair workshops in Portugal). We use pages_show_list only to list the Facebook Pages our own team manages (Carretos Group, Carreto Clips and AURON) so the administrator can choose which Page to connect after Facebook Login. It is a dependency of pages_manage_metadata, pages_read_user_content, pages_manage_engagement and pages_messaging.

**pages_read_engagement**
> We read the posts published by our own Pages so the team can see, inside Carretos Studio, which post each customer comment belongs to (post text and link shown next to the comment) and confirm that a post was published correctly.

**pages_manage_metadata**
> We use pages_manage_metadata only to subscribe our own Pages to the "feed" and "messages" webhooks (the "Activate on Meta" button). Without it we would not be notified when a customer comments or sends a message, and customers would wait longer for an answer.

**pages_read_user_content**
> When a customer comments on one of our Page posts, Carretos Studio reads the comment (text, author name and time) and shows it to our team with a suggested reply. A human reviews every comment: nothing is answered automatically. We also use it to check that a comment still exists before sending an approved reply.

**pages_manage_engagement**
> After a team member approves (or edits and approves) the suggested reply, Carretos Studio publishes that reply as a comment from our Page in the customer's comment thread. Replies are never published without explicit human approval in the dashboard.

**pages_messaging**
> Customers send our Pages questions about service prices, quotes and appointments through Messenger. Carretos Studio shows each message to our team with a suggested answer; after a team member approves it, the answer is sent to the customer (customer-initiated conversations only, within the standard messaging window). We never send unsolicited messages.

**instagram_basic**
> We read the username and ID of our own Instagram professional accounts (@carretos_group, @carretoclips, @_auron_2026, linked to our Pages) to identify which account each comment or message belongs to, and to avoid answering our own accounts.

**instagram_manage_comments**
> Carretos Studio reads new comments on posts of our own Instagram professional accounts and shows them to our team with a suggested reply. After a team member approves it, the reply is published in the comment thread from our account. Nothing is published without human approval.

**instagram_manage_messages**
> Customers send Instagram Direct messages to our business accounts asking about prices, quotes and appointments. Carretos Studio shows each message with a suggested answer and sends it only after a team member approves it, so the team can manage the Instagram inbox in one place.

Também necessárias para a publicação continuar a funcionar em Live (já usadas hoje):
**pages_manage_posts**, **instagram_content_publish**, **instagram_manage_insights**, **business_management**
(as nossas Páginas estão em dois portefólios: Carreto's e RibaMotor). Cada uma precisa da sua descrição e gravação.

## 3. Guião das gravações de ecrã
Regras da Meta: interface em inglês se possível (ou legendas a explicar), 1080p ou mais, sem áudio (não é ouvido),
mostrar o login a dar a autorização e o uso de cada autorização. Uma gravação por autorização (pode ser a mesma
sequência cortada). A Meta vai seguir as gravações para testar: é preciso dar-lhe acesso ao dashboard.

Sequência (com legendas em inglês):
1. **Login e autorizações**: Carretos Studio → Accounts → "Connect with Facebook" → janela da Meta → escolher as
   Páginas/Instagrams → "Continue" mostrando a lista de autorizações. (todas)
2. **Ativar webhooks**: Messages → "Activate on Meta" numa Página → mensagem de sucesso. (pages_manage_metadata)
3. **Comentário de cliente no Facebook**: noutro separador, uma conta de teste comenta num post da Página →
   no Carretos Studio aparece o comentário com o texto, o autor, o post e a resposta proposta, estado
   "awaiting approval". Legenda: "Nothing is published without approval". (pages_read_user_content, pages_read_engagement)
4. **Aprovar e publicar**: abrir o comentário → editar o texto → "Approve and send" → no Facebook aparece a
   resposta da Página no fio. (pages_manage_engagement)
5. **Mensagem no Messenger**: a conta de teste envia mensagem à Página → aparece no Carretos Studio com proposta
   → aprovar → mostrar o Messenger da conta de teste a receber a resposta. (pages_messaging; a Meta pede que se veja
   a mensagem a ser enviada pela app e recebida no cliente Messenger)
6. **Instagram**: o mesmo para um comentário (aprovar → resposta no fio no Instagram) e para uma mensagem Direct
   (aprovar → mensagem recebida na app Instagram). (instagram_manage_comments, instagram_manage_messages, instagram_basic)
7. **Ignorar**: mostrar "Ignore" num comentário (nada é publicado) e o aviso no Telegram com os botões.
8. (publicação) criar e aprovar um post → publicado na Página/Instagram; ver métricas.

Antes de gravar: mudar o dashboard para inglês ou pôr legendas; criar no Carretos Studio um utilizador só para a
revisão (ex.: "meta-review", com acesso a uma Página de teste), para indicar no campo "how we can access your app".

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
