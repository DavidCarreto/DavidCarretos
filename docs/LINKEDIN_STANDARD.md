# LinkedIn · nível Standard da Community Management API (preparação, NÃO submetido)

Decisão do David (28/11/2026): preparar; submeter só quando ele disser.

## O que diz a documentação oficial ("Increasing Access", learn.microsoft.com)
- **Development** (o atual): 500 pedidos por app e **100 por membro** em 24 h; BATCH_GET não permitido;
  **avisos automáticos (webhooks) de social actions desligados**; a integração tem de ficar concluída e testada em
  12 meses desde a atribuição do acesso.
- **Standard**: "full-featured capability of the program — No restrictions" (sem estes limites).
- O LinkedIn revê os pedidos e escolhe os parceiros "at its discretion": pode recusar mesmo cumprindo os mínimos.
- O pedido faz-se no LinkedIn Developers → app da página ("Página do Carretos Studio") → Products →
  Community Management API → "Apply for Standard tier".

## O que ganhamos
- Ler os comentários sem o orçamento de 60 pedidos/dia (hoje: de hora a hora / 3 em 3 horas).
- Avisos automáticos de comentários (webhooks), sem ter de ir buscar: respostas mais rápidas.

## Texto de apoio para o formulário (inglês; adaptar às perguntas que aparecerem)
> Carretos Studio is the in-house social media tool of Carretos Group, a network of five Mercedes-Benz repair
> workshops in Portugal (Almada, Cacém, Lisboa, Mafra and Santarém). It is used only by our own team to manage our
> own LinkedIn Page (Carretos Group). We use the Community Management API to (1) publish posts to our Page after
> internal approval, (2) read comments and replies on our Page posts and show them to our team with a suggested
> answer, and (3) publish the reply as our Page only after a team member explicitly approves it in the dashboard.
> Nothing is published automatically. We also read follower counts and post statistics for internal reporting.
> In the Development tier the daily call limit forces us to check comments only every one to three hours; the
> Standard tier and social action webhooks would let us answer customers' questions about services and
> appointments much faster. We do not store profile data beyond the commenter URN and the comment text needed to
> handle each comment.

## Antes de submeter (checklist)
- Política de privacidade e termos públicos: https://carretosstudio.duckdns.org/privacidade e /termos.
- Conferir no portal a lista de perguntas e se pedem vídeo de demonstração (se pedirem, gravar: post da página →
  comentário → aparece no Carretos Studio → aprovar → resposta como página).
