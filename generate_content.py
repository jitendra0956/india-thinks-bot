"""Generates a full India Thinks post using a two-stage Gemini pipeline.

Stage 1 — SELECT: search current trends and brainstorm 20 candidate debate
topics, score each on 7 dimensions, and deterministically pick the winner
in Python (never trust an LLM's own arithmetic/ranking — recompute it).

Stage 2 — ELABORATE: given the single winning topic, generate everything
that topic needs: article, caption, cover post, 6-slide carousel, story
content, and AI image-generation prompts.

Splitting into two calls (rather than one giant "pick and write everything"
call) keeps each JSON response smaller and more reliable, and makes the
topic-scoring transparent and independently inspectable — the scores are
saved to disk, not just used internally and discarded.
"""
import json
import os
from datetime import date

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL, TEMPLATE_TYPES, CTA_BY_TEMPLATE, ICON_SET
from utils import logger, retry, require_env

BLOG_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "blog", "manifest.json")

# Weights: trend_momentum is now the highest-weighted dimension — the brief
# changed from "evergreen is fine" to "must feel like something Indians are
# already discussing today." comment_potential stays a close second since
# a fresh-but-boring policy tweak still isn't worth posting.
SCORE_WEIGHTS = {
    "trend_momentum": 0.25,
    "comment_potential": 0.22,
    "discussion_potential": 0.18,
    "relatability": 0.13,
    "opinion_strength": 0.12,
    "shareability": 0.10,
}
BRAND_SAFETY_MIN = 8   # candidates scoring below this are excluded entirely, not just penalized
NEWS_ANCHOR_REQUIRED = True  # candidates with no real recent-news citation are excluded entirely

PRIORITY_CATEGORIES = [
    "current news and breaking events",
    "government regulations and policy changes",
    "consumer issues and product/service complaints",
    "technology changes affecting ordinary people",
    "fuel prices and energy policy (e.g. E20 petrol)",
    "banking rules and UPI/payment changes",
    "taxation and GST changes",
    "jobs, layoffs, and hiring trends (e.g. AI layoffs)",
    "education and exams (e.g. NEET/JEE issues)",
    "transportation and mobility policy",
    "viral social media debates from the last 7 days",
]

GOOD_TOPIC_EXAMPLES = [
    "Should petrol pumps be required to clearly label E20 fuel blends?",
    "Is the new UPI transaction limit good for consumers?",
    "Should the latest GST rate change on this product apply?",
    "Should NEET/JEE be scrapped in favour of board-marks-based admission?",
    "Are AI-driven layoffs at Indian IT firms justified?",
    "Should companies be allowed to mandate full return-to-office?",
    "Should petrol/diesel prices be brought under GST?",
    "Should banks be held liable for UPI fraud losses?",
    "Should this week's viral consumer complaint change how the brand operates?",
]

EVERGREEN_TOPICS_TO_AVOID = [
    "Is hustle culture toxic or necessary?",
    "Are dating apps making relationships worse?",
    "Should tipping be mandatory at restaurants?",
    "Is social media making us lonely?",
    "Should you follow your passion or chase money?",
]

