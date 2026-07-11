"""Publishes the daily post to a Telegram channel/group via the Bot API.

Simpler than the Instagram path it replaces in two important ways:
1. Telegram accepts a direct multipart file upload (sendPhoto), so the
   image does NOT need a public URL — no jsDelivr CDN dependency, no
   requirement that the commit/push happened first for publishing to
   work (the workflow still commits first, for the blog and history, but
   Telegram publishing no longer depends on it).
2. No expiring tokens: a Telegram bot token doesn't need the ~60-day
   manual refresh the Instagram token did.

Failure policy (per requirements): a Telegram failure must never fail the
workflow. This module still raises on failure — keeping the same
"succeed fully or fail loudly" contract as every other module — and
main.py's telegram publish path catches it, logs a clear error, and exits
successfully anyway.
"""
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from utils import logger, retry

TELEGRAM_API = "https://api.telegram.org"
# Telegram's hard limit for a photo caption is 1024 characters (messages
# get 4096, but photo captions specifically get 1024).
TELEGRAM_CAPTION_LIMIT = 1024
REQUEST_TIMEOUT = 60


class TelegramPublishError(RuntimeError):
    """Raised when Telegram rejects or fails to accept a post."""


def _truncate_caption(caption: str) -> str:
    if len(caption) <= TELEGRAM_CAPTION_LIMIT:
        return caption
    logger.warning(
        "Caption is %d chars, over Telegram's %d photo-caption limit — truncating.",
        len(caption), TELEGRAM_CAPTION_LIMIT,
    )
    return caption[: TELEGRAM_CAPTION_LIMIT - 1].rstrip() + "…"


@retry(times=3, delay=5, backoff=2, exceptions=(requests.RequestException,))
def post_photo_to_telegram(image_path: str, caption: str) -> int:
    """Uploads the image file directly to Telegram with the caption.
    Returns the sent message id. Raises TelegramPublishError with
    Telegram's actual error description on rejection.
    """
    if not TELEGRAM_BOT_TOKEN:
        raise TelegramPublishError("TELEGRAM_BOT_TOKEN is not set")
    if not TELEGRAM_CHAT_ID:
        raise TelegramPublishError("TELEGRAM_CHAT_ID is not set")

    caption = _truncate_caption(caption)

    with open(image_path, "rb") as f:
        r = requests.post(
            f"{TELEGRAM_API}/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
            files={"photo": f},
            timeout=REQUEST_TIMEOUT,
        )

    body = {}
    try:
        body = r.json()
    except ValueError:
        pass

    if not r.ok or not body.get("ok"):
        # Telegram's error descriptions are genuinely useful (e.g. "chat not
        # found", "bot was kicked") — surface them instead of a bare status.
        raise TelegramPublishError(
            f"Telegram sendPhoto failed: HTTP {r.status_code} — "
            f"{body.get('description', r.text[:200])}"
        )

    message_id = body["result"]["message_id"]
    logger.info("Published to Telegram: message id %s", message_id)
    return message_id
