from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Account


@dataclass
class PublishRequest:
    account: Account
    format: str                     # reel | video | image | carousel | text_image | text
    caption: str
    media: list[str] = field(default_factory=list)   # caminhos locais
    cover: str | None = None
    title: str = ""
    article: dict | None = None     # LinkedIn só texto + link: cartão do link (url, title, description, image_bytes)


@dataclass
class PublishResult:
    remote_id: str
    url: str | None = None
    note: str = ""
    status: str = ""                # vazio = "published"; "assist_sent" (telemóvel); "tiktok_draft" (rascunho no TikTok)


class Publisher:
    def publish(self, req: PublishRequest) -> PublishResult:  # pragma: no cover
        raise NotImplementedError


class PublishStepError(RuntimeError):
    """Falha num passo concreto da publicação (para mostrar onde falhou)."""

    def __init__(self, step: str, cause: Exception):
        self.step, self.cause = step, cause
        super().__init__(f"{step}: {type(cause).__name__}: {cause}" if not str(cause) else f"{step}: {cause}")