SELECT_PROMPT_TEMPLATE = """You run "India Thinks", a daily Instagram debate page with the philosophy "Learn First. Vote Later."

Your job right now is ONLY to select a topic — not write about it yet.

Search the web for what has actually happened in India in THE LAST 7 DAYS. You must prioritize these categories, in roughly this order of preference:
{priority_categories}

Concretely, prefer things like: E20 petrol rollout news, UPI transaction rule changes, GST rate changes, NEET/JEE exam controversies, AI-driven layoffs at Indian companies, work-from-office mandates, fuel price changes, new banking rules, and consumer complaints that went viral this week.

Generate exactly 20 candidate debate topics. Every single candidate MUST be anchored to something that specifically happened, changed, or was announced in the last 7 days — not a timeless question that could have been asked any week of any year.

Do NOT propose evergreen philosophical or lifestyle debates unless they are directly triggered by a specific recent news event. For calibration, here is the WRONG kind of topic — reject these even though they're relatable, because they aren't tied to anything that just happened:
{evergreen_examples}

Here is the RIGHT kind of topic — tied to a real, recent, checkable event or change:
{good_examples}

For each candidate, you must be able to point to the actual news trigger. If you cannot name a specific recent event/policy/change behind a topic, do not include it.

Still apply these rules:
- It must be something an ordinary person (not a policy expert) instantly has a gut reaction to.
- It must be a YES/NO question, answerable in one line.
- It must have genuine, roughly balanced arguments on both sides.
- STRICTLY AVOID: religion, active elections or named politicians, communal or caste angles, personal attacks on named private individuals, and unverified medical claims. If a topic touches sensitive personal themes (e.g. exam stress), keep it at the policy level, not individual tragedy.
- Do NOT repeat these topics we've already covered recently: {excluded_topics}

For EACH of the 20 candidates, provide:
- "topic": the yes/no debate question, under 12 words
- "news_anchor": one factual sentence naming the SPECIFIC recent event, policy, or change this topic is tied to (include an approximate date/timeframe if you found one in your search). This is mandatory — a candidate with no real news_anchor will be discarded.
- Scores 0-10 on each dimension:
  - relatability: does almost anyone in India instantly understand and relate to this?
  - opinion_strength: does this provoke a strong instinctive YES or NO, not a shrug?
  - comment_potential: how likely is a random viewer to type a comment?
  - discussion_potential: how likely is this to spark back-and-forth disagreement in the comments?
  - shareability: how likely is someone to share/tag a friend on this?
  - trend_momentum: how current and "being discussed right now" is this, based on your search?
  - brand_safety: 10 = perfectly safe and neutral, 0 = violates a hard exclusion above

Respond with ONLY a JSON object, no markdown fences, no commentary:

{{
  "candidates": [
    {{"topic": "Clear yes/no debate question under 12 words", "news_anchor": "The specific recent event/policy/change this is tied to, with approximate date", "relatability": 0, "opinion_strength": 0, "comment_potential": 0, "discussion_potential": 0, "shareability": 0, "trend_momentum": 0, "brand_safety": 0}}
  ]
}}

The "candidates" array must contain exactly 20 objects."""

