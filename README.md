# Respostas automáticas às avaliações Google – Carretos Group

Responde automaticamente às avaliações de **4 e 5 estrelas** no Google das 5 oficinas
(Almada, Cacém, Lisboa, Mafra e Santarém), **incluindo as antigas que ainda não têm resposta**.

As avaliações de **1 a 3 estrelas não são respondidas automaticamente**. Cada uma gera um
**alerta**: um *issue* no GitHub atribuído ao dono do repositório, que recebe email. O alerta
fecha-se sozinho quando a avaliação for respondida no Google.

## Como funciona

- Corre sozinho no **GitHub Actions**, de hora a hora entre as 7h e as 22h.
- Usa **uma única conta Google**, a que gere as 5 oficinas, através da Google Business Profile API.
- Encontra as fichas pelo nome; não é preciso configurar IDs.
- Ignora avaliações já respondidas, por isso nunca responde duas vezes.
- Por segurança, publica no máximo 25 respostas por execução. As avaliações antigas vão sendo
  respondidas ao longo das execuções seguintes (até cerca de 400 por dia).
- Os alertas são enviados mesmo em modo teste e nunca se repetem para a mesma avaliação.
  Para receber os emails, confirma em *github.com/settings/notifications* que tens o email ativo
  para "Issues" / "Assigned".
- **Modo teste por omissão:** gera as respostas e mostra-as no relatório sem publicar nada.

| Ficheiro | Para quê |
|---|---|
| `config/oficinas.yaml` | As 5 oficinas (ativar/desativar cada uma) |
| `config/respostas.yaml` | Textos das respostas, tom, assinatura, regras |
| `src/avaliacoes/` | Código |
| `scripts/obter_refresh_token.py` | Gera a autorização Google (uma vez) |
| `.github/workflows/responder-avaliacoes.yml` | Agendamento |

## Configuração (passo a passo)

### 1. Google Cloud e acesso à API
1. Com a **conta gestora**, cria um projeto em https://console.cloud.google.com, por exemplo `carretos-reviews`.
2. Pede acesso à API: https://support.google.com/business/contact/api_default
   ("Application for Basic API Access", com o número do projeto). Aguarda o email de aprovação.
3. Depois de aprovado, em *APIs e serviços → Biblioteca*, ativa:
   - My Business Account Management API
   - My Business Business Information API
   - Google My Business API
4. *APIs e serviços → Ecrã de consentimento OAuth*: tipo **Externo**, nome "Carretos Reviews",
   adiciona o teu email. Depois clica em **Publicar app** (estado "Em produção").
   ⚠️ Se a app ficar em "Teste", a autorização expira ao fim de 7 dias.
5. *Credenciais → Criar credenciais → ID de cliente OAuth → Aplicação para computador*.
   Fica com o **Client ID** e o **Client secret**.

### 2. Gerar a autorização (no teu computador, uma vez)
```bash
python scripts/obter_refresh_token.py "CLIENT_ID" "CLIENT_SECRET"
```
Entra com a conta gestora. O terminal mostra o *refresh token*.

### 3. Guardar os segredos no GitHub
No repositório: *Settings → Secrets and variables → Actions → New repository secret*:
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `ANTHROPIC_API_KEY` (respostas com IA; criar em https://console.anthropic.com → API Keys)

### 4. Testar e ligar
1. *Actions → Responder avaliações Google → Run workflow* (sem marcar "Publicar") e vê o relatório.
2. Quando estiveres satisfeito com as respostas, em *Settings → Secrets and variables → Actions →
   Variables* cria `PUBLICAR_AUTOMATICO` = `true`. A partir daí as execuções agendadas publicam.
   Para parar tudo, muda para `false`.

## Respostas: modelos fixos ou IA
Em `config/respostas.yaml`:
- `modo: ia` (ativo) usa o Claude para escrever uma resposta personalizada a cada avaliação,
  seguindo as regras de `estilo_ia`. Para não se repetir ao longo do tempo, a IA vê as 10
  respostas mais recentes da oficina e evita reutilizar frases e aberturas. Respostas com links,
  emails ou telefones são rejeitadas, e nesse caso, ou se a IA falhar, usa-se um modelo fixo.
  Custo estimado: cerca de 1 cêntimo por resposta.
- `modo: modelos` usa apenas textos fixos com várias variantes (gratuito).

## Correr localmente
```bash
pip install -r requirements.txt
export GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... GOOGLE_REFRESH_TOKEN=...
PYTHONPATH=src python -m avaliacoes.main --listar-locais   # confirma as fichas
PYTHONPATH=src python -m avaliacoes.main                   # modo teste
PYTHONPATH=src python -m avaliacoes.main --publicar        # publica
python -m unittest discover -s tests                       # testes
```
