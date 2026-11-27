# Respostas automáticas a comentários e mensagens (Instagram e Páginas de Facebook)

O Carretos Studio responde sozinho, em poucas palavras e no tom da marca, e encaminha sempre para o **assistente
do WhatsApp** (preço, orçamento, serviços e marcação, 24 horas). Nunca inventa preços nem factos; spam não é
respondido; reclamações e urgências avisam o David pelo Telegram. Tudo fica no dashboard → **Mensagens**.

**Importante:** com a app da Meta em **modo de desenvolvimento**, a Meta só envia comentários e mensagens de quem
tem função na app (o David): serve para testar. Para responder ao público é preciso a **revisão da app** pela Meta
("Advanced Access") e a **verificação da empresa** (passo 4).

## 1. Permissões novas (Facebook Login for Business → Configuração)
Na app "Carretos Studio" (developers.facebook.com) → **Facebook Login for Business → Configurations** → editar a
configuração usada (ID 1165286902566069) e acrescentar:
`pages_manage_metadata`, `pages_manage_engagement`, `pages_read_user_content`, `pages_messaging`,
`instagram_manage_comments`, `instagram_manage_messages`.
Depois, no dashboard → Contas → **Ligar com o Facebook** outra vez (com "Editar acesso", tudo marcado).

## 2. Webhooks (app da Meta)
App → **Webhooks** (adicionar o produto se não existir):
- objeto **Page** → URL de retorno e token de verificação que aparecem em dashboard → Mensagens (fundo da página)
  → subscrever os campos **feed** e **messages**;
- objeto **Instagram** → o mesmo URL e token → campos **comments** e **messages**.

## 3. No Carretos Studio
1. Dashboard → **Mensagens** → em cada conta: **Ativar na Meta** (a Página passa a enviar os eventos).
2. **Testar resposta** (não envia nada) para ver o que a IA responderia.
3. Ligar **"Responder automaticamente"** (e, se quiser, **"+ mensagem privada nos comentários"**) e Guardar.
4. Instagram: na app do Instagram → Definições → Privacidade → Mensagens → **Ferramentas ligadas: permitir acesso
   às mensagens** (sem isto as mensagens privadas não chegam).
5. Teste com a sua conta: comente uma publicação e envie uma mensagem privada → a resposta aparece em segundos e
   fica em Mensagens.

## 4. Para responder ao público (revisão da Meta)
1. **Verificação da empresa** (Business Verification) no portefólio onde está a app.
2. App → **App Review → Permissions and Features**: pedir **Advanced Access** às permissões do passo 1 (a Meta
   pede uma descrição e um vídeo do ecrã a mostrar o uso: comentário → resposta com o link do WhatsApp).
3. Pôr a app em **Live** (modo ativo). A política de privacidade já existe em
   `https://carretosstudio.duckdns.org/privacidade`.

## Identificar quem comentou
- A resposta vai **sempre no fio do comentário** (Facebook: `POST /{comentário}/comments`; Instagram:
  `POST /{comentário}/replies`), para a pessoa ser notificada.
- **Instagram:** a resposta começa por **@username** de quem comentou.
- **Facebook:** a API deixa uma Página mencionar outras Páginas, mas não etiquetar pessoas: a resposta começa por
  **"Olá {primeiro nome}!"** (ou "Olá!" se a Meta não enviar o nome).
- A mensagem privada (se ligada) começa por "Olá {primeiro nome}!" / "Olá @username!".
- Spam e ofensas não têm resposta, logo nunca levam o nome.

## Regras automáticas
- Desligado por defeito em cada conta; quem aprova numa conta pode ligar/desligar.
- Uma resposta por comentário; nas mensagens privadas, uma resposta automática por pessoa em 24 h.
- Nunca responde à própria conta; ignora reenvios da Meta e mensagens "eco".
- Respostas públicas até ~250 carateres, sempre com o link do WhatsApp (exceto agradecimentos a elogios).
- Nas contas do David e da Carretos nunca aparece o nome AURON; nenhuma resposta sai com [PREENCHER].

## LinkedIn · página Carretos Group (comentários)

