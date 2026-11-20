"""Notification handlers for FuelApp."""

import asyncio
import logging
from typing import Optional
from urllib.parse import urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

ALLOWED_DISCORD_HOSTS = frozenset({
    "discord.com",
    "discordapp.com",
    "ptb.discord.com",
    "canary.discord.com",
})


def is_valid_discord_webhook_url(url: str) -> bool:
    """Validate that a URL is an official HTTPS Discord webhook URL (prevents SSRF)."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        return (
            parsed.scheme == "https"
            and (parsed.hostname or "").lower() in ALLOWED_DISCORD_HOSTS
            and parsed.path.startswith("/api/webhooks/")
        )
    except Exception:
        return False


class DiscordClient:
    """Discord webhook client for sending notifications."""

    def __init__(self, webhook_url: str):
        """Initialize Discord client."""
        self.webhook_url = webhook_url

    async def send_notification_async(self, message: str) -> bool:
        """Send a notification to Discord asynchronously."""
        if not self.webhook_url:
            _LOGGER.warning("Discord webhook URL not configured")
            return False

        if not is_valid_discord_webhook_url(self.webhook_url):
            _LOGGER.error("Refusing to send notification to invalid Discord webhook URL")
            return False

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                payload = {"content": message}
                async with session.post(self.webhook_url, json=payload) as response:
                    if response.status in (200, 204):
                        _LOGGER.info("Discord notification sent successfully")
                        return True
                    else:
                        _LOGGER.error(
                            "Failed to send Discord notification: %d %s",
                            response.status,
                            await response.text(),
                        )
                        return False
        except Exception as e:
            _LOGGER.error("Error sending Discord notification: %s", e)
            return False

    def send_notification(self, message: str) -> bool:
        """Send a notification to Discord synchronously."""
        try:
            return asyncio.run(self.send_notification_async(message))
        except Exception as e:
            _LOGGER.error("Failed to run async Discord notification: %s", e)
            return False
