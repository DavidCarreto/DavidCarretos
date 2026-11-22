from ..config import Account
from .base import PublishRequest, PublishResult, Publisher


def get_publisher(acc: Account) -> Publisher:
    # perfil pessoal do Facebook: a Graph API não publica em perfis (publish_actions removido em 2018);
    # vai SEMPRE para o telemóvel, seja qual for a configuração
    if acc.mode == "assist":   # perfil pessoal do Facebook, TikTok por auditar, página LinkedIn por aprovar…
        from .assist import AssistPublisher
        return AssistPublisher()
    if acc.platform == "instagram":
        from .instagram import InstagramPublisher
        return InstagramPublisher()
    if acc.platform == "facebook_page":
        from .facebook import FacebookPagePublisher
        return FacebookPagePublisher()
    if acc.platform == "tiktok":
        from .tiktok import TikTokPublisher
        return TikTokPublisher()
    if acc.platform in ("linkedin_member", "linkedin_org"):
        from .linkedin import LinkedInPublisher
        return LinkedInPublisher()
    from .assist import AssistPublisher
    return AssistPublisher()


__all__ = ["get_publisher", "PublishRequest", "PublishResult", "Publisher"]
