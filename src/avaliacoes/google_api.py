"""Cliente mínimo para a Google Business Profile API (OAuth + avaliações)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
INFO_URL = "https://mybusinessbusinessinformation.googleapis.com/v1"
V4_URL = "https://mybusiness.googleapis.com/v4"
SCOPE = "https://www.googleapis.com/auth/business.manage"


class GoogleApiError(RuntimeError):
    pass


@dataclass
class Location:
    account: str      # "accounts/123"
    name: str         # "locations/456"
    title: str

    @property
    def v4_path(self) -> str:
        """Caminho usado pela API v4 de avaliações: accounts/123/locations/456."""
        return f"{self.account}/{self.name}"


def obter_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise GoogleApiError(f"Falha ao renovar token OAuth ({resp.status_code}): {resp.text}")
    return resp.json()["access_token"]


class GoogleBusinessClient:
    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {access_token}"

    @classmethod
    def from_env(cls) -> "GoogleBusinessClient":
        token = obter_access_token(
            os.environ["GOOGLE_CLIENT_ID"],
            os.environ["GOOGLE_CLIENT_SECRET"],
            os.environ["GOOGLE_REFRESH_TOKEN"],
        )
        return cls(token)

    def _request(self, method: str, url: str, **kwargs) -> dict:
        resp = self.session.request(method, url, timeout=60, **kwargs)
        if resp.status_code >= 400:
            raise GoogleApiError(f"{method} {url} -> {resp.status_code}: {resp.text[:500]}")
        return resp.json() if resp.content else {}

    def _paginate(self, url: str, key: str, params: dict | None = None) -> Iterator[dict]:
        params = dict(params or {})
        while True:
            data = self._request("GET", url, params=params)
            yield from data.get(key, [])
            token = data.get("nextPageToken")
            if not token:
                return
            params["pageToken"] = token

    def listar_contas(self) -> list[dict]:
        return list(self._paginate(ACCOUNTS_URL, "accounts", {"pageSize": 20}))

    def listar_locais(self) -> list[Location]:
        """Todas as fichas a que a conta tem acesso (sem duplicados entre contas/grupos)."""
        vistos: dict[str, Location] = {}
        for conta in self.listar_contas():
            url = f"{INFO_URL}/{conta['name']}/locations"
            params = {"readMask": "name,title", "pageSize": 100}
            for loc in self._paginate(url, "locations", params):
                if loc["name"] not in vistos:
                    vistos[loc["name"]] = Location(conta["name"], loc["name"], loc.get("title", ""))
        return list(vistos.values())

    def listar_avaliacoes(self, local: Location) -> Iterator[dict]:
        """Avaliações da mais recente para a mais antiga."""
        url = f"{V4_URL}/{local.v4_path}/reviews"
        yield from self._paginate(url, "reviews", {"pageSize": 50, "orderBy": "updateTime desc"})

    def responder(self, review_name: str, texto: str) -> dict:
        """review_name: accounts/X/locations/Y/reviews/Z (campo "name" da avaliação)."""
        return self._request("PUT", f"{V4_URL}/{review_name}/reply", json={"comment": texto})
