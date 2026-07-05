"""Premium editorial visual system for India Thinks — single-image posts.

Upgraded visual language (matching a reference design the founder liked):
dark background, single yellow accent, real icon badges next to each
bullet point, and two-tone keyword highlighting in headlines (one or two
words rendered in yellow within an otherwise white headline — the same
idea as **bold** in markdown, reused here since the model already handles
that marker reliably elsewhere in this codebase).

Five reusable templates, one image each (1080x1350):
  - debate        question, YES vs NO, 3 icon-badged points each
  - comparison    option A vs option B, 3 icon-badged points each
  - prediction    future event, bull case vs bear case
  - hot_take      one bold statement + supporting points (single column)
  - fact_vs_myth  common belief vs the actual reality

Plus one story renderer (1080x1920) with a reserved zone for manually
adding Instagram's native Poll sticker.
"""
import math
import os
import re

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

from config import (BRAND_NAME, IMG_SIZE_FEED, IMG_SIZE_STORY,
                     BG_COLOR, PANEL_COLOR, YELLOW, YELLOW_DARK_TEXT, WHITE,
                     MUTED, BORDER, USE_AI_IMAGES)
from utils import logger

# Fonts are bundled with the project (assets/fonts/) rather than referenced
# by OS-installed system paths. This was a real, confirmed bug: the code
# used to hardcode Linux-only paths like
# "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", which silently
# fail on Windows and macOS. When that happened, PIL's exception handler
# fell back to ImageFont.load_default() — which ignores the requested
# point size entirely and renders every piece of text at a tiny fixed
# size, while pure geometry (panels, pill shapes, icon circles) still
# rendered at full size. That mismatch is exactly what produced a "nearly
# blank image with a few tiny yellow marks": real content, invisible text.
_FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
FONT_BOLD = os.path.join(_FONTS_DIR, "DejaVuSans-Bold.ttf")
FONT_REGULAR = os.path.join(_FONTS_DIR, "DejaVuSans.ttf")

_font_warning_shown = False

PAD = 72
ICON_BADGE_R = 30
_FALLBACK_ICON = "check"