ELABORATE_PROMPT_TEMPLATE = """You run "India Thinks", a daily Instagram debate page with the philosophy "The Nation Decides."

The topic for today's post has already been chosen by a scoring process. Your job now is to fully develop it — do not second-guess or change the topic.

TOPIC: {topic}
NEWS ANCHOR: {news_anchor}

The post is delivered as ONE single image. A viewer must understand the topic, both sides, and know what to comment within 3 seconds of seeing it. Every point you write must be SHORT — under 8 words each, no exceptions. This is not the place for nuance; nuance lives in the article.

Visual polish rules:
- In every headline-style field (question/title/event/statement/belief/reality), wrap exactly ONE or TWO of the most important words in double asterisks, e.g. "Will AI **replace** most jobs?" — those words render in the brand's yellow accent color, the rest in white. Choose the word that carries the emotional weight of the claim, not a filler word.
- Every bullet point is an object with "text" (under 8 words, may also use **emphasis** on one word if it helps) and "icon" (pick the single closest-fitting icon from this exact list, lowercase, no other values allowed): {icon_set}

First, pick the ONE template_type that best fits this specific topic, and build the "content" object using EXACTLY the matching shape below — no other fields, no extra keys. Every "_points" list is a list of {{"text": ..., "icon": ...}} objects, not plain strings:

- template_type "debate" (a clear two-sided yes/no question -- use for most policy/regulation/consumer topics):
  content = {{"question": "under 12 words, may use **emphasis**", "yes_points": [3 point-objects], "no_points": [3 point-objects]}}

- template_type "comparison" (two concrete options being weighed -- use when the topic is "which one," not "yes or no"):
  content = {{"title": "under 12 words, may use **emphasis**", "option_a_label": "2-4 words", "option_a_points": [3 point-objects], "option_b_label": "2-4 words", "option_b_points": [3 point-objects]}}

- template_type "prediction" (a future event where the interesting question is what happens next -- use for market-moving news or upcoming policy changes):
  content = {{"event": "under 12 words, may use **emphasis**", "bull_points": [3 point-objects], "bear_points": [3 point-objects]}}

- template_type "hot_take" (a single strong, controversial statement -- use when the news anchor itself IS the provocative claim):
  content = {{"statement": "under 14 words, may use **emphasis**", "supporting_points": [3 point-objects]}}

- template_type "fact_vs_myth" (a common misconception versus the actual reality -- use when the news reveals popular belief is wrong):
  content = {{"belief": "under 14 words, may use **emphasis**", "reality": "under 14 words, may use **emphasis**", "explanation_points": [3 point-objects]}}

Then produce a complete content package. Respond with ONLY a JSON object, no markdown fences, no commentary before or after it:

{{
  "topic_slug": "2-4 words, lowercase, hyphen-separated, no punctuation",
  "category": "one word: technology, economy, education, society, or environment (pick closest fit)",
  "poll_question": "The debate as a clear yes/no question under 12 words, for the blog vote widget (write this even if template_type isn't 'debate' -- it's what powers the click-to-vote page)",
  "option_yes": "Yes side label (2-4 words)",
  "option_no": "No side label (2-4 words)",
  "article_title": "Engaging article title",
  "article_markdown": "A 450-550 word balanced explainer in markdown. Structure: one-paragraph hook explaining what happened and why it matters right now, '## Why people say yes' with 3 short argument paragraphs, '## Why people say no' with 3 short argument paragraphs, '## Key facts' with 3 bullet points citing real sources found in your search, '## The bottom line' one neutral closing paragraph that does NOT pick a side.",
  "instagram_caption": "Instagram caption under 2000 characters: curiosity hook line tied to the news anchor, then a one-line summary, then 'Full story -- link in bio.' End with 8-10 relevant hashtags including #india.",
  "post": {{
    "template_type": "debate, comparison, prediction, hot_take, or fact_vs_myth -- your choice from above",
    "kicker": "short uppercase category label, e.g. FUEL POLICY or BANKING UPDATE",
    "content": "an object matching EXACTLY the shape for your chosen template_type, as defined above -- no extra fields"
  }},
  "image_prompt": "A detailed prompt for an AI image model describing layout, typography, composition, visual hierarchy, dark background with a single yellow accent color, India Thinks branding placement, and CTA placement, optimized for mobile Instagram feed viewing at 1080x1350px, matching the chosen template_type's structure."
}}

Rules: perfectly balanced, no loaded language in the article, every fact must come from real search results, never invent statistics. If the topic touches personal hardship (e.g. exam stress), keep the post at the policy level, not individual tragedy."""


def _manifest() -> list[dict]:
    if not os.path.exists(BLOG_MANIFEST_PATH):
        return []
    try:
        with open(BLOG_MANIFEST_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Could not read blog manifest: %s", exc)
        return []


def _recent_titles(limit: int = 15) -> list[str]:
    """Titles from the last N posts, for general anti-repetition across days."""
    return [item["title"] for item in _manifest()[:limit] if "title" in item]


def _todays_titles() -> list[str]:
    """Titles already published today — used so the evening post can never
    pick the same (or a near-duplicate) topic as the morning post. Both
    slots write to the same blog manifest, so by the time the evening run
    executes, the morning post is already committed and visible here."""
    today_str = date.today().strftime("%B %d, %Y")
    return [item["title"] for item in _manifest() if item.get("date") == today_str]


def _extract_json_object(text: str) -> dict:
    """Robustly extracts the first valid top-level JSON object from free-form text."""
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text, idx)
            return obj
        except json.JSONDecodeError:
            idx = text.find("{", idx + 1)
    raise ValueError(f"No valid JSON object found in model response: {text[:300]!r}")


