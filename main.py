"""India Thinks daily pipeline — runs twice a day, once per posting slot.

Run order (GitHub Actions triggers this once per slot, at 9 AM and 6 PM IST):
  1. select   — Gemini scores 20 candidate topics against recency + engagement
  2. generate — Gemini elaborates the winner into one of 5 post templates
  3. render   — the single feed image (and a story image) are rendered
  4. blog     — article + click-to-vote page published to GitHub Pages
  5. commit   — workflow commits everything (images need a public URL)
  6. instagram — the single image is published as the day's feed post

Split into two commands, same as before, because images must be committed
and pushed BEFORE Instagram can fetch them:
  python main.py prepare <morning|evening>
  python main.py publish <morning|evening>
"""
import glob
import json
import os
import re
import sys
from datetime import date, timedelta

from config import BLOG_URL, GITHUB_REPOSITORY, GITHUB_REF_NAME, IMAGE_RETENTION_DAYS, POST_SLOTS
from generate_content import generate_daily_package
from make_image import make_post_image, make_story_image, headline_for_story
from publish_blog import publish_post
from utils import logger

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def _package_path(slot: str) -> str:
    return os.path.join(OUTPUT_DIR, f"package-{slot}.json")


def _topics_debug_path(slot: str) -> str:
    """Transparency artifact: the full 20-candidate scoring breakdown for
    every post, committed to the repo so it's inspectable later."""
    return os.path.join(OUTPUT_DIR, "topics", f"{date.today().isoformat()}-{slot}.json")


def _validate_slot(slot: str) -> str:
    if slot not in POST_SLOTS:
        raise SystemExit(f"Unknown slot '{slot}'. Must be one of: {', '.join(POST_SLOTS)}")
    return slot


def _prune_old_images() -> None:
    """Deletes rendered images older than IMAGE_RETENTION_DAYS.

    Instagram only needs source images transiently, to fetch them once at
    publish time — after that Instagram serves them from its own CDN.
    Blog articles and the topic-scoring debug JSON are kept forever.
    """
    cutoff = date.today() - timedelta(days=IMAGE_RETENTION_DAYS)
    removed = 0
    for path in glob.glob(os.path.join(OUTPUT_DIR, "*.jpg")):
        match = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
        if not match:
            continue
        try:
            file_date = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if file_date < cutoff:
            os.remove(path)
            removed += 1
    if removed:
        logger.info("Pruned %d old image(s) older than %d days.", removed, IMAGE_RETENTION_DAYS)


def prepare(slot: str) -> None:
    slot = _validate_slot(slot)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "topics"), exist_ok=True)

    logger.info("[%s] 1/4 Selecting and generating today's debate...", slot)
    package = generate_daily_package(slot)
    post = package["post"]
    logger.info("[%s]     Topic: %s (template=%s)", slot, package["poll_question"], post["template_type"])

    with open(_topics_debug_path(slot), "w") as f:
        json.dump(package["topic_selection"], f, indent=2)

    today = date.today().isoformat()
    tag = f"{slot}-{today}"

    logger.info("[%s] 2/4 Rendering post image (template: %s)...", slot, post["template_type"])
    post_image_path = os.path.join(OUTPUT_DIR, f"post-{tag}.jpg")
    # image_prompt is passed through so the (optional) AI image path gets a
    # real, topic-specific description rather than a generic fallback built
    # from just the kicker and headline. Passing None (the default) still
    # works fine — make_post_image() builds a reasonable prompt itself —
    # this is a quality improvement, not a required wiring.
    make_post_image(post["template_type"], post["content"], post["kicker"], post["cta"],
                     post_image_path, image_prompt=package.get("image_prompt"))
    package["post_image_file"] = os.path.relpath(post_image_path, os.path.dirname(__file__))

    story_headline = headline_for_story(post["template_type"], post["content"]) or package["poll_question"]
    story_path = os.path.join(OUTPUT_DIR, f"story-{tag}.jpg")
    make_story_image(story_headline, post["cta"], story_path)
    package["story_image_file"] = os.path.relpath(story_path, os.path.dirname(__file__))

    logger.info("[%s] 3/4 Publishing blog article...", slot)
    package["blog_post_path"] = publish_post(package)

    logger.info("[%s] 4/4 Pruning old images...", slot)
    _prune_old_images()

    with open(_package_path(slot), "w") as f:
        json.dump(package, f, indent=2)
    logger.info("[%s] Prepared. Commit the repo, then run: python main.py publish %s", slot, slot)


def publish(slot: str) -> None:
    from post_instagram import post_single_to_instagram

    slot = _validate_slot(slot)
    package_path = _package_path(slot)
    if not os.path.exists(package_path):
        raise SystemExit(
            f"{package_path} not found. Run 'python main.py prepare {slot}' first, "
            f"and make sure the repo was committed/pushed before calling publish."
        )

    with open(package_path) as f:
        package = json.load(f)

    if not GITHUB_REPOSITORY:
        raise SystemExit(
            "GITHUB_REPOSITORY is not set. This step is meant to run inside "
            "GitHub Actions, where that variable is set automatically."
        )
    if "post_image_file" not in package:
        raise SystemExit("package.json is missing 'post_image_file' — did 'prepare' complete successfully?")

    # jsDelivr's GitHub CDN — reliable content-type headers and, since every
    # filename is unique per day+slot, never serves a stale cached image.
    image_url = f"https://cdn.jsdelivr.net/gh/{GITHUB_REPOSITORY}@{GITHUB_REF_NAME}/{package['post_image_file']}"
    caption = package["instagram_caption"] + f"\n\nRead the full explainer: {BLOG_URL}"

    logger.info("[%s] Posting image to Instagram (template: %s)...", slot, package["post"]["template_type"])
    post_single_to_instagram(image_url, caption)
    logger.info("[%s] Done. Today's %s debate is live.", slot, slot)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else None
    slot_arg = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd not in ("prepare", "publish") or slot_arg not in POST_SLOTS:
        raise SystemExit(f"Usage: python main.py <prepare|publish> <{'|'.join(POST_SLOTS)}>")

    try:
        if cmd == "prepare":
            prepare(slot_arg)
        else:
            publish(slot_arg)
    except Exception as exc:
        logger.error("Pipeline failed (%s/%s): %s", cmd, slot_arg, exc)
        raise
