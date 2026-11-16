# Formatos de publicação por rede (verificação "Formato para publicar")

Validados a 16/11/2026 nas páginas oficiais e na documentação das APIs (a publicação automática passa
pela API, que às vezes é mais restrita do que a app). Código: `carretos_social/media/formats.py`.
Ajustes sem mexer no código: `config/strategy.yaml` → `formatos`.

| Rede | Tipo | Recomendado | Proporção | Duração / outros | N.º |
|---|---|---|---|---|---|
| Instagram | Imagem | 1080×1350 (4:5) | 4:5 a 1,91:1 (a app aceita 3:4, a API só 4:5) | | 1 |
| Instagram | Carrossel | 1080×1350 (4:5) | idem; a 1.ª imagem define o corte das outras | | 2 a 10 (API permite 20: subir depois de testar) |
| Instagram | Reel | 1080×1920 (9:16) | API aceita 0,01:1 a 10:1; fora de 1:2–1,91:1 é só "⚠" | 3 s–15 min (rec. 90 s), 23–60 fps, largura ≤1920 px, ≤300 MB | |
| Facebook página | Imagem / várias fotos | 1080×1350 (4:5) | 4:5 a 1,91:1 | | 1 / 2 a 10 |
| Facebook página | Reel | 1080×1920 (9:16) | 1:2 a 1,91:1 | **3–90 s** (60 s se story), mín. 540×960, 24–60 fps. As 4 h são só para vídeo normal de página | |
| Facebook perfil pessoal | qualquer | como a página | | A API não publica em perfis (desde 2018): vai **sempre** para "Enviado p/ telemóvel" | |
| TikTok | Vídeo | 1080×1920 (9:16) | 1:2 a 1,91:1 | 3 s até ao máximo da conta (3/5/10 min, pedido à API `creator_info` antes de publicar), 360–4096 px por lado, 23–60 fps | |
| LinkedIn | Imagem / várias | 1200×1500 (4:5) | 3:4 a 1,91:1 **só recomendação** ("⚠", não bloqueia) | | 1 / 2 a 20 |
| LinkedIn | Vídeo | 1080×1350 (4:5) | 1:2,4 a 2,4:1 | 3 s–30 min, 75 KB–500 MB, MP4 | |
| YouTube | Short | 1080×1920 (9:16) | vertical ou quadrado | até 3 min (sem mínimo). Mais de 3 min ou horizontal sai como vídeo normal | |

Notas: a API do TikTok também aceita posts de fotos (até 35); não está ativo.

## Veredictos
- ✓ proporção a ±3% da recomendada e resolução ≥90% da recomendada.
- ⚠ aceite mas não ideal (proporção, resolução, duração acima da recomendada). Pode publicar.
- ✕ fora dos limites (proporção, tamanho, duração, fps, ficheiro, n.º de imagens, tipo errado).
  Bloqueia "Aprovar" e a publicação automática. O botão "Ajustar ao formato" resolve proporção,
  resolução e fps (fundo desfocado, nada é cortado); a duração tem de ser editada.
