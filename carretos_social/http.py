"""Cliente HTTP com tentativas automáticas e erros legíveis."""
from __future__ import annotations

import time

import requests


class ApiError(RuntimeError):
    pass


def request(method: str, url: str, *, retries: int = 3, timeout: int = 120, **kwargs) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:  # rede
            last_exc = exc
            time.sleep(2 ** attempt)
            continue
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
            time.sleep(int(resp.headers.get("retry-after", 2 ** (attempt + 1))))
            continue
        if resp.status_code >= 400:
            raise ApiError(f"{method} {url.split('?')[0]} -> {resp.status_code}: {resp.text[:4000]}")
        return resp
    raise ApiError(f"{method} {url.split('?')[0]} falhou: {last_exc}")
