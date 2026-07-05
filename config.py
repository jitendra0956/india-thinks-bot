"""Configuration — all secrets come from environment variables (GitHub Secrets)."""
import os

# Google Gemini API key — get from aistudio.google.com/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Model used for content generation. Configurable via env var in case a
# newer/cheaper model becomes available without needing a code change.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# AI-generated background images (Gemini 2.5 Flash Image, aka "Nano Banana").
# When False (default), every post uses the free, instant, zero-cost PIL
# renderer only. When True, the pipeline first tries generating a real
# editorial-style photo background via Gemini's image model, and overlays
# the same headline/logo/CTA chrome on top of it — falling back to the
# pure-PIL renderer automatically if generation fails for any reason
# (network error, safety block, malformed response, missing key, etc).
# This is a real per-image cost when enabled — see README for current
# pricing before turning it on for production.
USE_AI_IMAGES = os.environ.get("USE_AI_IMAGES", "false").strip().lower() == "true"
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")

# Instagram Graph API — see README for setup steps
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")  # Your Instagram Business Account ID

# GitHub repo info — used to build the public image URL for Instagram.
# GITHUB_REPOSITORY / GITHUB_REF_NAME are set automatically inside Actions.
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")
GITHUB_REF_NAME = os.environ.get("GITHUB_REF_NAME", "main")

# Your blog URL (GitHub Pages) — shown in captions
BLOG_URL = os.environ.get("BLOG_URL", "https://YOURUSERNAME.github.io/india-thinks-bot/blog/")

# Supabase (free tier) — powers real click-to-vote counting on the blog
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

# Brand — single source of truth. Other modules (make_image, publish_blog)
# import these rather than redefining them, so the brand can never drift
# out of sync between the image, the blog, and the captions.
BRAND_NAME = "India Thinks"
BRAND_TAGLINE = "The Nation Decides"

# Posting slots. Each run of the pipeline is for exactly one slot; the
# GitHub Actions workflow triggers this script once per slot per day.
POST_SLOTS = ("morning", "evening")

# The five reusable post templates. Every post picks exactly one — the
# elaboration stage chooses whichever format best fits the winning topic
# (a fuel-price change might be a "debate", a fresh regulation might be
# "fact_vs_myth", a market-moving rumor might be "prediction", etc).
# CTA wording is deliberately fixed per template (not left to the model)
# so it stays consistent and on-brand across every post of that type.
TEMPLATE_TYPES = ("debate", "comparison", "prediction", "hot_take", "fact_vs_myth")
CTA_BY_TEMPLATE = {
    "debate": "COMMENT YES OR NO",
    "comparison": "WHICH WOULD YOU CHOOSE?",
    "prediction": "WHAT DO YOU THINK?",
    "hot_take": "AGREE OR DISAGREE?",
    "fact_vs_myth": "DID YOU KNOW THIS?",
}

# Icon vocabulary for bullet points — a small, fixed set of simple
# line-art icons drawn directly in PIL (no external icon library/API).
# The model picks the closest-fitting icon per point from this exact list;
# an unrecognized name falls back to a neutral dot rather than crashing.
ICON_SET = (
    "gear", "person", "chart", "pie", "heart", "globe", "calendar", "money",
    "book", "check", "cross", "warning", "arrow_up", "arrow_down", "phone",
    "bank", "fuel", "shield", "scale", "clock",
)

# Premium editorial visual system — dark theme, single yellow accent.
# Deliberately ONE accent color (not a rainbow of category palettes) so
# every post reads as unmistakably "India Thinks" branded, the way a real
# publication's visual identity stays consistent across stories.
IMG_SIZE_FEED = (1080, 1350)     # 4:5 — Instagram's largest feed real estate
IMG_SIZE_STORY = (1080, 1920)    # 9:16 — full-screen story
BG_COLOR = (11, 11, 13)
PANEL_COLOR = (20, 20, 23)
YELLOW = (245, 196, 34)
YELLOW_DARK_TEXT = (23, 18, 2)    # for text printed ON a yellow fill
WHITE = (245, 245, 248)
MUTED = (150, 150, 160)
BORDER = (40, 40, 45)

# How many days' worth of generated images to keep committed in the repo.
# Instagram only needs the images transiently to fetch them once at publish
# time — after that they're served from Instagram's own CDN. Keeping every
# day's images forever would grow the repo without bound, so the workflow
# prunes anything older than this.
IMAGE_RETENTION_DAYS = 3