def _call_gemini(prompt: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.9,
        ),
    )
    text = getattr(response, "text", None)
    if not text:
        finish_reason = None
        try:
            finish_reason = response.candidates[0].finish_reason
        except (AttributeError, IndexError):
            pass
        raise ValueError(f"Gemini returned no text (finish_reason={finish_reason})")
    return text


def _score_candidate(c: dict) -> float:
    return sum(float(c.get(dim, 0)) * weight for dim, weight in SCORE_WEIGHTS.items())


@retry(times=3, delay=3, backoff=2, exceptions=(Exception,))
def select_topic(exclude_topics: list[str]) -> dict:
    """Stage 1: brainstorm + score 20 candidates, return the ranked list and winner.

    Scoring math is recomputed here in Python from the model's per-dimension
    numbers rather than trusting any ranking the model itself claims — LLM
    arithmetic on 20 rows is exactly the kind of thing that quietly drifts.

    Two hard gates are applied before ranking, in addition to score weights:
    - brand_safety must be >= BRAND_SAFETY_MIN
    - news_anchor must be a non-empty, specific citation of a recent event
      (this is what actually enforces "must feel like today," rather than
      trusting the model's own trend_momentum self-score in isolation)
    """
    require_env("GEMINI_API_KEY", GEMINI_API_KEY)

    prompt = SELECT_PROMPT_TEMPLATE.format(
        priority_categories="\n".join(f"- {c}" for c in PRIORITY_CATEGORIES),
        good_examples="\n".join(f"- {t}" for t in GOOD_TOPIC_EXAMPLES),
        evergreen_examples="\n".join(f"- {t}" for t in EVERGREEN_TOPICS_TO_AVOID),
        excluded_topics=", ".join(exclude_topics) or "(none yet)",
    )
    text = _call_gemini(prompt)
    data = _extract_json_object(text)

    candidates = data.get("candidates", [])
    if len(candidates) < 10:
        raise ValueError(f"Expected ~20 candidates, got {len(candidates)}")

    for c in candidates:
        c["total_score"] = round(_score_candidate(c), 2)

    eligible = [c for c in candidates if float(c.get("brand_safety", 0)) >= BRAND_SAFETY_MIN]
    if NEWS_ANCHOR_REQUIRED:
        before = len(eligible)
        eligible = [c for c in eligible if str(c.get("news_anchor", "")).strip()]
        dropped = before - len(eligible)
        if dropped:
            logger.info("Dropped %d candidate(s) with no news_anchor (evergreen/unanchored).", dropped)

    if not eligible:
        raise ValueError("No candidate topics passed the brand-safety and news-anchor gates")

    ranked = sorted(eligible, key=lambda c: c["total_score"], reverse=True)
    winner = ranked[0]

    logger.info("Topic selected: %s (score=%.2f, anchor=%s)",
                winner["topic"], winner["total_score"], winner.get("news_anchor", "n/a"))
    return {
        "all_candidates": sorted(candidates, key=lambda c: c["total_score"], reverse=True),
        "eligible_candidates": ranked,
        "winner": winner,
    }


# The exact required fields for each template's "content" object. Used to
# validate the model's output strictly — a template claiming to be "debate"
# but missing "yes_points" should fail fast and retry, not render a broken
# or half-empty image.
TEMPLATE_CONTENT_SCHEMA = {
    "debate": ("question", "yes_points", "no_points"),
    "comparison": ("title", "option_a_label", "option_a_points", "option_b_label", "option_b_points"),
    "prediction": ("event", "bull_points", "bear_points"),
    "hot_take": ("statement", "supporting_points"),
    "fact_vs_myth": ("belief", "reality", "explanation_points"),
}