# Supersampling: every image is actually rendered at SCALE times the target
# resolution, then downsampled with high-quality resampling before saving.
# This is what makes curves, circles, and text edges look smooth instead of
# jagged — plain PIL drawing at 1x has no anti-aliasing at all, which is
# the core reason the earlier version read as "flat plain shapes" rather
# than a polished graphic.
#
# All existing layout code (padding, font sizes, wrap widths) stays in
# ORIGINAL/logical units — _ScaledDraw transparently multiplies every
# coordinate by SCALE before the real draw call, and divides textlength()
# results back down to logical units so wrapping math is unaffected.
SCALE = 4


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Returns a font loaded at SCALE x the requested size, so glyphs are
    rendered with real resolution to downsample from, not just stretched.

    Fonts are bundled in assets/fonts/, so this should never actually need
    to fall back on a correctly-checked-out install. If it ever does, that
    failure is now LOUD (logged once, clearly) rather than silently
    degrading every piece of text on every image to an unreadable fixed
    tiny size — that silent failure mode is exactly what shipped a
    "nearly blank" image last time, and a quiet fallback here would let
    the same class of bug hide again.
    """
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(path, size * SCALE)
    except OSError as exc:
        global _font_warning_shown
        if not _font_warning_shown:
            logger.error(
                "Could not load bundled font at %s (%s). Every image will "
                "render with visibly wrong text sizing until this is fixed "
                "-- check that assets/fonts/ was included when this repo "
                "was checked out or copied.", path, exc,
            )
            _font_warning_shown = True
        # Try the requested size explicitly where the installed Pillow
        # version supports it (10.1+), so a missing bundled font degrades
        # to "readable but using a different font" instead of "invisible."
        try:
            return ImageFont.load_default(size=size * SCALE)
        except TypeError:
            return ImageFont.load_default()


def _scale_xy(seq):
    """Scales a coordinate argument by SCALE, handling every shape PIL
    accepts: a flat [x0,y0,x1,y1] box, a list of (x,y) point tuples, or a
    single (x,y) point."""
    if isinstance(seq, (list, tuple)) and seq and isinstance(seq[0], (list, tuple)):
        return [(p[0] * SCALE, p[1] * SCALE) for p in seq]
    if isinstance(seq, (list, tuple)) and len(seq) == 4 and all(isinstance(v, (int, float)) for v in seq):
        return [v * SCALE for v in seq]
    if isinstance(seq, (list, tuple)) and len(seq) == 2 and all(isinstance(v, (int, float)) for v in seq):
        return (seq[0] * SCALE, seq[1] * SCALE)
    return seq


class _ScaledDraw:
    """Wraps a real ImageDraw so every existing call site in this file can
    keep using logical (1x) coordinates and font sizes unchanged, while the
    actual pixels land on a SCALE x canvas for anti-aliased downsampling."""

    def __init__(self, real_draw):
        self._d = real_draw

    def line(self, xy, fill=None, width=1):
        self._d.line(_scale_xy(xy), fill=fill, width=max(1, round(width * SCALE)))

    def rectangle(self, xy, fill=None, outline=None, width=1):
        self._d.rectangle(_scale_xy(xy), fill=fill, outline=outline, width=max(1, round(width * SCALE)))

    def rounded_rectangle(self, xy, radius=0, fill=None, outline=None, width=1):
        self._d.rounded_rectangle(_scale_xy(xy), radius=radius * SCALE, fill=fill, outline=outline,
                                   width=max(1, round(width * SCALE)))

    def ellipse(self, xy, fill=None, outline=None, width=1):
        self._d.ellipse(_scale_xy(xy), fill=fill, outline=outline, width=max(1, round(width * SCALE)))

    def polygon(self, xy, fill=None, outline=None, width=1):
        kwargs = {"fill": fill, "outline": outline}
        try:
            self._d.polygon(_scale_xy(xy), width=max(1, round(width * SCALE)), **kwargs)
        except TypeError:
            # Older Pillow versions don't accept width= for polygon.
            self._d.polygon(_scale_xy(xy), **kwargs)

    def arc(self, xy, start, end, fill=None, width=1):
        self._d.arc(_scale_xy(xy), start, end, fill=fill, width=max(1, round(width * SCALE)))

    def pieslice(self, xy, start, end, fill=None, outline=None, width=1):
        self._d.pieslice(_scale_xy(xy), start, end, fill=fill, outline=outline,
                          width=max(1, round(width * SCALE)) if outline else 1)

    def text(self, xy, text, font=None, fill=None, anchor=None):
        x, y = xy
        self._d.text((x * SCALE, y * SCALE), text, font=font, fill=fill, anchor=anchor)

    def textlength(self, text, font=None) -> float:
        # font passed in is already SCALE x sized (from _font()), so the
        # raw result is in scaled pixels — convert back to logical units so
        # every wrap/fit calculation elsewhere in this file needs no changes.
        return self._d.textlength(text, font=font) / SCALE


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        test = f"{line} {w}".strip()
        if draw.textlength(test, font=font) <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def _tracked_text(draw, xy, text: str, font, fill, tracking: int = 3):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


# ---------------------------------------------------------------------------
# Emphasis markup: "Will AI **replace** most jobs?" -> "replace" in yellow,
# the rest in the base color. Parsed once into (word, is_highlighted) pairs,
# then wrapped and drawn word-by-word so highlighting survives line wraps.
# ---------------------------------------------------------------------------

def _parse_emphasis(text: str) -> list[tuple[str, bool]]:
    tokens = []
    parts = re.split(r"\*\*(.+?)\*\*", text)
    for i, part in enumerate(parts):
        is_hl = (i % 2 == 1)
        for word in part.split():
            tokens.append((word, is_hl))
    return tokens


def _draw_rich_text(draw, xy, text: str, font, max_width: int,
                     base_color=WHITE, hl_color=YELLOW, line_height: int | None = None,
                     max_lines: int = 5) -> int:
    """Draws text with **emphasis** markup rendered in hl_color, wrapping at
    max_width. Returns the y-coordinate immediately below the last line."""
    tokens = _parse_emphasis(text)
    line_height = line_height or int(font.size * 1.25)
    x0, y = xy
    x = x0
    space_w = draw.textlength(" ", font=font)
    lines_drawn = 0

    for word, is_hl in tokens:
        w = draw.textlength(word, font=font)
        if x > x0 and x + w > x0 + max_width:
            x = x0
            y += line_height
            lines_drawn += 1
            if lines_drawn >= max_lines:
                break
        draw.text((x, y), word, font=font, fill=(hl_color if is_hl else base_color))
        x += w + space_w

    return y + line_height


def _rich_text_line_count(draw, text: str, font, max_width: int, max_lines: int = 5) -> int:
    """How many lines _draw_rich_text will actually use — needed to
    vertically center multi-line headlines before drawing them."""
    tokens = _parse_emphasis(text)
    x0, x = 0, 0
    space_w = draw.textlength(" ", font=font)
    lines = 1
    for word, _ in tokens:
        w = draw.textlength(word, font=font)
        if x > x0 and x + w > x0 + max_width:
            x = x0
            lines += 1
            if lines >= max_lines:
                break
        x += w + space_w
    return lines


# ---------------------------------------------------------------------------
# Icon badges — simple line-art, drawn with primitives only (no icon fonts
# or external assets), matching the reference's circular outline style.
# ---------------------------------------------------------------------------

def _draw_icon_glyph(draw, kind: str, cx: float, cy: float, r: float, color) -> None:
    lw = max(2, int(r * 0.16))

    if kind == "gear":
        draw.ellipse([cx - r * 0.45, cy - r * 0.45, cx + r * 0.45, cy + r * 0.45], outline=color, width=lw)
        for i in range(8):
            ang = math.pi * 2 * i / 8
            x1, y1 = cx + math.cos(ang) * r * 0.55, cy + math.sin(ang) * r * 0.55
            x2, y2 = cx + math.cos(ang) * r * 0.8, cy + math.sin(ang) * r * 0.8
            draw.line([(x1, y1), (x2, y2)], fill=color, width=lw)
    elif kind == "person":
        draw.ellipse([cx - r * 0.28, cy - r * 0.75, cx + r * 0.28, cy - r * 0.2], outline=color, width=lw)
        draw.arc([cx - r * 0.55, cy - r * 0.15, cx + r * 0.55, cy + r * 0.85], 200, 340, fill=color, width=lw)
    elif kind == "chart":
        bar_w = r * 0.32
        heights = [r * 0.5, r * 0.85, r * 0.65]
        for i, h in enumerate(heights):
            x0 = cx - r * 0.7 + i * (bar_w + r * 0.15)
            draw.rectangle([x0, cy + r * 0.5 - h, x0 + bar_w, cy + r * 0.5], outline=color, width=lw)
    elif kind == "pie":
        draw.ellipse([cx - r * 0.6, cy - r * 0.6, cx + r * 0.6, cy + r * 0.6], outline=color, width=lw)
        draw.pieslice([cx - r * 0.6, cy - r * 0.6, cx + r * 0.6, cy + r * 0.6], -90, 60, fill=color)
    elif kind == "heart":
        draw.pieslice([cx - r * 0.55, cy - r * 0.5, cx, cy], 180, 360, outline=color, width=lw)
        draw.pieslice([cx, cy - r * 0.5, cx + r * 0.55, cy], 180, 360, outline=color, width=lw)
        draw.polygon([(cx - r * 0.55, cy - r * 0.1), (cx + r * 0.55, cy - r * 0.1), (cx, cy + r * 0.6)], outline=color, width=lw)
    elif kind == "globe":
        draw.ellipse([cx - r * 0.6, cy - r * 0.6, cx + r * 0.6, cy + r * 0.6], outline=color, width=lw)
        draw.ellipse([cx - r * 0.25, cy - r * 0.6, cx + r * 0.25, cy + r * 0.6], outline=color, width=max(1, lw - 1))
        draw.line([(cx - r * 0.6, cy), (cx + r * 0.6, cy)], fill=color, width=max(1, lw - 1))
    elif kind == "calendar":
        draw.rounded_rectangle([cx - r * 0.6, cy - r * 0.5, cx + r * 0.6, cy + r * 0.6], radius=6, outline=color, width=lw)
        draw.line([(cx - r * 0.6, cy - r * 0.15), (cx + r * 0.6, cy - r * 0.15)], fill=color, width=lw)
        draw.line([(cx - r * 0.25, cy - r * 0.65), (cx - r * 0.25, cy - r * 0.4)], fill=color, width=lw)
        draw.line([(cx + r * 0.25, cy - r * 0.65), (cx + r * 0.25, cy - r * 0.4)], fill=color, width=lw)
    elif kind == "money":
        draw.ellipse([cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55], outline=color, width=lw)
        f = _font(int(r * 0.7))
        draw.text((cx, cy), "₹", font=f, fill=color, anchor="mm")
    elif kind == "book":
        draw.polygon([(cx - r * 0.55, cy - r * 0.45), (cx, cy - r * 0.6), (cx + r * 0.55, cy - r * 0.45),
                      (cx + r * 0.55, cy + r * 0.55), (cx, cy + r * 0.35), (cx - r * 0.55, cy + r * 0.55)],
                     outline=color, width=lw)
        draw.line([(cx, cy - r * 0.6), (cx, cy + r * 0.35)], fill=color, width=max(1, lw - 1))
    elif kind == "check":
        draw.line([(cx - r * 0.4, cy), (cx - r * 0.1, cy + r * 0.35)], fill=color, width=lw + 1)
        draw.line([(cx - r * 0.1, cy + r * 0.35), (cx + r * 0.5, cy - r * 0.35)], fill=color, width=lw + 1)
    elif kind == "cross":
        draw.line([(cx - r * 0.4, cy - r * 0.4), (cx + r * 0.4, cy + r * 0.4)], fill=color, width=lw + 1)
        draw.line([(cx - r * 0.4, cy + r * 0.4), (cx + r * 0.4, cy - r * 0.4)], fill=color, width=lw + 1)
    elif kind == "warning":
        draw.polygon([(cx, cy - r * 0.6), (cx + r * 0.6, cy + r * 0.5), (cx - r * 0.6, cy + r * 0.5)],
                     outline=color, width=lw)
        draw.line([(cx, cy - r * 0.15), (cx, cy + r * 0.12)], fill=color, width=lw)
        draw.ellipse([cx - lw * 0.6, cy + r * 0.28, cx + lw * 0.6, cy + r * 0.28 + lw * 1.2], fill=color)
    elif kind == "arrow_up":
        draw.line([(cx, cy + r * 0.5), (cx, cy - r * 0.5)], fill=color, width=lw)
        draw.line([(cx, cy - r * 0.5), (cx - r * 0.35, cy - r * 0.15)], fill=color, width=lw)
        draw.line([(cx, cy - r * 0.5), (cx + r * 0.35, cy - r * 0.15)], fill=color, width=lw)
    elif kind == "arrow_down":
        draw.line([(cx, cy - r * 0.5), (cx, cy + r * 0.5)], fill=color, width=lw)
        draw.line([(cx, cy + r * 0.5), (cx - r * 0.35, cy + r * 0.15)], fill=color, width=lw)
        draw.line([(cx, cy + r * 0.5), (cx + r * 0.35, cy + r * 0.15)], fill=color, width=lw)
    elif kind == "phone":
        draw.rounded_rectangle([cx - r * 0.35, cy - r * 0.6, cx + r * 0.35, cy + r * 0.6], radius=8, outline=color, width=lw)
        draw.line([(cx - r * 0.12, cy + r * 0.42), (cx + r * 0.12, cy + r * 0.42)], fill=color, width=lw)
    elif kind == "bank":
        draw.polygon([(cx - r * 0.6, cy - r * 0.15), (cx, cy - r * 0.6), (cx + r * 0.6, cy - r * 0.15)],
                     outline=color, width=lw)
        for dx in (-r * 0.4, 0, r * 0.4):
            draw.line([(cx + dx, cy - r * 0.1), (cx + dx, cy + r * 0.45)], fill=color, width=lw)
        draw.line([(cx - r * 0.6, cy + r * 0.55), (cx + r * 0.6, cy + r * 0.55)], fill=color, width=lw)
    elif kind == "fuel":
        draw.rounded_rectangle([cx - r * 0.35, cy - r * 0.55, cx + r * 0.2, cy + r * 0.55], radius=6, outline=color, width=lw)
        draw.line([(cx - r * 0.1, cy - r * 0.3), (cx - r * 0.1, cy + r * 0.15)], fill=color, width=max(1, lw - 1))
        draw.line([(cx + r * 0.2, cy - r * 0.15), (cx + r * 0.45, cy - r * 0.15)], fill=color, width=lw)
        draw.line([(cx + r * 0.45, cy - r * 0.15), (cx + r * 0.45, cy + r * 0.3)], fill=color, width=lw)
    elif kind == "shield":
        draw.polygon([(cx, cy - r * 0.6), (cx + r * 0.5, cy - r * 0.35), (cx + r * 0.5, cy + r * 0.15),
                      (cx, cy + r * 0.6), (cx - r * 0.5, cy + r * 0.15), (cx - r * 0.5, cy - r * 0.35)],
                     outline=color, width=lw)
    elif kind == "scale":
        draw.line([(cx, cy - r * 0.5), (cx, cy + r * 0.4)], fill=color, width=lw)
        draw.line([(cx - r * 0.55, cy - r * 0.25), (cx + r * 0.55, cy - r * 0.25)], fill=color, width=lw)
        draw.ellipse([cx - r * 0.55 - 6, cy - r * 0.1, cx - r * 0.55 + 6, cy + r * 0.05], outline=color, width=max(1, lw - 1))
        draw.ellipse([cx + r * 0.55 - 6, cy - r * 0.1, cx + r * 0.55 + 6, cy + r * 0.05], outline=color, width=max(1, lw - 1))
        draw.line([(cx - r * 0.3, cy + r * 0.4), (cx + r * 0.3, cy + r * 0.4)], fill=color, width=lw)
    elif kind == "clock":
        draw.ellipse([cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55], outline=color, width=lw)
        draw.line([(cx, cy), (cx, cy - r * 0.35)], fill=color, width=max(1, lw - 1))
        draw.line([(cx, cy), (cx + r * 0.28, cy)], fill=color, width=max(1, lw - 1))
    else:
        # Unknown icon name (shouldn't happen after sanitization, but a
        # rendering-time fallback costs nothing and never crashes a post).
        draw.ellipse([cx - r * 0.12, cy - r * 0.12, cx + r * 0.12, cy + r * 0.12], fill=color)


def _icon_badge(draw, x: int, y: int, icon: str, color=YELLOW, r: int = ICON_BADGE_R) -> None:
    cx, cy = x + r, y + r
    draw.ellipse([x, y, x + 2 * r, y + 2 * r], outline=color, width=2)
    _draw_icon_glyph(draw, icon, cx, cy, r * 0.62, color)


# ---------------------------------------------------------------------------
# Shared chrome
# ---------------------------------------------------------------------------

def _new_canvas(size: tuple[int, int]) -> Image.Image:
    """Flat near-black background with a very subtle yellow glow in one
    corner for depth. Rendered directly at SCALE x resolution (this
    function isn't routed through _ScaledDraw since it only does its own
    internal glow overlay, not general layout drawing)."""
    real_size = (size[0] * SCALE, size[1] * SCALE)
    img = Image.new("RGB", real_size, BG_COLOR)
    overlay = Image.new("RGB", real_size, (0, 0, 0))
    od = ImageDraw.Draw(overlay)
    r = int(real_size[0] * 0.55)
    od.ellipse([-r * 0.4, -r * 0.5, r * 0.9, r * 0.7], fill=YELLOW)
    overlay = overlay.filter(ImageFilter.GaussianBlur(160 * SCALE))
    return Image.blend(img, overlay, alpha=0.10)


def _brand_lockup(draw, x: int, y: int):
    sq = 14
    draw.rectangle([x, y, x + sq, y + sq], fill=YELLOW)
    draw.text((x + sq + 10, y - 5), BRAND_NAME, font=_font(24), fill=WHITE)


def _kicker(draw, x: int, y: int, text: str, max_width: int | None = None, size: int = 22) -> int:
    """Draws the tracked-uppercase kicker label with a short underline
    accent beneath it (matching the reference design). Returns the y
    position immediately below the underline."""
    font = _font(size)
    if max_width:
        tracking = 3
        while tracking > 0:
            test_width = sum(draw.textlength(c, font=font) + tracking for c in text.upper())
            if test_width <= max_width:
                break
            tracking -= 1
        end_x = _tracked_text(draw, (x, y), text.upper(), font, YELLOW, tracking=max(tracking, 0))
    else:
        end_x = _tracked_text(draw, (x, y), text.upper(), font, YELLOW, tracking=3)
    underline_y = y + size + 10
    draw.line([(x, underline_y), (x + 46, underline_y)], fill=YELLOW, width=3)
    return underline_y + 16


def _cta_pill(canvas_size: tuple[int, int], draw, cta_text: str, bottom_margin: int = 84):
    """Solid yellow rounded pill with a small chat-bubble glyph at the end.

    Takes logical canvas_size explicitly (not an Image object) — reading
    img.width/img.height was a real bug: after supersampling was added,
    the actual Image object is SCALE times bigger than logical coordinates,
    so cx/y1 computed from it were already-scaled values that then got
    scaled AGAIN by the _ScaledDraw proxy, pushing the pill off-canvas
    entirely. canvas_size is always the logical (1x) size, same units as
    every other coordinate in this file.
    """
    font = _font(30)
    text = cta_text.upper()
    text_w = draw.textlength(text, font=font)
    bubble_d = 34
    pill_w = int(text_w) + 90 + bubble_d
    pill_h = 78
    cx = canvas_size[0] // 2
    x0, x1 = cx - pill_w // 2, cx + pill_w // 2
    y1 = canvas_size[1] - bottom_margin
    y0 = y1 - pill_h
    draw.rounded_rectangle([x0, y0, x1, y1], radius=pill_h // 2, fill=YELLOW)

    text_x = x0 + 40
    draw.text((text_x, (y0 + y1) // 2), text, font=font, fill=YELLOW_DARK_TEXT, anchor="lm")

    # Small speech-bubble glyph after the text
    bx = x1 - 55
    by = (y0 + y1) // 2
    draw.rounded_rectangle([bx - bubble_d / 2, by - bubble_d / 2 + 4, bx + bubble_d / 2, by + bubble_d / 2 - 4],
                            radius=10, fill=YELLOW_DARK_TEXT)
    for i, dx in enumerate((-8, 0, 8)):
        draw.ellipse([bx + dx - 2.5, by - 2.5, bx + dx + 2.5, by + 2.5], fill=YELLOW)


def _panel(draw, x0, y0, x1, y1, radius=20, outline=BORDER):
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=PANEL_COLOR, outline=outline, width=1)


def _points_block(draw, x: int, y: int, width: int, points: list[dict],
                   label_color=YELLOW, icon_color=None) -> int:
    """Draws icon-badged bullet points (icon circle left, text right),
    matching the reference's row layout with thin dividers between rows."""
    icon_color = icon_color or label_color
    font = _font(29)
    row_gap = 26

    for i, point in enumerate(points[:3]):
        icon = point.get("icon", _FALLBACK_ICON) if isinstance(point, dict) else _FALLBACK_ICON
        text = point.get("text", "") if isinstance(point, dict) else str(point)

        _icon_badge(draw, x, y, icon, color=icon_color)
        text_x = x + 2 * ICON_BADGE_R + 22
        text_width = width - (2 * ICON_BADGE_R + 22)
        text_bottom = _draw_rich_text(draw, (text_x, y + 2), text, font, text_width,
                                       base_color=WHITE, hl_color=label_color,
                                       line_height=36, max_lines=2)
        row_height = max(2 * ICON_BADGE_R, text_bottom - y - 6)
        next_y = y + row_height + row_gap
        if i < len(points[:3]) - 1:
            divider_y = next_y - row_gap // 2
            draw.line([(x, divider_y), (x + width, divider_y)], fill=BORDER, width=1)
        y = next_y
    return y


