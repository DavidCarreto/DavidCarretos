# Servidor de produção

## Estado atual (não secreto)
| | |
|---|---|
| Fornecedor | Hetzner Cloud, projeto **redes-sociais**, servidor **redes-sociais** |
| Tipo | **CPX32**: 4 vCPU AMD, 8 GB RAM, 160 GB disco (o CX33 estava esgotado) |
| Localização / SO | Helsínquia (hel1) · Ubuntu 24.04 |
| Custo | €29,99/mês + €0,50 IPv4 (sem IVA) |
| IPv4 | 2.29.177.117 |
| Dashboard | https://2-29-177-117.sslip.io (certificado HTTPS automático do Caddy) |
| Aplicação | `/opt/carretos` (utilizador `carretos`, venv em `/opt/carretos/.venv`) |
| Serviços | `carretos-web` (dashboard, porta 8000 local) · `carretos-agendador` (publicação, métricas, lembretes) · `caddy` (HTTPS → 127.0.0.1:8000) |
| Instalação | cloud-init (`deploy/cloud-config.yaml`) → `deploy/setup_servidor.sh` |

### Problemas da 1.ª instalação (corrigidos no repositório)
1. `chatterbox-tts` puxava `pkuseg`, que falha a compilar no Ubuntu 24.04 e parava a instalação.
   Passou a extra opcional `voz-local`, que **não** se instala no servidor (a voz vem da ElevenLabs).
2. Faltava `itsdangerous`, e também `fastapi`, `uvicorn`, `python-multipart` e `jinja2`, nas dependências.
   Estão agora em `pyproject.toml`; `pip install -e .` traz tudo (testado num venv limpo).

## Atualizar o servidor
```bash
bash /opt/carretos/deploy/atualizar.sh
```
Faz `git pull` do ramo, `pip install -e .`, reinicia `carretos-web` e `carretos-agendador` e mostra o estado.
Pode correr como `carretos` (por SSH) ou como root (na consola); como root volta a correr-se como `carretos`.

`deploy/setup_servidor.sh` também pode voltar a correr-se (é idempotente): faz `git pull` se `/opt/carretos`
já existir, não duplica o `SETUP_CODE` e só mexe no Caddy se o endereço mudar.

## Consola da Hetzner com teclado português
A consola web assume um teclado americano. Na consola, escreve primeiro (uma vez por sessão):
```
loadkeys pt-latin1
```
Até isso, no teclado português: o **`-`** está na tecla **`'`** (à direita do 0); o **`/`** está na tecla **`-`**
(à direita do `.`); o espaço, as letras e os números estão no sítio normal. Depois de `loadkeys pt-latin1`,
as teclas passam a escrever o que mostram.

## Entrar por SSH (deixar de depender da consola)
### 1. Criar a chave no teu computador (Windows, PowerShell)
```powershell
ssh-keygen -t ed25519 -C "david-portatil"
```
Enter para aceitar o local proposto. Escolhe uma frase-passe (recomendado). São criados dois ficheiros em
`C:\Users\<tu>\.ssh\`: `id_ed25519` (**privada, nunca partilhar**) e `id_ed25519.pub` (**pública**).

Mostrar a pública, para a copiares:
```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

### 2. Pôr a chave pública no servidor
A consola não permite colar texto e a chave é longa. Por isso a chave pública passa pelo repositório
(não é secreta):
1. Envia a linha `ssh-ed25519 AAAA… david-portatil` ao Claude Code (ou cria o ficheiro
   `deploy/ssh_keys/david-portatil.pub` no GitHub). Fica guardada no repositório.
2. Na consola da Hetzner, como root:
   ```
   loadkeys pt-latin1
   bash /opt/carretos/deploy/atualizar.sh
   bash /opt/carretos/deploy/autorizar_ssh.sh
   ```
   (`autorizar_ssh.sh` só corre à mão, como root; autoriza as chaves de `deploy/ssh_keys/` para `root` e `carretos`.)

### 3. Entrar
```powershell
ssh carretos@2.29.177.117      # trabalho normal (atualizar, ver registos)
ssh root@2.29.177.117          # administração do sistema
```

### 4. (Recomendado, depois de confirmares que a chave funciona) desligar a entrada por palavra-passe
Por SSH, como root:
```bash
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\n' > /etc/ssh/sshd_config.d/99-so-chaves.conf
systemctl reload ssh
```
**Não feches** a sessão atual antes de testares, noutra janela, que ainda consegues entrar com a chave.

## Comandos úteis (por SSH como `carretos`)
```bash
sudo systemctl --no-pager status carretos-web carretos-agendador caddy   # estado
journalctl -u carretos-web -n 50 --no-pager                              # erros do dashboard
journalctl -u carretos-agendador -n 50 --no-pager                        # erros do agendador
cat /opt/carretos/ENDERECO_DASHBOARD.txt                                 # endereço do dashboard
```
