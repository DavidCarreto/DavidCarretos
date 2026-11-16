# Material de voz do David (inventário)

Os ficheiros de áudio ficam em `assets/voz/` (fora do Git, por serem dados pessoais). Este ficheiro
regista o que existe e para que serve.

| Ficheiro | Origem | Fala do David | Qualidade | Uso |
|---|---|---|---|---|
| `elevenlabs/voz_david_youtube_35min.m4a` | YouTube "David Carreto em 2020 e como nasceu a Carreto's" | 34,6 min (semelhança ≥0,80) | Uma só gravação, som constante | **Principal** para o clone profissional (ElevenLabs) |
| `elevenlabs/voz_david_telemovel_10min.m4a` | Gravação no telemóvel (16/11/2026): a história da Carretos desde 1998 | 10,3 min (8,5 min ≥0,80); semelhança 0,84 com o YouTube | Sem saturação; ruído de fundo moderado (−37 dB); outro microfone | **Complemento**: só se o clone com o YouTube não chegar |
| `dataset/*.wav` | Trechos verificados dos 45 vídeos partilhados | 17,5 min | Microfones e sítios variados | Reserva e referência de semelhança |
| YouTube "POLÉMICA!! Como ganhar +€'s…" | Drive | 14,5 min | Por confirmar | Reserva |
| YouTube "Pacotes de Revisão Carreto's" | Drive | 19,7 min (tem convidados e música) | Misturado | Reserva (pior) |

## ⛔ Regra sobre o CONTEÚDO das gravações
- As gravações servem **apenas para a voz**: timbre, ritmo, entoação e forma de falar do David.
- O que é dito nelas (datas, história, acontecimentos) **não é verdade confirmada** e **não pode ser usado**:
  não extrair factos, não acrescentar a `config/factos.yaml`, não usar em guiões nem legendas.
- Factos sobre o David só vêm de `config/factos.yaml`, confirmados por ele.

## ⛔ Regra sobre o USO dos áudios e vídeos de voz (pedido do David, 16/11/2026)
Aplica-se aos vídeos do YouTube (2020/2021, com datas desatualizadas) e à gravação do telemóvel:
- **Não usar** o áudio nem a voz destes ficheiros para criar vídeos, cortes, narrações ou vozes
  **sem autorização explícita do David**.
- É permitido **propor** um uso ("este trecho podia dar um vídeo sobre X"); só se avança depois de ele aprovar.
- O uso para treinar o clone profissional na ElevenLabs também precisa de aprovação dele, e o David
  faz esse passo por si.

Testes gratuitos (Chatterbox e Piper com conversão): o timbre não ficou parecido e os L e os R saíram fracos,
por isso estão abandonados. Solução escolhida: o clone profissional da ElevenLabs.