def _header(draw, canvas_size, kicker: str) -> int:
    return _kicker(draw, PAD, PAD, kicker, max_width=canvas_size[0] - 2 * PAD - 40)


def _footer(draw, canvas_size, cta: str) -> None:
    _cta_pill(canvas_size, draw, cta)
    _brand_lockup(draw, PAD, canvas_size[1] - 60)


# ---------------------------------------------------------------------------
# TEMPLATE 1 — DEBATE
# ---------------------------------------------------------------------------

def _render_debate(content: dict, kicker: str, cta: str) -> Image.Image:
    w, h = IMG_SIZE_FEED
    img = _new_canvas(IMG_SIZE_FEED)
    d = _ScaledDraw(ImageDraw.Draw(img))
    header_y = _header(d, IMG_SIZE_FEED, kicker)

    q_font = _font(58)
    y = _draw_rich_text(d, (PAD, header_y + 10), content["question"], q_font, w - 2 * PAD,
                         line_height=66, max_lines=4)

    split_top = y + 40
    split_bottom = h - 210
    mid_y = (split_top + split_bottom) // 2
    _panel(d, PAD, split_top, w - PAD, split_bottom)
    d.line([(PAD + 24, mid_y), (w - PAD - 24, mid_y)], fill=BORDER, width=1)

    label_font = _font(26)
    d.text((PAD + 24, split_top + 18), "YES", font=label_font, fill=YELLOW)
    _points_block(d, PAD + 24, split_top + 60, w - 2 * PAD - 48, content["yes_points"], label_color=YELLOW)

    d.text((PAD + 24, mid_y + 18), "NO", font=label_font, fill=MUTED)
    _points_block(d, PAD + 24, mid_y + 60, w - 2 * PAD - 48, content["no_points"], label_color=WHITE, icon_color=MUTED)

    _footer(d, IMG_SIZE_FEED, cta)
    return img


