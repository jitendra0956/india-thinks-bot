"""Generates editorial-style background photos for use as the base layer
under India Thinks' text/logo overlay. Supports two interchangeable
providers — Google Gemini (default) and OpenAI — selected via the
IMAGE_PROVIDER config value, with zero changes needed anywhere else in
the pipeline.

This module has exactly one public function (generate_ai_background) and
it either returns a real PIL Image or raises — it never returns a
placeholder or silently degrades. The caller (make_image.py) is
responsible for catching failures and falling back to the pure-PIL
renderer; that fallback logic does not live here, so this module stays
simple and its one failure mode stays obvious.
"""
import io

from PIL import Image

from config import (GEMINI_API_KEY, GEMINI_IMAGE_MODEL, IMAGE_PROVIDER,
                     OPENAI_API_KEY, OPENAI_IMAGE_MODEL, OPENAI_IMAGE_SIZE,
                     OPENAI_IMAGE_QUALITY)
from utils import logger, retry

# Appended to every prompt regardless of provider. The "no text" instruction
# is the single most important line here: image models reliably mangle
# rendered text, so we generate a clean photographic background and add
# all real text (headline, logo, CTA) ourselves with PIL afterward, where
# typography is crisp and exactly on-brand instead of an AI guess.
STYLE_SUFFIX = """
Style: editorial magazine photography, cinematic lighting, dark and moody
background tones with a subtle warm yellow accent light source somewhere
in the frame, high-end news publication aesthetic, realistic photographic
detail (not illustration, not 3D render, not cartoon), shallow depth of
field, professional composition suitable for a premium digital publication
cover. Vertical portrait orientation matching a 4:5 aspect ratio (1080 by
1350 pixels). India-focused visual context where relevant to the topic --
real Indian settings, people, and everyday details rather than generic or
Western-coded imagery.

CRITICAL constraints: absolutely no text, no words, no letters, no numbers,
no logos, no captions, no watermarks, no signage with readable text
anywhere in the image. Keep the top quarter and bottom quarter of the
frame relatively uncluttered and darker in tone, since a headline, a small
logo, and a call-to-action button will be added on top of those areas
afterward. The image itself should contain zero typography of any kind.
""".strip()


def _generate_gemini(topic_prompt: str) -> Image.Image:
    """Gemini 2.5 Flash Image ("Nano Banana"). Returns image bytes as an
    inline_data part of a normal generate_content response, not through a
    dedicated image endpoint -- the standard documented pattern for
    multimodal Gemini output as of this writing.

    Deliberately does NOT use utils.require_env here: that helper raises
    SystemExit, which is correct for top-level fail-fast checks elsewhere
    in this codebase but would be a real bug in this specific function —
    it would propagate straight through make_image.py's `except Exception`
    fallback wrapper (SystemExit is not an Exception subclass) and crash
    the whole pipeline instead of degrading to the PIL renderer.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    from google import genai  # imported lazily -- see module docstring

    client = genai.Client(api_key=GEMINI_API_KEY)
    full_prompt = f"{topic_prompt}\n\n{STYLE_SUFFIX}"

    response = client.models.generate_content(
        model=GEMINI_IMAGE_MODEL,
        contents=full_prompt,
    )

    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        raise ValueError("Gemini Image response had no candidates")

    parts = getattr(candidates[0].content, "parts", None) or []
    for part in parts:
        inline_data = getattr(part, "inline_data", None)
        if inline_data is not None and getattr(inline_data, "data", None):
            image = Image.open(io.BytesIO(inline_data.data)).convert("RGB")
            logger.info("AI background image generated via Gemini (%dx%d)", *image.size)
            return image

    raise ValueError("Gemini Image response contained no image data")


def _generate_openai(topic_prompt: str) -> Image.Image:
    """OpenAI's GPT Image family. Note: DALL-E 2 and DALL-E 3 were removed
    from OpenAI's API on 2026-05-12 -- do not revert to those model names.
    GPT Image 1 Mini (the default here) is OpenAI's own recommended choice
    for high-volume, budget-conscious use, which matches a twice-daily
    automated pipeline exactly.

    Same SystemExit-avoidance reasoning as _generate_gemini applies here.
    """
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set")

    from openai import OpenAI  # imported lazily -- see module docstring

    client = OpenAI(api_key=OPENAI_API_KEY)
    full_prompt = f"{topic_prompt}\n\n{STYLE_SUFFIX}"

    response = client.images.generate(
        model=OPENAI_IMAGE_MODEL,
        prompt=full_prompt,
        size=OPENAI_IMAGE_SIZE,
        quality=OPENAI_IMAGE_QUALITY,
        n=1,
    )

    data = getattr(response, "data", None) or []
    if not data:
        raise ValueError("OpenAI image response contained no data")

    item = data[0]
    b64 = getattr(item, "b64_json", None)
    if b64:
        image = Image.open(io.BytesIO(__import__("base64").b64decode(b64))).convert("RGB")
        logger.info("AI background image generated via OpenAI (%dx%d)", *image.size)
        return image

    url = getattr(item, "url", None)
    if url:
        import requests
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        image = Image.open(io.BytesIO(r.content)).convert("RGB")
        logger.info("AI background image generated via OpenAI (%dx%d, fetched by URL)", *image.size)
        return image

    raise ValueError("OpenAI image response had neither b64_json nor url")


_PROVIDERS = {
    "gemini": _generate_gemini,
    "openai": _generate_openai,
}


@retry(times=2, delay=3, backoff=2, exceptions=(Exception,))
def generate_ai_background(topic_prompt: str) -> Image.Image:
    """Generates an editorial-style background photo using whichever
    provider IMAGE_PROVIDER selects ("gemini" by default, or "openai").
    Returns a PIL Image in RGB mode, or raises.

    This is the ONLY function the rest of the pipeline calls — switching
    providers is a config change (IMAGE_PROVIDER), never a code change in
    make_image.py or anywhere else.
    """
    provider_fn = _PROVIDERS.get(IMAGE_PROVIDER)
    if provider_fn is None:
        raise ValueError(
            f"Unknown IMAGE_PROVIDER '{IMAGE_PROVIDER}' -- must be one of {list(_PROVIDERS)}"
        )
    return provider_fn(topic_prompt)
