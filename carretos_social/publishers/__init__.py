from ..config import Account
from .base import PublishRequest, PublishResult, Publisher


def get_publisher(acc: Account) -> Publisher:
    if acc.publish_mode == "assist":
        from .assist import AssistPublisher
        return AssistPublisher()
    if acc.platform == "instagram":
        from .instagram import InstagramPublisher
        return InstagramPublisher()
    if acc.platform == "tiktok":
        from .tiktok import TikTokPublisher
        return TikTokPublisher()
    if acc.platform in ("linkedin_member", "linkedin_org"):
        from .linkedin import LinkedInPublisher
        return LinkedInPublisher()
    from .assist import AssistPublisher
    return AssistPublisher()


__all__ = ["get_publisher", "PublishRequest", "PublishResult", "Publisher"]