# ---------------------------------------------------------------------------
# TEMPLATE 2 — COMPARISON
# ---------------------------------------------------------------------------

def _render_comparison(content: dict, kicker: str, cta: str) -> Image.Image:
    w, h = IMG_SIZE_FEED
    img = _new_canvas(IMG_SIZE_FEED)
    d = _ScaledDraw(ImageDraw.Draw(img))
    header_y = _header(d, IMG_SIZE_FEED, kicker)

    q_font = _font(54)
    y = _draw_rich_text(d, (PAD, header_y + 10), content["title"], q_font, w - 2 * PAD,
                         line_height=64, max_lines=4)

    split_top = y + 40
    split_bottom = h - 210
    mid_y = (split_top + split_bottom) // 2
    _panel(d, PAD, split_top, w - PAD, split_bottom)
    d.line([(PAD + 24, mid_y), (w - PAD - 24, mid_y)], fill=BORDER, width=1)

    label_font = _font(26)
    d.text((PAD + 24, split_top + 18), content["option_a_label"].upper(), font=label_font, fill=YELLOW)
    _points_block(d, PAD + 24, split_top + 60, w - 2 * PAD - 48, content["option_a_points"], label_color=YELLOW)

    d.text((PAD + 24, mid_y + 18), content["option_b_label"].upper(), font=label_font, fill=MUTED)
    _points_block(d, PAD + 24, mid_y + 60, w - 2 * PAD - 48, content["option_b_points"], label_color=WHITE, icon_color=MUTED)

    _footer(d, IMG_SIZE_FEED, cta)
    return img


