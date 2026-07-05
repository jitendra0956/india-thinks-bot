"""Generates editorial-style background photos via Gemini 2.5 Flash Image
("Nano Banana"), for use as the base layer under India Thinks' text/logo
overlay.

This module has exactly one public function and it either returns a real
PIL Image or raises — it never returns a placeholder or silently degrades.
The caller (make_image.py) is responsible for catching failures and
falling back to the pure-PIL renderer; that fallback logic does not live
here, so this module stays simple and its failure mode stays obvious.

Implementation note: Gemini's image-output models (as opposed to the
separate Imagen product) return image bytes as an inline_data part of a
normal generate_content response, not through a dedicated image-generation
endpoint. This is the standard documented pattern for multimodal Gemini
output as of this writing — if Google changes the response shape, this is
the one place that needs updating.
"""
import io

from PIL import Image

from config import GEMINI_API_KEY, GEMINI_IMAGE_MODEL
from utils import logger, retry

# Appended to every prompt. The "no text" instruction is the single most
# important line here: image models reliably mangle rendered text, so we
# generate a clean photographic background and add all real text (headline,
# logo, CTA) ourselves with PIL afterward, where typography is crisp and
# exactly on-brand instead of an AI guess.
STYLE_SUFFIX = """
Style: editorial magazine photography, cinematic lighting, dark and moody
background tones with a subtle warm yellow accent light source somewhere
in the frame, high-end news publication aesthetic, realistic photographic
detail (not illustration, not 3D render, not cartoon), shallow depth of
field, professional composition suitable for a premium digital publication
cover. Vertical portrait orientation matching a 4:5 aspect ratio (1080 by
1350 pixels).

CRITICAL constraints: absolutely no text, no words, no letters, no numbers,
no logos, no captions, no watermarks, no signage with readable text
anywhere in the image. Keep the top quarter and bottom quarter of the
frame relatively uncluttered and darker in tone, since a headline, a small
logo, and a call-to-action button will be added on top of those areas
afterward. The image itself should contain zero typography of any kind.
""".strip()


@retry(times=2, delay=3, backoff=2, exceptions=(Exception,))
def generate_ai_background(topic_prompt: str) -> Image.Image:
    """Calls Gemini 2.5 Flash Image to generate an editorial-style
    background photo for one post. Returns a PIL Image in RGB mode.

    Raises on any failure (missing key, network error, safety block, no
    image data in the response) — callers must catch and fall back to the
    PIL renderer rather than treating a raised exception here as fatal to
    the whole pipeline.

    Deliberately does NOT use utils.require_env here: that helper raises
    SystemExit, which is correct for top-level fail-fast checks elsewhere
    in this codebase but would be a real bug in this specific function —
    it would propagate straight through make_image.py's `except Exception`
    fallback wrapper (SystemExit is not an Exception subclass) and crash
    the whole pipeline instead of degrading to the PIL renderer, which
    defeats the entire point of USE_AI_IMAGES having a safe fallback.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    # Imported here, not at module load, so the rest of the pipeline (and
    # its tests) never need the google-genai package importable just to
    # read this file when USE_AI_IMAGES is off.
    from google import genai

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
            logger.info("AI background image generated (%dx%d)", *image.size)
            return image

    raise ValueError("Gemini Image response contained no image data")
