"""Posts to Instagram via the official Meta Graph API.

Two publish paths:
  - post_single_to_instagram()   — one image (used for the cover, if you
                                    choose to post it standalone)
  - post_carousel_to_instagram() — a multi-image carousel post (used for
                                    the daily 6-slide debate carousel,
                                    which is what main.py auto-publishes,
                                    since carousels carry the full
                                    "swipe through both sides, then
                                    comment" mechanic this product is built
                                    around)

Both require the images to already be at public URLs (Instagram fetches
them itself — you can't upload bytes directly). See main.py for how the
jsDelivr CDN URL is built.

Note on Stories: Instagram's Graph API does not support publishing
interactive story stickers (like the native Poll sticker) programmatically
for standard app review tiers. The story image is generated and available
for manual posting — see README's Known Limitations.
"""
import time

import requests

from config import IG_ACCESS_TOKEN, IG_USER_ID
from utils import logger, require_env, retry

GRAPH = "https://graph.facebook.com/v21.0"
INSTAGRAM_CAPTION_LIMIT = 2200  # Meta's hard limit; longer captions are rejected outright.
POLL_ATTEMPTS = 12
POLL_DELAY_SECONDS = 5
REQUEST_TIMEOUT = 60


class InstagramPublishError(RuntimeError):
    """Raised when Instagram rejects or fails to process a post — with a clear reason."""


def _truncate_caption(caption: str) -> str:
    if len(caption) <= INSTAGRAM_CAPTION_LIMIT:
        return caption
    logger.warning(
        "Caption is %d chars, over Instagram's %d limit — truncating.",
        len(caption), INSTAGRAM_CAPTION_LIMIT,
    )
    return caption[: INSTAGRAM_CAPTION_LIMIT - 1].rstrip() + "…"


@retry(times=3, delay=5, backoff=2, exceptions=(requests.RequestException,))
def _create_item_container(image_url: str, is_carousel_item: bool, caption: str = None) -> str:
    data = {"image_url": image_url, "access_token": IG_ACCESS_TOKEN}
    if is_carousel_item:
        data["is_carousel_item"] = "true"
    if caption:
        data["caption"] = caption
    r = requests.post(f"{GRAPH}/{IG_USER_ID}/media", data=data, timeout=REQUEST_TIMEOUT)
    if not r.ok:
        raise InstagramPublishError(f"Failed to create media container: {r.status_code} {r.text}")
    return r.json()["id"]


@retry(times=3, delay=5, backoff=2, exceptions=(requests.RequestException,))
def _create_carousel_container(item_ids: list[str], caption: str) -> str:
    r = requests.post(
        f"{GRAPH}/{IG_USER_ID}/media",
        data={
            "media_type": "CAROUSEL",
            "children": ",".join(item_ids),
            "caption": caption,
            "access_token": IG_ACCESS_TOKEN,
        },
        timeout=REQUEST_TIMEOUT,
    )
    if not r.ok:
        raise InstagramPublishError(f"Failed to create carousel container: {r.status_code} {r.text}")
    return r.json()["id"]


@retry(times=3, delay=5, backoff=2, exceptions=(requests.RequestException,))
def _publish_container(container_id: str) -> str:
    r = requests.post(
        f"{GRAPH}/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": IG_ACCESS_TOKEN},
        timeout=REQUEST_TIMEOUT,
    )
    if not r.ok:
        raise InstagramPublishError(f"Failed to publish media: {r.status_code} {r.text}")
    return r.json()["id"]


def _wait_for_processing(container_id: str) -> None:
    """Polls until Instagram finishes fetching/processing the image(s).

    Explicitly checks for ERROR status instead of silently timing out and
    attempting to publish anyway.
    """
    for attempt in range(1, POLL_ATTEMPTS + 1):
        r = requests.get(
            f"{GRAPH}/{container_id}",
            params={"fields": "status_code", "access_token": IG_ACCESS_TOKEN},
            timeout=30,
        )
        r.raise_for_status()
        status = r.json().get("status_code")

        if status == "FINISHED":
            return
        if status == "ERROR":
            raise InstagramPublishError(
                f"Instagram failed to process container {container_id}. "
                f"Check that the image URL(s) are publicly reachable, valid JPEGs, "
                f"and within Instagram's 4:5 to 1.91:1 aspect ratio range."
            )
        logger.info("Waiting for Instagram to process... (%d/%d, status=%s)",
                    attempt, POLL_ATTEMPTS, status)
        time.sleep(POLL_DELAY_SECONDS)

    raise InstagramPublishError(
        f"Timed out waiting for Instagram to process container {container_id} "
        f"after {POLL_ATTEMPTS * POLL_DELAY_SECONDS}s."
    )


def post_single_to_instagram(image_url: str, caption: str) -> str:
    """Publishes one standalone feed image. Returns the media id."""
    require_env("IG_ACCESS_TOKEN", IG_ACCESS_TOKEN)
    require_env("IG_USER_ID", IG_USER_ID)
    caption = _truncate_caption(caption)

    logger.info("Creating Instagram media container...")
    container_id = _create_item_container(image_url, is_carousel_item=False, caption=caption)
    _wait_for_processing(container_id)

    logger.info("Publishing to Instagram...")
    media_id = _publish_container(container_id)
    logger.info("Published to Instagram: media id %s", media_id)
    return media_id


def post_carousel_to_instagram(image_urls: list[str], caption: str) -> str:
    """Publishes a multi-image carousel post. Returns the media id.

    Each image becomes a child item container first (is_carousel_item=true,
    no caption on children — the caption lives on the parent container
    only), then all children are attached to one CAROUSEL container, which
    is what actually gets published.
    """
    require_env("IG_ACCESS_TOKEN", IG_ACCESS_TOKEN)
    require_env("IG_USER_ID", IG_USER_ID)
    if not 2 <= len(image_urls) <= 10:
        raise ValueError(f"Instagram carousels need 2-10 images, got {len(image_urls)}")
    caption = _truncate_caption(caption)

    logger.info("Creating %d carousel item containers...", len(image_urls))
    item_ids = []
    for url in image_urls:
        item_id = _create_item_container(url, is_carousel_item=True)
        _wait_for_processing(item_id)
        item_ids.append(item_id)

    logger.info("Creating carousel container...")
    carousel_id = _create_carousel_container(item_ids, caption)
    _wait_for_processing(carousel_id)

    logger.info("Publishing carousel to Instagram...")
    media_id = _publish_container(carousel_id)
    logger.info("Published carousel to Instagram: media id %s", media_id)
    return media_id