- O agendador lê os comentários dos posts da página dos últimos 30 dias de 10 em 10 minutos
  (⚙ Configurar → "LinkedIn · ler os comentários…") e responde **como página**, no fio do comentário.
- Mensagens → conta "Carretos Group (LinkedIn)": **Ligado** + modo **"Propor e eu aprovo"** (por omissão) ou
  **"Responder sozinho"**. Parcerias, reclamações e urgências esperam sempre pela aprovação; as candidaturas
  têm resposta fixa e saem logo.
- Só comentários depois de ligar. "Trazer os comentários já existentes para aprovar" traz os dos últimos 30 dias
  só como propostas.
- O LinkedIn não dá o nome de quem comentou (só um identificador), por isso a resposta não menciona a pessoa:
  fica por baixo do comentário dela.
- Perfil pessoal: fora (r_member_social só para parceiros do LinkedIn). Mensagens privadas: não se leem pela API.

## Categorias fixas (Instagram, Facebook e LinkedIn)

- **Candidatura** (espera pela aprovação, como tudo) → "Obrigado pelo interesse em juntar-se à Carretos Group! Envie o seu CV para rh@carretos.pt, com a
  função e a oficina que lhe interessam. Boa sorte!" (nunca pede dados no comentário; se o comentário tiver
  telefone/email, não o repete e avisa no Telegram).
- **Parceria** → proposta "Obrigado pelo contacto! Para propostas de parceria, envie-nos os detalhes para
  davidcarreto@carretos.pt, que respondemos com toda a atenção." **Sempre para aprovação.** Aviso no Telegram e
  email para a lista de ⚙ Configurar → "Respostas · avisos de parcerias por email".

## LinkedIn · avisos de mensagens privadas (perfil e página)

A API de mensagens do LinkedIn só está aberta a parceiros: o Carretos Studio **não lê nem responde** mensagens,
só avisa no Telegram a partir dos emails de aviso do LinkedIn.

1. Uma vez, como root (consola da Hetzner): `bash /opt/carretos/deploy/ativar_correio.sh` → cria o serviço
   `carretos-correio`, que recebe email na porta 25 **só** para um endereço secreto.
2. ⚙ Configurar → "LinkedIn · avisar no Telegram as mensagens privadas" = sim.
3. Mensagens → "Endereço para a regra do Hotmail" (ex.: `linkedin-xxxxxxxxxx@carretosstudio.duckdns.org`).
4. Hotmail → Regras: De contém `linkedin.com` **e** Assunto contém `mensagem` / `message` / `InMail` →
   Redirecionar para esse endereço.
5. Aviso: "💬 Nova mensagem no LinkedIn (perfil do David | página Carretos Group) de <nome>", o início da
   mensagem (se vier no email) e o link. Os emails não são guardados.

Alternativa (se a Microsoft não entregar no servidor): uma caixa dedicada lida por IMAP
(⚙ Configurar → "Caixa dedicada (alternativa) · …").

## Regra geral (desde 27/11/2026): tudo passa pelo David

- **Cada comentário novo** em todas as contas ligadas (LinkedIn Carretos Group, Instagram e Páginas de Facebook)
  envia um aviso ao Telegram: conta e rede, quem comentou, texto, categoria, resposta proposta, link da
  publicação e os botões ✓ Aprovar / ✎ Editar / ✕ Ignorar (abrem o dashboard). Spam também, como
  "spam (proposta: ignorar)". Comentários da própria conta não geram aviso.
- **Nada é publicado sem aprovação** (todas as contas em "Propor e eu aprovo" por omissão). Uma conta em
  "Responder sozinho" mostra um aviso em Mensagens a dizer que contraria esta regra.
- Cada aviso (enviado ou falhado) fica em ⚙ Configurar → Registos → "Avisos de comentários no Telegram".

## Facebook · comentários das Páginas (também sem webhooks)
Além dos avisos (webhooks) da Meta, o agendador vai buscar de 5 em 5 minutos (⚙ → FACEBOOK_COMMENTS_MINUTES) os
comentários recentes de cada Página ligada (posts dos últimos 30 dias). Só comentários depois de a leitura começar;
os da própria Página não contam; o mesmo comentário nunca é tratado duas vezes (mesmo id que o webhook).
