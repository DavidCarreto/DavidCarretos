# Ligar o Instagram

> **Atualizado:** a ligação faz-se agora no dashboard → **Contas → "Ligar com o Facebook"**,
> sem copiar tokens. Ver **docs/GUIA_META.md**. O texto abaixo fica só como referência.


Tempo: ~30 min, uma vez. Custo: 0 €.

1. **Conta profissional:** na app do Instagram → Definições → Tipo de conta → mudar para **Criador** (ou Empresa).
2. **Página do Facebook:** cria (ou usa) uma Página "David Carreto" e liga-a ao Instagram
   (Instagram → Editar perfil → Página).
3. **App de programador (Meta):** em developers.facebook.com → *Criar app* → tipo **Empresa** →
   adiciona o produto **Instagram** (API com início de sessão do Facebook).
4. **Permissões:** `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`,
   `pages_show_list`, `pages_read_engagement`. Para uso próprio (a tua conta) não é preciso revisão da Meta.
5. **Token:** no *Graph API Explorer* gera um token com essas permissões e troca-o por um de
   **longa duração** (60 dias). Copia também o **Instagram Business Account ID**.
6. Diz ao Claude "Instagram pronto": a chave é guardada por formulário seguro (nunca no chat) e o
   sistema testa a ligação, recolhe as métricas e passa a publicar o que aprovares.

Notas:
- O Instagram exige que as imagens/capas estejam num endereço público: o servidor trata disso.
- O token dura 60 dias; o sistema avisa antes de expirar.
