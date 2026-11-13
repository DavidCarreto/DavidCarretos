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


@dataclass
class PublishResult:
    remote_id: str
    url: str | None = None
    note: str = ""


class Publisher:
    def publish(self, req: PublishRequest) -> PublishResult:  # pragma: no cover
        raise NotImplementedError
