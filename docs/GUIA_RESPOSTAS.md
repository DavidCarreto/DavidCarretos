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
