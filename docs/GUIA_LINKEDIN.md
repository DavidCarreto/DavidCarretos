# Ligar o LinkedIn ao Carretos Studio

Uma vez, ~20 minutos, **sem custos**. Depois liga-se no dashboard → **Contas → "Ligar com o LinkedIn"**.

| Conta | Como fica |
|---|---|
| LinkedIn pessoal (David Carreto) | **Publicação automática** (produto "Share on LinkedIn", aprovado logo) |
| Página da Carretos Group | **Modo assistido** até o LinkedIn aprovar a **Community Management API**; depois, automática |

## 1. Criar a app (linkedin.com/developers)
1. Entrar em **linkedin.com/developers/apps** com a sua conta → **Create app**.
2. Preencher:
   - **App name**: `Carretos Studio`
   - **LinkedIn Page**: escolher a página **Carretos Group** (tem de ser administrador da página)
   - **Privacy policy URL**: `https://carretosstudio.duckdns.org/privacidade`
   - **App logo**: o logótipo da Carretos Group (imagem quadrada)
   - aceitar os termos → **Create app**.
3. **Verificar a app com a página**: no separador **Settings** → **Verify** → gera um link; abra esse link
   (com a sua conta, que é administradora da página) e confirme.
4. Separador **Products** → pedir (ficam ativos logo):
   - **Sign In with LinkedIn using OpenID Connect**
   - **Share on LinkedIn**
5. Separador **Auth**:
   - em **Authorized redirect URLs for your app** acrescentar exatamente:
     `https://carretosstudio.duckdns.org/contas/linkedin/callback`
   - copiar o **Client ID** e o **Primary Client Secret**.

## 2. No Carretos Studio
1. **⚙ Configurar** → **LinkedIn · Client ID**, **LinkedIn · Client Secret** → Guardar.
   Em **LinkedIn · Community Management API aprovada?** escrever `não` (por agora).
2. **Contas** → **in Ligar o perfil pessoal** → autorizar → **Testar** na conta pessoal.
   (Os tokens do LinkedIn duram ~60 dias: a página Contas mostra até quando; basta voltar a ligar.)

## 3. Página da empresa: 2.ª app só para a Community Management API
O LinkedIn não deixa juntar a Community Management API à app do perfil (Share on LinkedIn + OpenID Connect).
Por isso a página usa uma **2.ª app**, só com esse produto:
1. linkedin.com/developers/apps → **Create app**: nome `Carretos Studio · Página`, página **Carretos Group**,
   a mesma política de privacidade e logótipo → verificar com a página (Settings → Verify).
2. **Products** → **Community Management API** → **Request access** e preencher o formulário (empresa:
   Carretos Group; utilização: publicar e gerir as publicações da nossa própria página). O LinkedIn pode
   demorar dias ou semanas a aprovar. Até lá a página fica em **modo assistido** (os posts vão para o telemóvel).
3. **Auth** → acrescentar o mesmo endereço de retorno:
   `https://carretosstudio.duckdns.org/contas/linkedin/callback` → copiar o Client ID e o Client Secret.
4. **⚙ Configurar** → **LinkedIn (2.ª app, página da empresa) · Client ID / Client Secret** → Guardar.
5. Quando o LinkedIn aprovar: **⚙ Configurar → Community Management API aprovada? → `sim`** →
   **Contas → "Ligar a página da empresa"** → autorizar → a página Carretos Group fica ligada → **Testar**.

As ligações do LinkedIn duram ~60 dias: o dashboard avisa 14 dias antes (e pelo Telegram, se estiver ativo).
