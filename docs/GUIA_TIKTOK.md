# TikTok no Carretos Studio: modo "rascunho na app TikTok"

A TikTok **não aprova o Direct Post** para ferramentas internas que publicam nas próprias contas. Por isso o
Carretos Studio **nunca publica em público no TikTok**: envia os conteúdos para os **rascunhos da app TikTok**
e o David revê e publica lá. Não é preciso pedir a auditoria do Direct Post.

| Conta | @ |
|---|---|
| TikTok pessoal | @davidcarretos |
| Carreto Clips | @clips.do.carreto |
| Carretos Group | @carretos_group |

## Como funciona
- **Vídeos**: vão para os rascunhos **sem legenda nem capa** (a TikTok não deixa enviá-las neste modo). No mesmo
  momento a legenda pronta vai por **email** (⚙ Configurar → "TikTok · email para onde vão as legendas") e pelo
  Telegram, e fica no dashboard com o botão **"📋 Copiar legenda"**. No telemóvel: abrir a notificação da TikTok
  → colar a legenda → escolher a capa → publicar.
- **Carrosséis de fotos**: vão para os rascunhos **já com título, legenda e capa**. Só falta publicar na app.
- No dashboard o post fica **"No TikTok: falta publicar na app"**.
- Se a TikTok recusar o rascunho (ex.: app ainda não aprovada), aparece o erro completo e o post segue em
  **modo assistido** (vai para o telemóvel).

## Configuração da app (developers.tiktok.com)
1. Produtos: **Login Kit** (Redirect URI `https://carretosstudio.duckdns.org/contas/tiktok/callback`) e
   **Content Posting API**. Scopes: `user.info.basic` e `video.upload`.
   O **Direct Post** e o scope `video.publish` já não são usados: pode retirá-los da app.
2. Sandbox: cada conta (pessoal, Carreto Clips, Carretos Group) tem de estar em **Target users**.
3. ⚙ Configurar: **TikTok · Client key**, **TikTok · Client secret** e **email para as legendas**.
4. Contas → em cada conta TikTok: abrir tiktok.com com essa conta → **"♪ Ligar esta conta"** → **Testar**.

## Fotos: verificar o domínio na TikTok (necessário para os carrosséis)
As fotos são enviadas a partir do servidor (endereço público). A TikTok só as aceita de um domínio verificado:
1. Na app → **URL properties** (ou "Manage URL properties") → **Add URL prefix**:
   `https://carretosstudio.duckdns.org/` → método **ficheiro**: a TikTok dá um ficheiro `.txt`.
2. ⚙ Configurar → **TikTok · nome do ficheiro de verificação** (ex.: `tiktokAbC123.txt`) e **conteúdo desse
   ficheiro** (`tiktok-developers-site-verification=…`) → Guardar.
3. Na TikTok → **Verify**. (Com o domínio verificado, pode também pôr **"TikTok · domínio verificado?" = sim**:
   os vídeos passam a ir pelo endereço público em vez de envio por blocos.)

## Testar
Contas → conta TikTok → **"Testar envio de rascunho"**: envia um vídeo curto e um carrossel de 2 fotos de TESTE
para os rascunhos dessa conta (nada é publicado). O resultado aparece em **Tarefas**. Depois apague os rascunhos
de teste na app TikTok.