# ---------------------------------------------------------------------------
# TEMPLATE 3 — PREDICTION
# ---------------------------------------------------------------------------

def _render_prediction(content: dict, kicker: str, cta: str) -> Image.Image:
    w, h = IMG_SIZE_FEED
    img = _new_canvas(IMG_SIZE_FEED)
    d = _ScaledDraw(ImageDraw.Draw(img))
    header_y = _header(d, IMG_SIZE_FEED, kicker)

    q_font = _font(58)
    y = _draw_rich_text(d, (PAD, header_y + 10), content["event"], q_font, w - 2 * PAD,
                         line_height=66, max_lines=4)

    split_top = y + 40
    split_bottom = h - 210
    mid_y = (split_top + split_bottom) // 2
    _panel(d, PAD, split_top, w - PAD, split_bottom)
    d.line([(PAD + 24, mid_y), (w - PAD - 24, mid_y)], fill=BORDER, width=1)

    label_font = _font(26)
    d.text((PAD + 24, split_top + 18), "▲ BULL CASE", font=label_font, fill=YELLOW)
    _points_block(d, PAD + 24, split_top + 60, w - 2 * PAD - 48, content["bull_points"], label_color=YELLOW)

    d.text((PAD + 24, mid_y + 18), "▼ BEAR CASE", font=label_font, fill=MUTED)
    _points_block(d, PAD + 24, mid_y + 60, w - 2 * PAD - 48, content["bear_points"], label_color=WHITE, icon_color=MUTED)

    _footer(d, IMG_SIZE_FEED, cta)
    return img


