"""Alertas de avaliações negativas (1-3 estrelas) como issues no GitHub.

Cada avaliação gera um único issue (identificado por um marcador escondido com o ID
da avaliação), atribuído ao dono do repositório para o GitHub enviar notificação por
email. Quando a avaliação é respondida no Google, o issue é fechado automaticamente.
"""
from __future__ import annotations

import os
import re

import requests

ETIQUETA = "avaliacao-negativa"
MARCADOR = re.compile(r"<!-- review:(\S+) -->")


class AlertasGitHub:
    def __init__(self, token: str, repo: str, dono: str | None, api: str = "https://api.github.com"):
        self.base = f"{api}/repos/{repo}"
        self.dono = dono
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        })

    @staticmethod
    def disponivel() -> bool:
        return bool(os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"))

    @classmethod
    def from_env(cls) -> "AlertasGitHub":
        return cls(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"],
                   os.environ.get("ALERTAS_ATRIBUIR_A") or os.environ.get("GITHUB_REPOSITORY_OWNER"),
                   os.environ.get("GITHUB_API_URL", "https://api.github.com"))

    def _req(self, method: str, path: str, **kw):
        r = self.session.request(method, f"{self.base}{path}", timeout=30, **kw)
        r.raise_for_status()
        return r.json() if r.content else None

    def _issues_existentes(self) -> dict[str, dict]:
        """review_id -> issue (abertos e fechados), para nunca alertar duas vezes."""
        out, pagina = {}, 1
        while True:
            lote = self._req("GET", "/issues", params={
                "labels": ETIQUETA, "state": "all", "per_page": 100, "page": pagina})
            for issue in lote:
                m = MARCADOR.search(issue.get("body") or "")
                if m:
                    out[m.group(1)] = issue
            if len(lote) < 100:
                return out
            pagina += 1

    def sincronizar(self, baixas: list[dict], pode_fechar: bool = True) -> tuple[int, int]:
        existentes = self._issues_existentes()
        criados = 0
        for b in baixas:
            if b["id"] in existentes:
                continue
            corpo = (
                f"**Oficina:** {b['oficina']}\n"
                f"**Classificação:** {'★' * b['estrelas']}{'☆' * (5 - b['estrelas'])} ({b['estrelas']}/5)\n"
                f"**Cliente:** {b['autor']}\n"
                f"**Data:** {b['data']}\n\n"
                f"> {(b['comentario'] or '(sem comentário escrito)').replace(chr(10), chr(10) + '> ')}\n\n"
                "Esta avaliação **não é respondida automaticamente**. Responde no Google: "
                "https://business.google.com/reviews\n\n"
                "_Este alerta fecha-se sozinho quando a avaliação tiver resposta._\n"
                f"<!-- review:{b['id']} -->"
            )
            dados = {"title": f"⚠️ {b['estrelas']}★ – {b['oficina']} – {b['autor']}",
                     "body": corpo, "labels": [ETIQUETA]}
            if self.dono:
                dados["assignees"] = [self.dono]
            self._req("POST", "/issues", json=dados)
            criados += 1

        fechados = 0
        if pode_fechar:  # só fecha se todas as oficinas foram lidas sem erros
            pendentes = {b["id"] for b in baixas}
            for rid, issue in existentes.items():
                if issue["state"] == "open" and rid not in pendentes:
                    self._req("POST", f"/issues/{issue['number']}/comments",
                              json={"body": "✅ A avaliação já tem resposta no Google. A fechar."})
                    self._req("PATCH", f"/issues/{issue['number']}",
                              json={"state": "closed", "state_reason": "completed"})
                    fechados += 1
        return criados, fechados
