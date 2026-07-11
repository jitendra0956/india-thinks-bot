# Changelog

## Fix: publish step crashed on git-conflict-corrupted package JSON

### Root cause (diagnosed from the founder's real workflow failure)

`publish` failed with `JSONDecodeError: Expecting property name enclosed
in double quotes: line 2 column 1 (char 2)` reading
`output/package-morning.json`. Reproduced exactly: this is what a JSON
file looks like after **git writes merge-conflict markers into it**
(`<<<<<<< HEAD` at line 2). Chain of causes, all in the workflow's commit
step:

1. `git add output/` committed `package-*.json` every run — a design
   mistake from an earlier round: it's a transient scratch file passing
   data from `prepare` to `publish` within one run, and committing it
   meant yesterday's copy lived in the remote for today's rebase to
   conflict with.
2. On conflict, `git pull --rebase` wrote conflict markers straight into
   the file on disk.
3. The push retry loop swallowed the failure — the step exited
   successfully even when rebase/push failed — so the run proceeded to
   `publish` against the corrupted file.

### Fixes (all three layers)

- **`.gitignore`**: `output/package-*.json` is no longer committed at all.
  The intentional, committed transparency artifact (`output/topics/`) and
  the images are unaffected — verified with a real `git add`/`ls-files`
  dry run showing package files excluded and everything else still
  tracked.
- **Workflow commit step hardened**: on a failed rebase, `git rebase
  --abort` restores a clean tree before retrying; a one-time
  `git rm --cached --ignore-unmatch output/package-*.json` untracks
  copies committed by the older workflow version; and if the push never
  succeeds after 3 attempts, the step now **fails loudly** (`exit 1`)
  instead of silently continuing with a possibly-corrupted tree.
- **`main.py`**: a corrupt package file now produces a clear, actionable
  diagnostic naming the likely cause and the fix, instead of a raw
  traceback.

### Verified

- Reproduced the founder's exact error string from synthetic conflict
  markers before writing any fix.
- gitignore behavior verified with a real git dry run.
- The new diagnostic verified against a conflict-markered file.
- Full pipeline (prepare → Telegram publish with mocked API) re-run
  end-to-end: passes.

### One manual step for the existing repo

The older workflow already committed package files to the repo. The
hardened commit step untracks them automatically on its next run, but you
can also do it once manually: `git rm --cached output/package-*.json`,
commit, push.

---

# Changelog

## Instagram publishing replaced with Telegram publishing

Per the founder's request, the publishing destination switched from
Instagram to a Telegram channel. Minimal-change implementation: content
generation, image generation (both Gemini and OpenAI providers), blog
publishing, and the commit/push flow are all untouched.

### What changed

