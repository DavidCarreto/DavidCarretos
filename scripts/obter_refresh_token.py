"""Gera o GOOGLE_REFRESH_TOKEN (corre-se UMA vez, no teu computador).

Uso:
    python scripts/obter_refresh_token.py CLIENT_ID CLIENT_SECRET

1. Abre o link que aparece e entra com a conta Google que gere as 5 oficinas.
2. Aceita o acesso (se aparecer "A Google não validou esta app", clica em
   Avançadas -> Aceder; a app é tua e só tu a usas).
3. O token aparece no terminal. Guarda-o como secret GOOGLE_REFRESH_TOKEN no GitHub.
   Não o envies por chat nem email.
"""
import http.server
import json
import sys
import urllib.parse
import urllib.request

SCOPE = "https://www.googleapis.com/auth/business.manage"
PORTA = 8765
REDIRECT = f"http://localhost:{PORTA}"


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    client_id, client_secret = sys.argv[1], sys.argv[2]
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    })
    print("\nAbre este link no browser:\n\n" + url + "\n")

    codigo = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            codigo.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Pronto! Podes fechar esta janela e voltar ao terminal.</h2>".encode())

        def log_message(self, *a):
            pass

    with http.server.HTTPServer(("localhost", PORTA), Handler) as srv:
        while "code" not in codigo and "error" not in codigo:
            srv.handle_request()
    if "error" in codigo:
        sys.exit(f"Autorização recusada: {codigo['error']}")

    dados = urllib.parse.urlencode({
        "code": codigo["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": REDIRECT, "grant_type": "authorization_code",
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", dados) as r:
        token = json.load(r)
    if "refresh_token" not in token:
        sys.exit(f"Não veio refresh_token: {token}")
    print("\nGOOGLE_REFRESH_TOKEN =\n\n" + token["refresh_token"] + "\n")


if __name__ == "__main__":
    main()
