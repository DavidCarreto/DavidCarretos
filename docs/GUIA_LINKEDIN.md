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
2. **Contas** → **in Ligar com o LinkedIn** → autorizar → **Testar** na conta pessoal.
   (Os tokens do LinkedIn duram ~60 dias: a página Contas mostra até quando; basta voltar a ligar.)

## 3. Página da empresa (Community Management API)
1. Na app, separador **Products** → **Community Management API** → **Request access** e preencher o
   formulário (empresa: Carretos Group; utilização: publicar e gerir as publicações da nossa própria página).
   Se o LinkedIn disser que esta API tem de estar numa app só para ela, crie uma 2.ª app igual (passos 1.1 a 1.5)
   só com este produto e diga ao Claude Code (o sistema passa a usar essa).
2. A aprovação pode demorar dias ou semanas. Até lá a página fica em **modo assistido** (os posts vão para o
   telemóvel, para publicar à mão).
3. Quando for aprovada: **⚙ Configurar → LinkedIn · Community Management API aprovada? → `sim`**, depois
   **Contas → Ligar com o LinkedIn** outra vez (passa a pedir também a página) → escolher a página Carretos
   Group → **Testar**.
