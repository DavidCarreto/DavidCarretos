# Identidade das imagens geradas (cores, logótipos e assinaturas)

Valores **base** de cada marca. A equipa pode mudá-los em ⚙ Configurar → "Logótipo e assinatura das imagens";
o botão "Repor a cor base" / "Repor o logótipo original" volta sempre a estes valores.

| Marca | Cor de destaque (aspas e traço) | Logótipo | Assinatura por baixo da frase |
|---|---|---|---|
| David Carreto (contas pessoais) | `#D4AF37` (dourado) | nenhum | "DAVID CARRETO" (uma vez) |
| Carretos Group | `#00A3E0` (azul) | CARRETO'S GROUP branco, do site (`carretos_social/assets/carretos-logo-branco.png`) | nenhuma |
| AURON | `#C5A316` (dourado do logótipo) | AURON dourado, original sem "By David Carreto" (`carretos_social/assets/auron-logo-dourado.png`) | nenhuma |

Outras cores base (não editáveis no dashboard; estão em `config/brand.yaml`):
- Fundo: pessoal `#000000`, Carretos Group `#0B0B0D`, AURON `#0B0B0C`.
- Brilho do fundo: pessoal dourado, Carretos Group azul, AURON cinzento `#E6E8EB` (para não se confundir com o
  preto e dourado das contas pessoais).

Regras:
- O nome aparece **uma só vez** em cada imagem.
- O nome do David só nas contas pessoais (nunca na Carretos Group nem na AURON).
- Versões extra da AURON em `carretos_social/assets/`: `auron-logo-branco.png` (fundos escuros) e
  `auron-logo-preto.png` (fundos claros).
