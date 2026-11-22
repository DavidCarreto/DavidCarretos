# Ligar o TikTok ao Carretos Studio

Uma vez, ~30 minutos, **sem custos**. Depois liga-se cada conta no dashboard → **Contas → "Ligar esta conta"**.

**Importante:** enquanto a TikTok não **auditar** a app, a API só deixa publicar em **privado** (só o dono vê).
Até lá, os posts públicos seguem em **modo assistido** (vão para o telemóvel, para publicar à mão).

## 1. Criar a app (developers.tiktok.com)
1. Entrar em **developers.tiktok.com** (com a conta TikTok ou um email) → **Manage apps → Connect an app**.
2. Preencher em **App details**:
   - **App name**: `Carretos Studio` · ícone (logótipo) · categoria (ex.: Business / Productivity)
   - **Description**: "Ferramenta interna da Carretos Group para publicar os nossos próprios vídeos."
   - **Terms of Service URL**: `https://carretosstudio.duckdns.org/termos`
   - **Privacy Policy URL**: `https://carretosstudio.duckdns.org/privacidade`
   - **Platforms**: Web · Website URL: `https://carretosstudio.duckdns.org`
3. **Add products**:
   - **Login Kit** → **Redirect URI**: `https://carretosstudio.duckdns.org/contas/tiktok/callback`
   - **Content Posting API** → ativar **Direct Post**
4. **Scopes**: `user.info.basic`, `video.publish`, `video.upload`.
5. Para testar já, sem esperar pela auditoria: usar o modo **Sandbox** e, em **Target users / Sandbox users**,
   acrescentar as 3 contas: pessoal, Carreto Clips e Carretos Group.
6. Copiar o **Client key** e o **Client secret** (separador Credentials).

## 2. No Carretos Studio
1. **⚙ Configurar** → **TikTok · Client key**, **TikTok · Client secret** → Guardar.
   Em **TikTok · app já auditada?** escrever `não` (por agora).
2. Para **cada** conta (pessoal, Carreto Clips, Carretos Group):
   - abrir **tiktok.com** no mesmo browser e **entrar com essa conta** (o TikTok autoriza a conta que estiver aberta);
   - no dashboard → **Contas** → nessa conta → **♪ Ligar esta conta** → autorizar → **Testar**.
   - para a conta seguinte: sair do TikTok, entrar com a outra conta e repetir.
3. O token da TikTok dura 24 horas: o sistema renova-o sozinho (o de renovação dura ~1 ano).

## 3. Auditoria (para publicar em público)
1. Na app → **Content Posting API** → **Submit for review/audit**: a TikTok pede uma descrição e um vídeo curto
   a mostrar como a app é usada (pode gravar o ecrã do Carretos Studio a aprovar e publicar um vídeo).
2. Quando for aprovada: **⚙ Configurar → TikTok · app já auditada? → `sim`**. A partir daí as contas ligadas
   publicam sozinhas em público.
