# Ligar o Facebook e o Instagram (Meta) ao Carretos Studio

Uma vez, ~20 minutos, **sem custos**. Depois, tudo se faz no dashboard → **Contas → "Ligar com o Facebook"**.

## O que se liga e o que não se liga
| Conta | Como fica |
|---|---|
| Instagram @davidcarretos, @carretoclips e o da Carretos Group | **Publicação automática** (têm de ser contas profissionais ligadas a uma Página) |
| Página de Facebook da Carretos Group | **Publicação automática** (imagem, várias fotos, Reel, texto) |
| AURON: Página «AURON» e Instagram @_auron_2026 | **Publicação automática** (estão no portefólio Meta **RibaMotor**) |
| Facebook pessoal (perfil) | **Modo assistido**: a Meta não deixa publicar em perfis por API; o post vai para o telemóvel |

## 1. Preparar as contas (na app do Instagram e no Facebook)
1. Cada Instagram tem de ser **profissional**: Instagram → Definições → Tipo de conta e ferramentas →
   **Mudar para conta profissional** (Criador ou Empresa).
2. **De preferência**, cada Instagram está **ligado a uma Página de Facebook** (cada Página só leva um Instagram).
   Os Instagrams **sem Página** que estejam num portefólio (ex.: @davidcarretos e @carretoclips no "Carreto's")
   também aparecem na ligação ("sem Página") e publicam com o token do utilizador, que dura ~60 dias (a página
   Contas mostra até quando; basta voltar a "Ligar com o Facebook"):
   Instagram → Editar perfil → Página → escolher/criar a Página.
   - @davidcarretos → Página "David Carreto" (criar uma Página pública, se ainda não houver)
   - @carretoclips → Página "Carreto Clips"
   - Instagram da Carretos Group → Página "Carretos Group"
3. Ser **administrador** de todas essas Páginas com a sua conta pessoal do Facebook.

## 2. Criar a app da Meta (developers.facebook.com)
1. Entrar em **developers.facebook.com** com a sua conta do Facebook → **As minhas apps → Criar app**.
2. Nome: `Carretos Studio`. Email de contacto: o seu.
3. Caso de utilização / tipo: escolher **Empresa** (Business) ou, se aparecer a lista de "casos de
   utilização", os que falam em **gerir Páginas** e **Instagram (API com início de sessão do Facebook)**.
4. Na app: **Definições → Básicas**:
   - **Domínios da app**: `carretosstudio.duckdns.org`
   - copiar o **ID da app** (App ID) e o **Segredo da app** (App Secret, carregar em "Mostrar").
5. Adicionar o produto **Início de sessão do Facebook** (Facebook Login, ou "Facebook Login for Business")
   → **Definições** → em **URIs de redirecionamento OAuth válidos** pôr exatamente:
   `https://carretosstudio.duckdns.org/contas/meta/callback`
   (o mesmo endereço aparece no dashboard, em Contas).
6. Se a app usar **Facebook Login for Business** e pedir uma **Configuração**: criar uma com o tipo de token
   "Token de acesso de utilizador" e estas permissões, e copiar o **ID da configuração**:
   `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `business_management`,
   `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`.
7. Deixar a app em **modo de desenvolvimento**: para as suas próprias Páginas e Instagrams não é preciso
   pedir revisão à Meta (é o administrador da app).

## 3. No Carretos Studio
1. **⚙ Configurar** → preencher **Meta · App ID**, **Meta · App Secret** (e o **Configuration ID**, só se
   houver) → Guardar.
2. **Contas** → **Ligar com o Facebook** → entrar e **marcar todas as Páginas e Instagrams** que quer ligar,
   **de todos os portefólios** (Carreto's e RibaMotor). Se já tinha autorizado antes só um portefólio, na
   janela do Facebook use **"Editar acesso"** e marque também as Páginas/Instagrams do outro.
3. De volta a Contas, confirmar a que conta corresponde cada Página/Instagram (o sistema já sugere) →
   **Guardar ligações** → **Testar** em cada uma.

Notas
- As chaves ficam no servidor (nunca aparecem no ecrã). As das Páginas não expiram; deixam de funcionar se
  mudar a palavra-passe do Facebook ou retirar o acesso à app → basta voltar a "Ligar com o Facebook".
- Imagens para o Instagram: o próprio servidor dá-lhes um endereço público temporário (`/publico/…`,
  apagado ao fim de 7 dias).
- Este sistema não usa nenhuma API Google nem responde a avaliações Google.