- **New `post_telegram.py`**: `post_photo_to_telegram()` uploads the image
  file directly via Telegram's sendPhoto (multipart) — no public URL
  needed, which removes the jsDelivr CDN dependency from publishing
  entirely. Telegram error descriptions are surfaced verbatim ("chat not
  found", "bot was kicked", etc). Captions are truncated to Telegram's
  1024-char photo-caption limit (stricter than Instagram's 2200).
- **`main.py` `publish()`**: now posts to Telegram with title + caption +
  blog URL. Per requirements, a Telegram failure logs a clear ERROR and
  exits 0 — the workflow never fails because publishing failed (the blog
  is already committed and live by that point). A missing package.json is
  still a hard error, since that means `prepare` never ran. Now-unused
  `GITHUB_REPOSITORY`/`GITHUB_REF_NAME` imports removed.
- **`config.py`**: added `TELEGRAM_BOT_TOKEN` (secret) and
  `TELEGRAM_CHAT_ID` (default `-1004307013125`, overridable via env). IG
  config vars kept but marked retired.
- **`.github/workflows/daily.yml`**: the Instagram publish step replaced
  with a Telegram publish step (`TELEGRAM_BOT_TOKEN` secret +
  `TELEGRAM_CHAT_ID` variable). Everything else in the workflow unchanged.
- **`post_instagram.py` kept on disk, unused** — same convention as the
  carousel code earlier: re-enabling Instagram later is a workflow/config
  change, not a code resurrection.

### Verified with tests

- Caption truncation at exactly 1024 chars with ellipsis.
- Missing token raises `TelegramPublishError` (a normal Exception
  subclass — the SystemExit-vs-Exception lesson from the AI-image round
  re-checked here).
- **The never-fail guarantee tested directly**: ran `main.py publish` with
  a broken token against a real package file — clear ERROR logged, exit
  code 0.
- Success path tested with a mocked Telegram API: correct endpoint,
  correct chat_id (-1004307013125), caption contains title + blog URL,
  photo attached as a direct file upload.
- **Not tested live**: an actual Telegram API call (sandbox network, as
  always). The request shape is Telegram's stable, documented sendPhoto
  form; if anything's off, error descriptions will say exactly what.

---

# Changelog

## OpenAI added as a second image provider (minimal-change)

Founder requested OpenAI image generation as an alternative to Gemini
(limited free credit, wanted a cheap option to try), explicitly asking
for the smallest possible change given the system was already fully
deployed and working end to end. This was genuinely small because of how
the AI-image system was architected in an earlier round: one isolated
module (`ai_image.py`) with exactly one public function, called
generically by `make_image.py`. Swapping/adding a provider only ever
needed to change what's behind that one function.

### Files touched (5, all small)

- **`config.py`**: added `IMAGE_PROVIDER` (default `"gemini"` — existing
  setups are completely unaffected unless this is explicitly changed) and
  `OPENAI_API_KEY`/`OPENAI_IMAGE_MODEL`/`OPENAI_IMAGE_SIZE`/`OPENAI_IMAGE_QUALITY`.
- **`ai_image.py`**: the existing Gemini logic was renamed to a private
  `_generate_gemini()` with no behavioral change, a new `_generate_openai()`
  was added alongside it, and the public `generate_ai_background()` — the
  only function anything else in the codebase calls — became a two-line
  dispatcher that picks between them based on `IMAGE_PROVIDER`.
- **`requirements.txt`**: added `openai`.
- **`.github/workflows/daily.yml`**: added one secret
  (`OPENAI_API_KEY`) and four variable pass-throughs to the existing
  `prepare` step's `env:` block. No new jobs, no new steps, no schedule
  changes.
- **`README.md`**: documented the new secret/variables and provider switch.

### Files NOT touched (by design)

`main.py`, `generate_content.py`, `make_image.py`, `publish_blog.py`,
`post_instagram.py` — zero changes. None of them know or care which
provider generated the background photo; `make_image.py` still just calls
`generate_ai_background(prompt)` exactly as before.

### A correction made before writing any code

DALL-E 2 and DALL-E 3 were removed from OpenAI's API on 2026-05-12 — the
originally-requested "DALL-E-style" integration would not have worked at
all if implemented against those model names. Verified current pricing
and model lineup before writing code rather than assuming training-data
knowledge was current, given how recently this specific change happened.
Implemented against `gpt-image-1-mini`, which is OpenAI's own documented
recommendation for high-volume, budget-conscious use — a direct match for
a twice-daily automated pipeline running on a small one-time credit.

### Verified with tests

- Confirmed the default `IMAGE_PROVIDER` remains `"gemini"` with no env
  var set, so upgrading this code changes nothing for an existing Gemini
  setup unless `IMAGE_PROVIDER=openai` is explicitly set.
- Tested all three dispatch outcomes: missing `OPENAI_API_KEY` raises a
  clear `ValueError` (not `SystemExit` — same subtlety fixed for Gemini in
  an earlier round applies identically here and was re-verified), an
  unrecognized `IMAGE_PROVIDER` value raises a clear error listing valid
  options, and the full `make_post_image()` fallback wrapper catches
  either failure and produces a valid PIL-rendered image instead of
  crashing — exactly the same unconditional safety net Gemini already had.
- Tested the OpenAI success path with a mocked response (a real small PNG,
  base64-encoded exactly as OpenAI's `b64_json` field would contain),
  confirming the decode logic correctly reconstructs a proper RGB PIL
  Image at the right dimensions.
- Re-ran the full 5-template + story regression suite (including the CTA
  pill position check) to confirm none of this touched anything in the
  rendering path.
- Workflow YAML re-validated for structural correctness after the env
  additions.
- **Not tested in this environment**: a live call to OpenAI's API — same
  sandbox network limitation as every previous round (this sandbox
  cannot reach PyPI to even install the `openai` package, let alone call
  the live endpoint). The request/response shape used
  (`client.images.generate(...)`, reading `.b64_json` or `.url` from
  `response.data[0]`) matches OpenAI's current documented SDK usage; if
  that shape has changed, `_generate_openai()` in `ai_image.py` is the one
  place to fix it, and the existing fallback guarantees a wrong/changed
  shape degrades to the PIL renderer rather than crashing the workflow.

---

# Changelog

## Critical fix: PIL renderer produced "nearly blank" images on Windows

### Root cause

`make_image.py` hardcoded Linux-only absolute font paths:
`/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf` and the regular
weight equivalent. These paths don't exist on Windows or macOS. When
`ImageFont.truetype()` failed to find them, the existing exception handler
silently fell back to `ImageFont.load_default()` — which **ignores the
requested point size entirely** and renders every piece of text at a tiny
fixed size, while pure geometry (panels, the CTA pill's background shape,
icon circle outlines) kept rendering at full correct size. That mismatch
— real layout, invisible text — is exactly what produced a "nearly blank
image with only a few tiny yellow marks visible," despite the content
package containing completely valid data. The rendering pipeline was
never actually broken; the font it silently substituted was.

### Diagnosis, not guesswork

Before changing anything, the failure was reproduced directly and
measured:
- A headline requested at a large point size, when forced through the
  same `load_default()` fallback path, rendered at **114px wide** on a
  1080px-wide canvas — about a tenth of the intended size.
- The real, previously-shipped code's exception handling was traced line
  by line to confirm this exact fallback was reachable and silent (no
  warning, no error, nothing in the logs to indicate anything had gone
  wrong) before writing a single line of fix.

### The fix

- **DejaVu Sans and DejaVu Sans Bold are now bundled directly in the
  repository** at `assets/fonts/`, under their existing permissive license
  (see `assets/fonts/LICENSE.txt`). `FONT_BOLD`/`FONT_REGULAR` in
  `make_image.py` now resolve to paths relative to the script's own
  location (`os.path.dirname(__file__)`), not an OS-specific system path.
  This makes rendering identical on Windows, macOS, Linux, and GitHub
  Actions runners — there is no longer any dependency on what fonts
  happen to be installed on whatever machine runs the code.
- **The fallback path is now loud, not silent.** If font loading ever
  fails for any reason (e.g. a fresh clone that's missing the assets
  folder), `_font()` now logs a clear one-time `ERROR` naming the exact
  path that failed and stating plainly that every image will render with
  wrong text sizing until it's fixed — instead of quietly substituting a
  broken font and letting the symptom (a blank-looking image) obscure the
  cause. It also now tries `ImageFont.load_default(size=...)` first on
  Pillow versions that support an explicit size for the default font
  (10.1+), so even a genuinely missing bundled font degrades to "readable
  but wrong typeface" rather than "invisible," on top of the loud logging.

### Verified

- Directly measured the fix: the same headline that rendered at 114px
  under the broken fallback now measures **3380px** at the same requested
  size — confirming the actual root cause is resolved, not just
  papered over.
- Measured the real, final, pipeline-generated image (not a synthetic
  test): the headline spans **895px, or 82.9% of the 1080px canvas
  width** — a normal, readable headline, matching what every template was
  always supposed to produce.
- Re-ran the full 5-template + story regression suite (including the CTA
  pill position check from the previous round) — all still pass with the
  new bundled fonts.
- Confirmed the loud-failure diagnostic actually fires: pointed
  `FONT_BOLD`/`FONT_REGULAR` at a genuinely nonexistent path and verified
  a clear `ERROR`-level log line appears, naming the broken path.
- Confirmed `.gitignore` does not exclude the new `assets/fonts/`
  directory — checked with a real `git add` / `git ls-files` dry run,
  since a font that's bundled but never actually committed would silently
  recreate the exact same bug on a fresh clone.
- Full pipeline dry run re-executed end-to-end; the generated image file
  itself (not a synthetic test render) was measured and confirmed correct.

### Not addressed in this round (out of scope per this request)

- The `429 RESOURCE_EXHAUSTED` error from Gemini's image model
  (`gemini-2.5-flash-preview-image`, limit: 0) was reported alongside this
  bug but is a separate, unrelated issue — it indicates the API key's
  project has zero quota allocated for that specific image model, which
  is an account/billing configuration matter on Google's side, not a code
  bug. The `USE_AI_IMAGES` fallback already handles this correctly by
  design: on that 429, the pipeline logs a warning and falls back to the
  PIL renderer automatically, which is why this font bug was even visible
  in the first place — the fallback path was doing its job of being used,
  it just wasn't yet correct.

---

# Changelog

## Optional AI-generated photo backgrounds (Gemini 2.5 Flash Image)

Integrated real AI image generation as an opt-in alternative to the PIL
renderer, per the founder's request after comparing free code-only
rendering against a photographic reference. The existing architecture
(topic selection, scoring, blog, voting, Instagram publishing) is
completely untouched — this only touches the image-rendering step, and
only when explicitly turned on.

### A real bug found and fixed before building on top of it

While preparing to reuse `_cta_pill` and `_footer` for the new AI-overlay
compositor, testing turned up a genuine regression from the supersampling
round two versions ago: `_cta_pill` computed its position from
`img.width`/`img.height` on the actual Image object. After supersampling
was added, that object is 4x larger than logical coordinates — so those
already-scaled values were being scaled a *second* time by the
`_ScaledDraw` proxy, pushing the CTA pill completely off-canvas. Verified
with a precise pixel check: zero yellow pixels found at the pill's
intended location before the fix, 200/200 after.

This had been silently broken since the supersampling round — the tests
run at the time checked *that* a pill-shaped yellow region existed
somewhere via a full-image scan, but never checked it was specifically at
the *correct* logical position. Fixed by having `_cta_pill` take an
explicit logical `canvas_size` tuple instead of reading it from a
(possibly scaled) Image object, matching the pattern `_header`/`_footer`
already used correctly. Re-ran the full 5-template + story regression
suite after the fix; all pass with the CTA pill in the exact right place.

### What's new

- **`config.py`**: `USE_AI_IMAGES` (default `false`) and
  `GEMINI_IMAGE_MODEL` (default `gemini-2.5-flash-image`). Off by default
  since this path has a real per-image cost, unlike the free PIL renderer.
- **New module `ai_image.py`**: `generate_ai_background(prompt)` calls
  Gemini's image-output model and returns a PIL Image, or raises. It
  never silently degrades — degrading is the caller's job, so this module
  stays simple and its one failure mode stays obvious. The prompt always
  gets an appended style suffix enforcing editorial/cinematic/dark+yellow
  aesthetics and — critically — explicitly forbidding any text, numbers,
  logos, or watermarks in the generated image, since image models reliably
  mangle rendered text. All real text is added afterward with PIL.
- **`make_image.py`**: the old `make_post_image()` is renamed
  `_make_post_image_pil()` unchanged. A new `make_post_image()` wraps it:
  when `USE_AI_IMAGES` is on, it tries `_make_post_image_ai()` first and
  falls back to the PIL path on **any** exception, logging a warning; when
  off, it calls the PIL path directly with no API call attempted at all
  (verified with a spy that confirms the AI function is never even called
  when the flag is off).
- **`_composite_ai_overlay()`**: takes the generated photo, crops it to
  the exact 1080x1350 target with `ImageOps.fit` (handles whatever
  dimensions the model actually returns), adds a dark gradient scrim at
  the top and bottom for text legibility over an arbitrary photo, then
  reuses the *exact same* `_kicker`, `_draw_rich_text`, `_footer` (which
  itself calls the now-fixed `_cta_pill`), and `_brand_lockup` helpers the
  PIL templates use — drawn onto a transparent supersampled layer and
  alpha-composited over the photo. Both rendering paths share one visual
  identity instead of two independently-maintained ones.
- **Deliberately simpler overlay than the full templates**: just kicker +
  headline + CTA + logo, magazine-cover style — not the icon-badged
  bullet-point layout, since a busy chart doesn't sit well on top of a
  photo. This is a real, visible product tradeoff (the AI path loses the
  "read both sides in 3 seconds" bullet content), stated here rather than
  silently decided.
- **`main.py`**: one line changed — `image_prompt=package.get("image_prompt")`
  is now passed through to `make_post_image()`, so the AI path gets the
  real, topic-specific prompt Gemini already generates during elaboration,
  instead of a generic fallback built from just the kicker and headline.
  This is the one necessary touchpoint outside `make_image.py`/`ai_image.py`;
  it's backward compatible (`image_prompt` defaults to `None`, in which
  case a generic prompt is still constructed) and no other module needed
  any change — `publish_blog.py`, `post_instagram.py`, and
  `generate_content.py`'s callers are all completely untouched.
- **Output paths unchanged.** Both rendering paths save to the exact same
  `out_path` the pipeline already expects — `main.py`'s file naming,
  pruning, and jsDelivr URL construction needed zero changes beyond the
  one prompt pass-through above.

### Found and fixed while testing this round (in `ai_image.py`)

- Initially used `utils.require_env()` to check for a missing API key —
  but that helper deliberately raises `SystemExit` for legitimate top-level
  fail-fast checks elsewhere in the codebase, and `SystemExit` is **not**
  a subclass of `Exception`. It would have passed straight through
  `make_post_image()`'s `except Exception` fallback wrapper and crashed
  the whole pipeline on a missing key — exactly the failure mode
  `USE_AI_IMAGES`'s fallback is supposed to prevent. Caught via a direct
  test (confirmed `issubclass(SystemExit, Exception)` is `False`) before
  it shipped. Fixed by raising a plain `ValueError` instead.

### Verified with tests

- The `SystemExit`-vs-`Exception` bug above, reproduced and confirmed
  fixed: `USE_AI_IMAGES=true` with an empty `GEMINI_API_KEY` now correctly
  retries, logs a warning, and falls back to a valid 1080x1350 PIL image
  — does not crash.
- `USE_AI_IMAGES=false` (the default) confirmed to never even call the AI
  function — verified with a spy wrapping `ai_image.generate_ai_background`
  that recorded zero calls.
- AI success path tested with a mocked background image (a random-noise
  placeholder standing in for a real photo, since this sandbox can't reach
  the live API): confirmed the CTA pill and kicker both composite
  correctly on top of the photo at the exact expected pixel locations.
- A second failure mode (a generic exception simulating a safety block or
  malformed response, not just a missing key) also confirmed to fall back
  cleanly.
- Full pipeline dry run re-executed end-to-end with `USE_AI_IMAGES=false`
  to confirm the default (safe, free) path is completely unaffected by
  everything added this round.
- **Not tested in this environment**: an actual live call to Gemini's
  image model — same sandbox network limitation as every previous round.
  The exact response shape for Gemini image-output models (inline_data
  parts on a generate_content response) is based on Google's documented
  pattern for multimodal Gemini output as of this writing; if that shape
  has changed, `ai_image.py` is the one place to fix it, and the fallback
  guarantees a missing/wrong shape degrades to the PIL renderer rather
  than crashing regardless.

---

# Changelog

## Anti-aliased rendering: supersampling added to fix "plain text" appearance

After the icon/highlighting upgrade, the founder reported the images
still looked like "plain text," not matching the visual polish of a
reference design. The honest root cause: **PIL draws with zero
anti-aliasing at native resolution** — every circle, line, and letter edge
is a hard jump between two colors, which reads as flat and unpolished no
matter how good the layout or icon choices are. This is a rendering
technique gap, not a layout or content gap, so it needed a rendering fix,
not more design tweaking.

Clarified two possible directions with the founder first, since one path
(real AI-generated photographic/illustrated imagery) has an ongoing
per-image cost and the other (better code-only rendering) is free — didn't
want to silently pick the paid path. Founder chose to max out the free
path first.

### What changed

- **Supersampling added to every rendered image.** Each template now
  renders internally at 4x the target resolution, then downsamples with
  LANCZOS filtering before saving — the standard technique for
  anti-aliased graphics from vector-style drawing. This is what actually
  produces smooth circle edges, clean text, and non-jagged lines, instead
  of the hard-edged shapes PIL draws by default.
- **Implemented via a transparent scaling proxy (`_ScaledDraw`)** rather
  than rewriting the ~300 lines of existing layout code. Every existing
  call site (`d.line(...)`, `d.ellipse(...)`, `d.text(...)`, etc.) keeps
  using the exact same logical/1x coordinates and font sizes as before;
  the proxy multiplies coordinates by the scale factor before the real
  draw call, and — critically — divides `textlength()` results back down
  to logical units so all the existing text-wrapping math keeps working
  unmodified. This kept the change contained and low-risk instead of
  touching every render function.
- `_font()` now loads fonts at 4x the requested size (real glyph
  resolution to downsample from, not a stretched bitmap).
- `_new_canvas()`'s background glow is now rendered directly at the
  supersampled resolution so it composites correctly with everything else.

### Verified with a real before/after measurement, not just "looks better"

- Rendered the same circle shape twice — once through the new supersampled
  pipeline, once with plain unscaled PIL — and compared the actual pixel
  values across the edge:
  - **Without supersampling**: background→circle transition is `25, 25,
    ..., 25, 192, 192, ..., 192` — a hard 2-level jump. This is the
    "plain text" look being reported.
  - **With supersampling**: the same kind of edge in the real rendered
    output shows `25, 29, 21, 130, 203, 192, ...` — 11 distinct
    intermediate levels, a genuine smooth gradient. This is a real,
    numeric before/after, not a subjective impression.
- Re-ran the emphasis-highlighting pixel test from the previous round
  through the new scaling proxy to confirm it still works unchanged
  (289 yellow pixels, 2520 white pixels found in a test headline).
- Re-ran the full 5-template stress test (icons + emphasis + extreme-length
  text combined) — all pass, no crashes introduced by the proxy.
- **Performance check**: 4x supersampling means 16x the pixels to render
  before downsampling. Measured at ~1.3 seconds per image — completely
  fine for a pipeline that renders 2 images/day.
- Full pipeline dry run re-executed end-to-end with the new renderer wired
  in; no changes needed in `main.py` or `generate_content.py` — the
  proxy's transparency paid off exactly as intended.

### Honest limitation this does NOT solve

Supersampling fixes *jaggedness* — it cannot add photographic or
illustrated imagery (like the robot artwork in the founder's reference).
That gap is real and was explicitly discussed: closing it fully requires
a paid AI image-generation API, which is a separate, deliberate decision
still open for later, not something this round attempted or silently
worked around.

---

# Changelog

## Visual upgrade: icon badges + two-tone keyword highlighting

The founder shared a reference design (a 6-slide carousel with much richer
visual polish: custom line-art icons in circular badges, headlines with
one key word highlighted in yellow, better composition). The carousel
format itself was explicitly kept out of scope — the architecture stays
single-image, per the previous round — but the *visual craft* of that
reference was worth adopting. Clarified this trade-off with the founder
directly before rebuilding, since carousel-vs-single-image had already
flipped once and a silent revert would have undone real, tested work.

### What changed

- **Every bullet point now carries a real icon**, not a plain dot. The
  model picks the closest-fitting icon per point from a fixed 20-icon
  vocabulary (`ICON_SET` in `config.py`: gear, person, chart, pie, heart,
  globe, calendar, money, book, check, cross, warning, arrow_up,
  arrow_down, phone, bank, fuel, shield, scale, clock). All 20 are drawn
  as simple line-art circles directly in PIL — no icon font, no external
  asset, no image-gen API — and individually tested to confirm each
  renders visible content without crashing.
- **Two-tone keyword highlighting in headlines.** Every headline-style
  field (question/title/event/statement/belief/reality) can wrap one or
  two words in `**double asterisks**`, which render in the brand's yellow
  accent while the rest of the headline stays white — e.g. "Will AI
  **replace** most jobs?" This reuses the same markdown-bold convention
  the model already handles reliably in article text, rather than
  inventing a new markup scheme.
- **Kicker gets an underline accent** beneath the tracked-uppercase label,
  matching the reference's styling.
- **CTA pill gets a small speech-bubble glyph** after the text, matching
  the reference's chat-icon CTA treatment.
- **Bullet point layout redesigned**: icon badge on the left, text on the
  right, thin divider lines between rows — replacing the old plain-yellow-
  dot bullet list.

### Reliability work behind the visual upgrade

- **Schema change, defended at two layers.** Points are now
  `{"text": ..., "icon": ...}` objects instead of plain strings. Rather
  than trusting the model to always send a valid icon name:
  1. `generate_content.py`'s new `_sanitize_points_fields()` normalizes
     every point after generation — an icon outside the allowed 20-item
     set is replaced with a neutral fallback (`check`), and even a
     legacy/malformed plain-string point (instead of an object) is
     recovered into the correct shape rather than burning a retry.
  2. `make_image.py`'s icon renderer has its own independent fallback for
     an unrecognized name at draw time — defense in depth, since a bug
     anywhere upstream shouldn't be able to crash a render.
  Both fallback paths are unit tested directly, along with the normal
  valid-icon path and the legacy-plain-string path.
- **Found and fixed a real bug before it shipped**: the initial
  `arrow_up`/`arrow_down` icon geometry used a confusing sign-flip
  expression (`cy - r * 0.55 * -flip * -1`) that doesn't compute the
  intended coordinates. Rewritten as plain if/else geometry per direction
  and re-verified.
- **Emphasis highlighting verified with an actual pixel test**, not just
  "it should work": rendered "Will AI **replace** most jobs?" in
  isolation and confirmed both yellow pixels (over 4,000) and white pixels
  (over 13,000) are present in the same rendered headline — proof the
  highlighted word and the base text are genuinely different colors, not
  just correct-looking code.
- Combined stress test: all 5 templates rendered together with icons,
  multi-word emphasis, and deliberately extreme-length text in the same
  pass — no crashes.
- Full pipeline dry run re-run end-to-end with the upgraded renderer
  wired in, confirming `main.py` and `generate_content.py` still
  integrate correctly with no changes needed on the orchestration side.

### Not changed

- The single-image, 5-template architecture from the previous round is
  unchanged — this was a rendering-quality upgrade within that
  architecture, not a structural change. Topic selection, the blog,
  click-to-vote, and Instagram publishing are all untouched.
- Deliberately did NOT introduce the reference's green/red YES/NO speech
  bubble coloring — kept the single-yellow-accent brand rule established
  in an earlier round rather than silently reintroducing a second/third
  color. Worth knowing this was a judgment call, not an oversight, in
  case the founder wants that color treatment specifically.

---

# Changelog

## Carousel replaced with single-image, 5-template post system

The brief was direct: 6-slide carousels are too much friction for
engagement. A user should understand the topic, both sides, and know what
to comment within 3 seconds of seeing ONE image. This is an architectural
simplification, not an additive feature — the carousel system is fully
removed, not kept as an option alongside the new one.

### What changed

- **Brand tagline** changed to "The Nation Decides" (from "Learn First.
  Vote Later.") — flows automatically everywhere via `config.py`'s single
  source of truth, including the blog, which was specifically fixed in an
  earlier round to import from config rather than hardcode its own copy.
  That earlier fix paid for itself immediately here: zero blog template
  edits were needed for the tagline change.
- **`cover` + `carousel` + `story` schema replaced with one `post` object**:
  `{template_type, kicker, content}`, where `content`'s shape depends on
  which of 5 templates was chosen. Schema is smaller than the old 6-slide
  carousel schema, which should also mean fewer malformed-JSON retries in
  practice.
- **Five reusable templates**, matching the brief exactly:
  - `debate` — question, YES vs NO, 3 points each
  - `comparison` — option A vs option B, 3 points each
  - `prediction` — future event, bull case vs bear case
  - `hot_take` — one bold statement + supporting points (single column,
    structurally different from the two-sided templates on purpose)
  - `fact_vs_myth` — common belief vs. the actual reality
- **The model picks the template, not the config.** Stage 2's prompt now
  describes all 5 shapes in plain prose with concrete field names, and
  asks Gemini to choose whichever fits the specific topic — a fuel-price
  regulation might render as `debate`, a market rumor as `prediction`, a
  provocative one-liner as `hot_take`. This wasn't hardcoded per category;
  it's a live decision made per topic.
- **CTA text is deterministic per template, not model-generated.** After
  validation, `post["cta"]` is overwritten with the fixed string for that
  template type (`COMMENT YES OR NO`, `WHICH WOULD YOU CHOOSE?`, etc.),
  regardless of what the model wrote. This is the same "don't trust the
  model for something that should be exactly consistent" principle applied
  to the risk-scoring math in an earlier round — a template's CTA is part
  of its design, not creative content.
- **Strict per-template content validation.** `TEMPLATE_CONTENT_SCHEMA`
  defines the exact required fields for each of the 5 shapes. A response
  claiming `template_type: "hot_take"` but missing `supporting_points` is
  rejected and retried, not rendered half-empty. Verified with a test that
  a genuinely malformed hot_take response fails all 3 retries and raises
  clearly, and that a valid one for each of the 5 types passes and gets
  its CTA injected correctly.
- **`make_image.py` rewritten**: the old cover/carousel renderers are gone,
  replaced by one dispatch function (`make_post_image`) and 5 private
  renderers, one per template, sharing the same chrome helpers (kicker,
  brand lockup, CTA pill) as before. `prediction`'s bull/bear split uses
  ▲/▼ glyphs rather than green/red to keep the single-accent-color brand
  rule intact even for a template that's conceptually bullish/bearish.
- **Story generation simplified.** Rather than asking Gemini for a
  separate `story` object (extra schema surface for no real benefit), the
  story headline is now derived in Python directly from whichever content
  field the chosen template already produced (`question` for debate,
  `statement` for hot_take, etc.) via a small `headline_for_story()`
  lookup. One less thing that can be malformed.
- **`main.py` and `post_instagram.py`**: single-image publish path
  (`post_single_to_instagram`, already present from an earlier round) is
  used again instead of the carousel path. `post_carousel_to_instagram`
  is left in `post_instagram.py` unused rather than deleted, in case
  carousels are ever wanted again — dead code that costs nothing.
- **Image pruning simplified** to match — one image pattern (`post-*.jpg`,
  `story-*.jpg`) instead of needing to handle a nested carousel directory.

### Verified with tests

- All 5 templates individually validated end-to-end: fake Gemini responses
  for each type pass strict content-shape validation and produce the
  correct deterministic CTA.
- A deliberately malformed `hot_take` (missing `supporting_points`) is
  correctly rejected across all 3 retry attempts and raises a clear error.
- All 5 templates rendered and checked programmatically: correct 1080×1350
  dimensions, real pixel variance (not blank frames).
- **Targeted pixel-region verification** (new this round, not just
  luminance variance): sampled the exact expected coordinates for the
  kicker label, the CTA pill fill, the brand lockup square, and the
  headline text, confirming each renders in its expected color at its
  expected position. One early check briefly "failed" because it sampled
  directly through the CTA button's own text rather than the fill next to
  it — a flawed test, not a rendering bug — caught and corrected before
  being reported.
- Stress-tested all templates with deliberately extreme-length headlines,
  statements, and bullet points: no crashes.
- Full pipeline dry run (`prepare` → single image + story render → blog
  publish → `publish` → Instagram call) executed end-to-end, confirming
  the jsDelivr image URL is built correctly and the package contains every
  expected field.
- Image pruning re-tested against the new simpler filename pattern.
- **Not tested in this environment**: a live Gemini call or live Instagram
  publish, for the same sandbox-network reasons as previous rounds. Your
  next real `workflow_dispatch` run is the actual test of this round's
  prompt and schema changes.

### Not changed

- Topic selection scoring (weights, `news_anchor` gate, brand-safety gate)
  from the previous round is untouched — this was a post-format change,
  not a topic-selection change.
- The blog, click-to-vote system, and Supabase schema are untouched.

---

# Changelog

## Topic selection reworked: recent news over evergreen topics

The brief changed from "engagement above all, evergreen is fine" to
"must feel like something Indians are already discussing today." This
was a real philosophy change, not a wording tweak, so the scoring and
prompt were reworked accordingly rather than patched.

### What changed

- **`trend_momentum` is now the highest-weighted scoring dimension**
  (0.25, up from 0.10 — previously the lowest weight). `comment_potential`
  stays a close second (0.22) since a topic can be current and still be
  boring. Weights still sum to exactly 1.0 (tested).
- **New hard gate: `news_anchor`.** Every candidate must now come with a
  one-line citation of the actual recent event, policy, or change it's
  tied to. Candidates with an empty or missing `news_anchor` are excluded
  from ranking entirely — this is what actually enforces "feels like
  today," rather than trusting the model's own `trend_momentum` self-score
  in isolation (self-reported recency scores are easy for a model to
  inflate without a concrete citation forcing it to justify the number).
- **Explicit priority category list added to the prompt**: current
  news/breaking events, government regulations and policy changes,
  consumer issues, technology changes, fuel prices and energy policy,
  banking rules and UPI/payment changes, taxation/GST changes, jobs and
  layoffs, education and exams, transportation policy, and viral social
  debates from the last 7 days — matching the brief's list directly.
- **Good/bad calibration examples updated**: `GOOD_TOPIC_EXAMPLES` now
  includes E20 fuel labeling, UPI limit changes, GST changes, NEET/JEE
  controversies, AI layoffs, and work-from-office mandates. A new
  `EVERGREEN_TOPICS_TO_AVOID` list (hustle culture, dating apps, tipping,
  etc.) is shown to the model explicitly as the wrong kind of answer, not
  just omitted.
- Added a light sensitivity instruction for topics that touch personal
  themes (e.g. exam stress from NEET/JEE) to stay at the policy level
  rather than dramatizing individual hardship — a natural risk given the
  new topic categories skew closer to real people's real problems than
  the old evergreen list did.

### Verified with tests

- Weight sum still equals 1.0; `trend_momentum` confirmed to be the
  highest-weighted dimension.
- **The critical test**: an evergreen topic ("Is hustle culture toxic or
  necessary?") given a perfect 10/10 on every engagement dimension, but
  no `news_anchor`, was correctly excluded — a real, current, lower-raw-
  scoring topic ("Should petrol pumps clearly label E20 fuel blends?")
  won instead. This is the exact behavior the brief asked for, and it's
  now mechanically enforced, not just requested in prompt wording that an
  LLM could drift away from over time.
- Confirmed the `news_anchor` gate and the pre-existing `brand_safety`
  gate compose correctly when both would otherwise exclude different
  candidates in the same batch.

### Not changed

- The two-stage pipeline structure, the brand-safety gate, same-day
  overlap prevention, and the elaboration/rendering stages are untouched.
  This was a scoring-and-prompt change, not an architecture change.

---

# Changelog

## Engagement-optimized topic selection, premium visual system, twice-daily posting

### 1. Topic selection now optimizes for engagement, not importance

- **Two-stage pipeline** replaces the old single-call "pick and write"
  approach: `select_topic()` brainstorms and scores 20 candidates;
  `generate_full_package()` elaborates only the winner. Smaller JSON per
  call, easier to debug, and the scoring becomes independently inspectable
  instead of a black box inside one big prompt.
- **7-dimension scoring**: relatability, opinion_strength, comment_potential,
  discussion_potential, shareability, trend_momentum, brand_safety — each
  0-10, requested directly from Gemini for all 20 candidates.
- **Scores are recomputed in Python, not trusted from the model.** The
  weighted total (`SCORE_WEIGHTS`, weighted toward comment/discussion
  potential per the brief) is calculated deterministically and the ranking
  is redone in Python. Verified with a test where a candidate scored a
  perfect 10/10 on every engagement dimension but 2/10 on brand safety —
  it's correctly excluded regardless of how high its other scores were.
- **Brand safety is a hard gate (≥8/10), not just one score among many.**
  Anything below the threshold is removed from the eligible pool entirely
  before ranking, not merely down-weighted.
- **Every day's full 20-candidate breakdown is saved** to
  `output/topics/<date>-<slot>.json` and committed — this is explicit,
  auditable output, not a discarded intermediate.
- **Anti-repetition now covers same-day overlap.** The evening run reads
  the blog manifest for anything already published *today* (the morning
  post will already be committed by then) and excludes it, in addition to
  the existing 15-post rolling window for general variety.

### 2. Premium visual system replaces the old multi-color Pillow renderer

- Old system: 5 different colored palettes keyed by topic category (tech
  = purple, economy = green, etc.) — visually inconsistent from post to
  post, more social-template than publication.
- New system: **one consistent dark-and-yellow editorial identity** across
  every asset, the way a real publication's visual identity doesn't change
  story to story. All colors live in `config.py`, not scattered across
  render code.
- Three asset types now generated per post, up from one:
  - **Cover** (1080×1350) — question, neutral YES/NO split, comment CTA.
  - **Carousel** (6× 1080×1350) — question, why-yes, why-no, key facts,
    re-ask, and a final "comment READ" growth slide. This is the asset
    that actually gets posted to the Instagram feed.
  - **Story** (1080×1920) — with a reserved blank zone for manually adding
    Instagram's native Poll sticker (see Known Limitations for why that
    step can't be automated).
- **AI image-generation prompts** are also produced for every asset
  (layout, typography, composition, palette, branding and CTA placement,
  mobile optimization) — saved in the package for future use with a
  generative image model, even though the current pipeline renders with
  PIL directly.
- All three renderers share common chrome helpers (brand lockup, kicker
  label, slide-index badge) so the brand identity only needs to change in
  one place, not three.
- Stress-tested with deliberately extreme-length headlines, options, and
  carousel points to confirm no layout overflow or crash; verified
  rendered output has real visual variance (not blank/degenerate frames)
  and the expected yellow-accent pixel presence.

### 3. Two posts a day, non-overlapping topics

- `main.py` now takes a required `<morning|evening>` slot argument for
  both `prepare` and `publish`. All filenames (images, blog slugs, debug
  JSON) are tagged with both the date and the slot, so the two runs never
  collide.
- **Overlap prevention**: the evening run's topic-selection prompt
  excludes anything already published today (see topic-selection section
  above) — verified with a test that seeds a morning post in the blog
  manifest and confirms it's correctly read back and excluded.
- Workflow updated to two cron schedules (9:00 AM and 6:00 PM IST) feeding
  into a `determine-slot` job that resolves which slot triggered the run
  (from `github.event.schedule`) or reads it from a manual
  `workflow_dispatch` input — `workflow_dispatch` now lets you pick
  morning or evening explicitly for testing, rather than always running
  the same thing.

### 4. Instagram publishing: carousel support added

- New `post_carousel_to_instagram()` in `post_instagram.py`: creates N
  child media containers (`is_carousel_item=true`), waits for each to
  process, attaches them to a parent `CAROUSEL` container, then publishes.
  Reuses the same retry/error-handling helpers as the existing single-image
  path (`_wait_for_processing` now explicitly checks for `ERROR` status
  for both paths, unchanged from the previous review).
- **Product decision, stated explicitly rather than silently made**: only
  the carousel is auto-posted to the feed. The cover image is still fully
  generated (useful as a standalone shareable asset, e.g. for the blog
  header) but not separately posted, to avoid two feed posts about the
  same topic on the same day. This is documented in README's Known
  Limitations so it's a visible tradeoff, not a hidden one.

### 5. Bug fixed during this round: brand definition duplication

- `publish_blog.py` had its own hardcoded `BRAND_NAME`/`BRAND_TAGLINE`
  constants, separate from `config.py`'s. A future rebrand would have had
  to remember to update both, and they could silently drift apart (this
  is exactly the kind of duplication that caused real confusion in the
  previous OpinionVerse → India Thinks rename). Fixed by importing both
  from `config.py` — one source of truth.

### 6. Tagline reverted per this round's spec

- `BRAND_TAGLINE` changed from "Think. Vote. Compare." back to
  "Learn First. Vote Later." across config, blog templates, and all
  generated captions.

## Testing performed in this round

- Weighted-scoring math unit tested: weight sum equals 1.0, a perfect
  10-across-the-board candidate scores exactly 10, higher-weighted
  dimensions correctly outrank lower-weighted ones, missing dimensions
  default safely to 0 rather than crashing.
- Full `select_topic()` pipeline tested against simulated Gemini output:
  confirmed the brand-safety gate excludes a topic that scored perfectly
  on every engagement dimension but failed brand safety, and that the
  genuinely-best safe topic wins.
- Same-day overlap exclusion tested: seeded a fake blog manifest entry
  dated today, confirmed `_todays_titles()` correctly retrieves it for
  exclusion while `_recent_titles()` correctly includes older entries too.
- Image rendering stress-tested with extreme-length headlines, options,
  and carousel bullet points — no crashes, no exceptions.
- Rendered images verified programmatically (dimensions, luminance
  variance, yellow-accent pixel sampling) to confirm real content is being
  drawn, not blank frames.
- Full pipeline dry run (`prepare` → asset rendering → blog publish →
  `publish` → Instagram call) executed end-to-end against simulated Gemini
  responses and a mocked Instagram API, confirming: all expected output
  files are created, the package JSON contains every expected key, and the
  jsDelivr carousel URLs are built correctly from `GITHUB_REPOSITORY`.
- Image pruning re-tested against the new nested `output/carousel/`
  directory structure and slot-tagged filenames.
- **Not tested in this environment**: a live Gemini API call (no PyPI/API
  network access in this sandbox) and a live Instagram carousel publish.
  Treat your first real `workflow_dispatch` run as the true end-to-end
  test — the two-stage JSON schema is larger than before, so if Gemini's
  output doesn't validate, paste the exact error and it'll get fixed fast.

## Manual setup steps still required

Same as the previous round (GitHub repo + Pages, Gemini key, the Meta/
Instagram 30-minute setup, Supabase schema, secrets) — see README.md
Steps 1-7. Nothing new to configure beyond what's already there; the
`workflow_dispatch` input now lets you test each slot independently
without waiting for the actual cron time.

---

# Changelog

## Rebrand: OpinionVerse → India Thinks

- Brand name changed everywhere: image, blog title, blog index, article
  pages, README, GitHub Actions workflow name, git commit author.
- New tagline: "Think. Vote. Compare." (was "Learn First. Vote Later.").
- Repo name convention updated from `opinionverse-bot` to `india-thinks-bot`
  throughout the README's setup instructions.
- localStorage keys renamed (`ov_vote_*` → `it_vote_*`) — cosmetic, but
  avoids confusion if you ever look at browser storage while debugging.

## Provider migration: Anthropic Claude → Google Gemini

- `requirements.txt`: removed `anthropic`, added `google-genai`.
- `config.py`: `ANTHROPIC_API_KEY` replaced with `GEMINI_API_KEY`; added
  `GEMINI_MODEL` (default `gemini-2.5-flash`) as an env-configurable setting
  so the model can be changed later without a code edit.
- `generate_content.py`: rewritten to use `google.genai.Client` with the
  `google_search` grounding tool (Gemini's equivalent of Claude's web
  search tool) instead of Anthropic's `web_search_20250305` tool.
- GitHub Actions workflow: `ANTHROPIC_API_KEY` secret replaced with
  `GEMINI_API_KEY`.

## Bugs found and fixed

1. **XSS-shaped bug in blog pages (security).** AI-generated text (titles,
   poll questions, article body) was inserted into HTML with no escaping.
   Any `<`, `>`, `&`, or `"` in the model's output — which happens
   incidentally, not just adversarially, e.g. "cost < benefit" — would
   break rendering or, worst case, inject markup. Fixed by routing all
   AI-generated text through `html.escape()` before insertion, and
   verified with an adversarial test using literal `<script>` tags and
   quotes in the input.
2. **Unsanitized slug used as a filename, URL path, and JS string literal.**
   `topic_slug` came straight from the model with no validation. A slug
   containing a quote character would have broken the embedded
   `const POLL_ID = "...";` JavaScript on the vote page; spaces or unicode
   would have produced broken URLs. Fixed with a new `slugify()` utility
   that strips anything outside `a-z0-9-` before the slug is used anywhere.
3. **Naive JSON extraction (`str.find` / `str.rfind`) was fragile.** The
   old code took "first `{`" to "last `}`" as the JSON boundary. If the
   model added trailing commentary after the JSON object (something both
   Claude and Gemini occasionally do despite instructions), or the content
   itself contained braces, extraction could silently grab the wrong
   span. Replaced with `json.JSONDecoder().raw_decode()`, tried at every
   `{` position until one parses successfully — this correctly ignores
   leading/trailing junk text and unit-tested against 6 edge cases
   including brace characters inside the article text itself.
4. **Instagram polling loop didn't check for `ERROR` status.** If
   Instagram failed to process the image, the old code looped silently for
   50 seconds, then attempted to publish anyway, producing a confusing
   generic failure. Now checks for `status_code == "ERROR"` explicitly and
   raises a clear `InstagramPublishError` immediately.
5. **No caption length guard.** Instagram rejects captions over 2200
   characters outright. Added `_truncate_caption()` so a verbose Gemini
   response degrades gracefully instead of failing the whole post.
6. **Unreliable image host for Instagram fetches.** The old code built
   image URLs from `raw.githubusercontent.com`, which is not intended as a
   hotlinking CDN and has a history of inconsistent content-type headers
   for third-party fetchers (including Meta's crawler). Switched to
   jsDelivr's GitHub CDN (`cdn.jsdelivr.net/gh/...`), which is built for
   this exact use case. Because each day's image has a unique filename,
   jsDelivr's edge caching can never serve a stale image for that URL.
7. **Unbounded repo growth.** Every day's poll image was committed and kept
   forever, with nothing ever deleting old ones. Added `_prune_old_images()`
   in `main.py`, run automatically each day, deleting images older than
   `IMAGE_RETENTION_DAYS` (default 3) — safe because Instagram only needs
   the source file transiently to fetch it once.
8. **A stray line of debugging cruft in `_md_to_html`** (introduced and
   caught during this review, not present in a shipped version) would have
   stripped every `**bold**` marker from articles instead of converting it
   to `<strong>`. Removed before it ever reached you.

## Reliability improvements

- **Retry with exponential backoff** (`utils.retry`) applied to: Gemini
  generation (3 attempts) and both Instagram Graph API calls (3 attempts
  each). Network flakiness and transient 5xx responses no longer fail the
  whole day's post.
- **Structured logging** (`utils.setup_logging`) replaces bare `print()`
  calls throughout, with levels (INFO/WARNING/ERROR) and timestamps, so
  GitHub Actions logs are actually diagnosable instead of a flat text wall.
- **Fail-fast config validation** (`utils.require_env`) — missing secrets
  now raise an immediate, specific error ("Missing required configuration:
  GEMINI_API_KEY") instead of an obscure downstream exception three calls
  deep.
- **`main.py` wraps both pipeline commands in a top-level try/except** that
  logs the failure clearly before re-raising, so the GitHub Actions run
  fails loudly and specifically instead of silently or cryptically.
- **A failed workflow run now automatically opens a GitHub Issue** in your
  repo (via `actions/github-script`), so a solo founder doesn't have to
  remember to check the Actions tab every day.
- **GitHub Actions workflow hardening**:
  - `timeout-minutes: 15` — a hung step can no longer run indefinitely.
  - `concurrency` group prevents a manual trigger and the scheduled run
    from overlapping and corrupting each other's git state.
  - `git pull --rebase` before `git push`, with one retry — avoids a
    failed push if two runs' commits land close together.
  - `pip install` now uses the `actions/setup-python` pip cache for faster,
    more consistent runs.

## Content quality improvements

- Prompt now explicitly asks for topics with **broad, gut-reaction appeal**
  and gives 8 example questions to calibrate tone and scope, steering away
  from niche regulatory/technical topics that would get little engagement.
- Prompt reads your own blog's recent post titles (from `blog/manifest.json`)
  and instructs the model not to repeat similar topics — automatic
  anti-repetition with zero extra infrastructure.
- Brand-safety exclusion list made explicit and specific: no religion, no
  active elections or named politicians, no communal/caste angles, no
  personal attacks on named private individuals, no unverified medical
  claims (was previously just "religion, elections, communal issues").
- Added two more topic categories (`society`, `environment`) with matching
  image palettes and icons, so topics outside technology/economy/education
  get a purpose-built visual instead of falling back to a generic default.

## Voting improvements

- **Duplicate-vote mitigation**: a persistent anonymous `voter_id` (UUID)
  is generated per browser and sent with every vote. The Supabase table
  now has a `UNIQUE(poll_id, voter_id)` constraint, so network retries or
  accidental double-submits can no longer create duplicate rows. This is
  documented honestly as best-effort, not fraud-proof — true dedup would
  require login or IP-based server logic, which is a deliberate scope
  decision for a no-login voting page.
- **Vote counting now scales.** The old implementation downloaded every
  vote row and counted them in JavaScript — fine at dozens of votes, slow
  and wasteful at thousands. Replaced with two lightweight `count=exact`
  requests (one per choice, `limit=1` so no rows are actually transferred)
  reading the count from the `Content-Range` response header.
- **Added `votes_poll_id_idx` index** on the Supabase table so lookups
  stay fast as the table grows across hundreds of daily polls.
- Added a visible (if the network call fails) inline error message on the
  vote page instead of silently showing 0%/0% with no explanation.

## Deployment verification performed in this review

- All Python files verified to compile (`py_compile`) with no syntax errors.
- `generate_content.py`'s JSON extractor unit-tested against 6 cases:
  clean JSON, leading commentary, trailing commentary, markdown fences,
  literal braces inside string values, and no-JSON-present (expected
  failure).
- `utils.slugify()` and `utils.retry()` unit-tested directly, including a
  retry-then-succeed case and a give-up-after-max-attempts case.
- `publish_blog.py` tested end-to-end with deliberately adversarial input
  (HTML tags, quotes, ampersands, unicode-unsafe slug characters) and
  verified the output correctly escapes everything and produces a safe,
  sanitized slug.
- `make_image.py` tested with all five topic categories (technology,
  economy, education, society, environment) plus the default fallback —
  all render correctly with distinct palettes and icons.
- `main.py`'s image-pruning logic tested with synthetic dated files,
  confirmed it deletes only images older than the retention window.
- The GitHub Actions workflow YAML validated for structural correctness.
- **Not tested in this environment**: an actual live call to the Gemini
  API, since this sandbox's network policy doesn't allow installing the
  `google-genai` package or reaching Google's API host. The integration
  code follows the documented `google-genai` SDK usage precisely, but you
  should treat the first real run (Step 7 in README.md) as the true
  end-to-end test and report back the exact error if anything's off.

## Manual setup steps still required (unavoidable — nothing to automate here)

1. Create the GitHub repo and enable GitHub Pages.
2. Get a Gemini API key from aistudio.google.com/apikey.
3. Connect Instagram via Meta's developer portal (the genuinely fiddly
   30-minute step — unchanged by this review, it's a Meta-side process).
4. Create the Supabase project and run the updated SQL schema (note: the
   schema changed — it now includes `voter_id` and a unique constraint —
   re-run the SQL even if you set up Supabase before this review).
5. Add the renamed secrets/variables to the GitHub repo (see README Step 6).
6. Manually refresh the Instagram access token every ~60 days.