@retry(times=3, delay=3, backoff=2, exceptions=(Exception,))
def generate_full_package(topic: str, news_anchor: str = "") -> dict:
    """Stage 2: elaborate the already-chosen topic into a full content package."""
    require_env("GEMINI_API_KEY", GEMINI_API_KEY)

    prompt = ELABORATE_PROMPT_TEMPLATE.format(
        topic=topic, news_anchor=news_anchor or "n/a",
        icon_set=", ".join(ICON_SET),
    )
    text = _call_gemini(prompt)
    package = _extract_json_object(text)

    required = ["topic_slug", "category", "poll_question", "option_yes", "option_no",
                "article_title", "article_markdown", "instagram_caption",
                "post", "image_prompt"]
    missing = [k for k in required if not package.get(k)]
    if missing:
        raise ValueError(f"Model response missing/empty keys: {missing}")

    post = package["post"]
    for key in ("template_type", "kicker", "content"):
        if key not in post:
            raise ValueError(f"'post' is missing '{key}'")

    template_type = post["template_type"]
    if template_type not in TEMPLATE_TYPES:
        raise ValueError(f"Unknown template_type '{template_type}', must be one of {TEMPLATE_TYPES}")

    content = post["content"]
    expected_fields = TEMPLATE_CONTENT_SCHEMA[template_type]
    missing_content = [f for f in expected_fields if not content.get(f)]
    if missing_content:
        raise ValueError(f"'{template_type}' content is missing fields: {missing_content}")

    _sanitize_points_fields(content, template_type)

    # CTA is deterministic per template, not left to the model — keeps every
    # post of a given type visually and verbally consistent.
    post["cta"] = CTA_BY_TEMPLATE[template_type]

    return package


# Fields ending in "_points" hold lists of {"text", "icon"} objects (see
# ELABORATE_PROMPT_TEMPLATE). Older/malformed responses might send plain
# strings instead — normalize those to the object shape rather than
# failing, since a missing icon is cosmetic, not a reason to burn a retry.
_FALLBACK_ICON = "check"


def _sanitize_points_fields(content: dict, template_type: str) -> None:
    for field in TEMPLATE_CONTENT_SCHEMA[template_type]:
        if not field.endswith("_points"):
            continue
        items = content.get(field, [])
        if not isinstance(items, list) or len(items) < 1:
            raise ValueError(f"'{field}' must be a non-empty list")

        normalized = []
        for item in items[:3]:
            if isinstance(item, dict):
                text = str(item.get("text", "")).strip()
                icon = str(item.get("icon", "")).strip().lower()
                if icon not in ICON_SET:
                    icon = _FALLBACK_ICON
            else:
                # Model sent a plain string instead of {"text","icon"} —
                # recover gracefully with a neutral fallback icon rather
                # than retrying the whole (expensive) generation call.
                text = str(item).strip()
                icon = _FALLBACK_ICON
            if not text:
                raise ValueError(f"'{field}' contains an empty point")
            normalized.append({"text": text, "icon": icon})

        if len(normalized) < 1:
            raise ValueError(f"'{field}' has no usable points")
        content[field] = normalized


def generate_daily_package(slot: str) -> dict:
    """Full pipeline for one posting slot ('morning' or 'evening').

    Returns a dict with both the topic-selection transparency data
    (all 20 scored candidates + winner) and the full elaborated content
    package, merged under clearly separated top-level keys.
    """
    exclude = list(dict.fromkeys(_recent_titles() + _todays_titles()))
    selection = select_topic(exclude)
    winner = selection["winner"]
    package = generate_full_package(winner["topic"], winner.get("news_anchor", ""))
    package["topic_selection"] = selection
    package["slot"] = slot
    return package


if __name__ == "__main__":
    import sys
    slot_arg = sys.argv[1] if len(sys.argv) > 1 else "morning"
    pkg = generate_daily_package(slot_arg)
    print(json.dumps(pkg, indent=2)[:3000])