# ---------------------------------------------------------------------------
# TEMPLATE 4 — HOT TAKE
# ---------------------------------------------------------------------------

def _render_hot_take(content: dict, kicker: str, cta: str) -> Image.Image:
    w, h = IMG_SIZE_FEED
    img = _new_canvas(IMG_SIZE_FEED)
    d = _ScaledDraw(ImageDraw.Draw(img))
    header_y = _header(d, IMG_SIZE_FEED, kicker)

    stmt_font = _font(66)
    n_lines = _rich_text_line_count(d, content["statement"], stmt_font, w - 2 * PAD, max_lines=5)
    block_h = n_lines * 78
    y = header_y + max(30, (420 - block_h) // 2)
    _draw_rich_text(d, (PAD, y), content["statement"], stmt_font, w - 2 * PAD,
                     base_color=WHITE, hl_color=YELLOW, line_height=78, max_lines=5)

    panel_top = header_y + 30 + block_h + 40
    panel_bottom = h - 210
    _panel(d, PAD, panel_top, w - PAD, panel_bottom)
    _points_block(d, PAD + 24, panel_top + 26, w - 2 * PAD - 48, content["supporting_points"], label_color=YELLOW)

    _footer(d, IMG_SIZE_FEED, cta)
    return img


# ---------------------------------------------------------------------------
# TEMPLATE 5 — FACT VS MYTH
# ---------------------------------------------------------------------------

def _render_fact_vs_myth(content: dict, kicker: str, cta: str) -> Image.Image:
    w, h = IMG_SIZE_FEED
    img = _new_canvas(IMG_SIZE_FEED)
    d = _ScaledDraw(ImageDraw.Draw(img))
    y = _header(d, IMG_SIZE_FEED, kicker)

    label_font = _font(26)
    text_font = _font(44)

    _icon_badge(d, PAD, y, "cross", color=MUTED, r=20)
    d.text((PAD + 54, y + 4), "MYTH", font=label_font, fill=MUTED)
    y += 60
    y = _draw_rich_text(d, (PAD, y), content["belief"], text_font, w - 2 * PAD,
                         base_color=MUTED, hl_color=MUTED, line_height=54, max_lines=3)

    y += 30
    d.line([(PAD, y), (w - PAD, y)], fill=BORDER, width=1)
    y += 40

    _icon_badge(d, PAD, y, "check", color=YELLOW, r=20)
    d.text((PAD + 54, y + 4), "FACT", font=label_font, fill=YELLOW)
    y += 60
    y = _draw_rich_text(d, (PAD, y), content["reality"], text_font, w - 2 * PAD,
                         base_color=WHITE, hl_color=YELLOW, line_height=54, max_lines=3)

    panel_top = y + 40
    panel_bottom = h - 210
    if panel_bottom - panel_top > 100:
        _panel(d, PAD, panel_top, w - PAD, panel_bottom)
        _points_block(d, PAD + 24, panel_top + 24, w - 2 * PAD - 48, content["explanation_points"], label_color=YELLOW)

    _footer(d, IMG_SIZE_FEED, cta)
    return img


_TEMPLATE_RENDERERS = {
    "debate": _render_debate,
    "comparison": _render_comparison,
    "prediction": _render_prediction,
    "hot_take": _render_hot_take,
    "fact_vs_myth": _render_fact_vs_myth,
}


def _make_post_image_pil(template_type: str, content: dict, kicker: str, cta: str, out_path: str) -> str:
    """Renders the single feed image using the free, code-only PIL
    renderer, dispatching to the renderer matching its template_type. The
    renderer draws at SCALE x resolution (see _ScaledDraw); downsampling
    with LANCZOS here is what actually produces the anti-aliased edges —
    this step is not optional."""
    renderer = _TEMPLATE_RENDERERS[template_type]
    img = renderer(content, kicker, cta)
    img = img.resize(IMG_SIZE_FEED, Image.LANCZOS)
    img.save(out_path, "JPEG", quality=94)
    return out_path


def _composite_ai_overlay(bg: Image.Image, kicker: str, headline: str, cta: str) -> Image.Image:
    """Takes an AI-generated background photo and overlays the kicker,
    headline (with **emphasis** support), a CTA pill, and the brand
    lockup — a magazine-cover-style treatment suited to a photographic
    background, deliberately simpler than the PIL templates' icon-badged
    bullet-point layout (a busy bulleted chart doesn't sit well on top of
    a photo; a clean headline does).

    Reuses the exact same chrome-drawing helpers as the PIL renderer
    (_kicker, _draw_rich_text, _cta_pill, _brand_lockup) by drawing them
    onto a transparent supersampled layer and alpha-compositing that layer
    over the (resized) photo — so both rendering paths share one visual
    identity instead of two independently-maintained ones.
    """
    w, h = IMG_SIZE_FEED
    bg = ImageOps.fit(bg, (w, h), Image.LANCZOS)

    # Gradient scrim: darkens the top and bottom of the photo so white/
    # yellow text stays legible regardless of what the AI generated there.
    # Rendered directly at supersampled resolution, same as the photo will
    # be composited at, for a clean final downsample.
    big = (w * SCALE, h * SCALE)
    scrim = Image.new("L", big, 0)
    sd = ImageDraw.Draw(scrim)
    top_band = int(big[1] * 0.30)
    bottom_band = int(big[1] * 0.32)
    for y in range(top_band):
        sd.line([(0, y), (big[0], y)], fill=int(190 * (1 - y / top_band)))
    for i in range(bottom_band):
        y = big[1] - bottom_band + i
        sd.line([(0, y), (big[0], y)], fill=int(210 * (i / bottom_band)))

    overlay = Image.new("RGBA", big, (0, 0, 0, 0))
    black = Image.new("RGBA", big, (0, 0, 0, 255))
    black.putalpha(scrim)
    overlay = Image.alpha_composite(overlay, black)

    d = _ScaledDraw(ImageDraw.Draw(overlay))
    _header(d, IMG_SIZE_FEED, kicker)
    head_font = _font(58)
    _draw_rich_text(d, (PAD, PAD + 90), headline, head_font, w - 2 * PAD, line_height=66, max_lines=4)
    _footer(d, IMG_SIZE_FEED, cta)

    overlay_small = overlay.resize((w, h), Image.LANCZOS)
    return Image.alpha_composite(bg.convert("RGBA"), overlay_small).convert("RGB")


def _make_post_image_ai(template_type: str, content: dict, kicker: str, cta: str,
                         out_path: str, image_prompt: str | None = None) -> str:
    """Generates a real editorial-style photo via Gemini 2.5 Flash Image
    and overlays headline/logo/CTA on top of it. Raises on any failure —
    the caller (make_post_image) is what applies the PIL fallback, so this
    function's only job is to succeed fully or fail loudly."""
    from ai_image import generate_ai_background  # imported lazily, see ai_image.py

    headline = headline_for_story(template_type, content)
    if not headline:
        raise ValueError(f"No headline text available for template '{template_type}'")

    prompt = image_prompt or f"An editorial photograph representing the theme: {kicker}. {headline}"
    background = generate_ai_background(prompt)
    final = _composite_ai_overlay(background, kicker, headline, cta)
    final.save(out_path, "JPEG", quality=94)
    return out_path


def make_post_image(template_type: str, content: dict, kicker: str, cta: str,
                     out_path: str, image_prompt: str | None = None) -> str:
    """Renders the single feed image for a post.

    When USE_AI_IMAGES is enabled, tries the Gemini-generated photographic
    background first; on ANY failure (missing key, network error, safety
    block, malformed response — anything at all) it logs a warning and
    falls back to the free PIL renderer automatically, so a bad day for
    the image API never means a missed post. When USE_AI_IMAGES is off,
    goes straight to the PIL renderer with no API call attempted.

    Saves to the exact same out_path either way, so main.py and every
    other caller needs zero changes regardless of which path was used.
    """
    if USE_AI_IMAGES:
        try:
            return _make_post_image_ai(template_type, content, kicker, cta, out_path, image_prompt)
        except Exception as exc:
            logger.warning("AI image generation failed (%s) — falling back to PIL renderer.", exc)

    return _make_post_image_pil(template_type, content, kicker, cta, out_path)


# ---------------------------------------------------------------------------
# STORY
# ---------------------------------------------------------------------------

def make_story_image(headline: str, cta: str, out_path: str) -> str:
    img = _new_canvas(IMG_SIZE_STORY)
    d = _ScaledDraw(ImageDraw.Draw(img))
    w, h = IMG_SIZE_STORY

    y = _kicker(d, PAD, PAD + 40, "TODAY'S DEBATE", max_width=w - 2 * PAD)

    font = _font(66)
    y = _draw_rich_text(d, (PAD, y + 20), headline, font, w - 2 * PAD,
                         base_color=WHITE, hl_color=YELLOW, line_height=78, max_lines=6)

    zone_top = y + 60
    zone_bottom = zone_top + 340
    _panel(d, PAD, zone_top, w - PAD, zone_bottom, radius=28)
    d.text((w / 2, (zone_top + zone_bottom) / 2), "Add Instagram POLL sticker here",
           font=_font(26, bold=False), fill=MUTED, anchor="mm")

    d.text((PAD, zone_bottom + 50), cta, font=_font(30, bold=False), fill=YELLOW)
    _brand_lockup(d, PAD, h - 90)
    img = img.resize(IMG_SIZE_STORY, Image.LANCZOS)
    img.save(out_path, "JPEG", quality=94)
    return out_path


def headline_for_story(template_type: str, content: dict) -> str:
    return {
        "debate": content.get("question", ""),
        "comparison": content.get("title", ""),
        "prediction": content.get("event", ""),
        "hot_take": content.get("statement", ""),
        "fact_vs_myth": content.get("reality", ""),
    }.get(template_type, "")


if __name__ == "__main__":
    make_post_image(
        "debate",
        {"question": "Will AI **replace** most human jobs?",
         "yes_points": [{"text": "Automates routine tasks", "icon": "gear"},
                        {"text": "Cuts entry-level roles", "icon": "chart"},
                        {"text": "Displaces admin, writing work", "icon": "person"}],
         "no_points": [{"text": "Creates new AI jobs", "icon": "book"},
                       {"text": "Human judgment stays vital", "icon": "heart"},
                       {"text": "Boosts productivity instead", "icon": "arrow_up"}]},
        "TODAY'S DEBATE", "COMMENT YES OR NO", "/tmp/preview_debate2.jpg",
    )
    print("Preview generated")
