# India Thinks — fully automated, twice-daily debate machine

**The Nation Decides**

Twice a day (9:00 AM and 6:00 PM IST) this bot:
1. Brainstorms 20 candidate topics from the last 7 days of Indian news,
   policy, and consumer discussion, scores each on 7 dimensions, and picks
   the single best one
2. Writes a balanced 500-word explainer article for the blog
3. Picks the best-fitting post template (of 5) for that specific topic and
   renders ONE powerful Instagram image designed to be understood in 3 seconds
4. Publishes the article to your free blog (GitHub Pages), with real
   click-to-vote
5. Posts the single image to your Instagram feed

Cost: roughly ₹2-5 per day in Gemini API usage (two posts, each using two
Gemini calls). Everything else is free.

See `CHANGELOG.md` for a full history of what changed and why.

---

## How topic selection works

1. **Stage 1 — Select.** Gemini searches the last 7 days of Indian news —
   regulations, fuel prices, banking/UPI/GST changes, layoffs, exams,
   transport, consumer complaints, viral debates — and proposes 20 topics,
   each scored 0-10 on relatability, opinion strength, comment potential,
   discussion potential, shareability, and trend momentum, plus a
   brand-safety score.
2. Every candidate must also come with a **news_anchor**: a one-line
   citation of the actual recent event it's tied to. A topic with no real
   anchor is discarded outright, no matter how well it scores otherwise —
   this is what actually enforces "feels like today," not just prompt wording.
3. Python — not the model — recomputes the weighted score from those
   numbers (`trend_momentum` is now the highest-weighted dimension) and
   re-ranks. Anything below 8/10 on brand safety is excluded entirely.
4. **Stage 2 — Elaborate.** A second Gemini call takes only the winning
   topic and picks whichever of the 5 post templates fits it best, then
   writes the full content package for that template plus the blog article.

Every day's full 20-candidate scoring breakdown is saved to
`output/topics/<date>-<slot>.json` and committed to the repo — nothing
about topic selection happens invisibly.

## The single-image post system

Each post is ONE Instagram image (1080×1350), designed so a viewer
understands the topic, both sides, and what to comment within about 3
seconds. Five reusable templates, and the AI picks whichever one actually
fits the topic rather than forcing everything into the same shape:

| Template | Use case | CTA |
|---|---|---|
| **Debate** | Two-sided yes/no question | COMMENT YES OR NO |
| **Comparison** | Weighing two concrete options | WHICH WOULD YOU CHOOSE? |
| **Prediction** | A future event, bull case vs bear case | WHAT DO YOU THINK? |
| **Hot Take** | One bold, single-voice claim | AGREE OR DISAGREE? |
| **Fact vs Myth** | Common belief vs. the actual reality | DID YOU KNOW THIS? |

The CTA text is fixed per template, not left to the model — every post of
a given type stays visually and verbally consistent, the way a real
publication's recurring formats do.

All five share one dark editorial visual identity with a single yellow
accent color (`config.py`'s `YELLOW`, `BG_COLOR`, etc. — a rebrand never
requires touching layout code). A secondary vertical story image is also
generated for each post, with a blank reserved zone for manually adding
Instagram's native Poll sticker (see Known Limitations for why that step
isn't automated).

An `image_prompt` is also generated for every post — a detailed prompt
ready to hand to an AI image model if you ever want to swap the PIL
renderer for a generative one. It's saved in the package but not currently
used automatically.

---

## One-time setup (about 1 hour)

### Step 1 — Put this code on GitHub (10 min)
1. Create a GitHub account at github.com if you don't have one
2. Create a new **public** repository named `india-thinks-bot`
   (public is required — Instagram must be able to fetch image URLs, and
   GitHub Pages free tier needs a public repo)
3. Upload all these files to it

### Step 2 — Turn on the blog (2 min)
1. In your repo: Settings → Pages
2. Source: "Deploy from a branch" → Branch: `main` → Folder: `/ (root)`
3. Your blog will be live at `https://YOURUSERNAME.github.io/india-thinks-bot/blog/`
4. Put that link in your Instagram bio.

### Step 3 — Get your Gemini API key (5 min)
1. Go to **aistudio.google.com/apikey** → sign in with Google → Create API Key
2. Attach a billing account in Google Cloud Console for reliability at two
   posts/day (expect well under ₹200/month)
3. Copy the key

### Step 4 — Connect Instagram (30 min, the fiddly part)
Instagram only allows API posting for **Business/Creator accounts** linked
to a **Facebook Page**.

1. Instagram app → Settings → Account type → switch to **Business**
2. Create a Facebook Page and link your Instagram to it: Instagram
   Settings → Business tools → Connect a Facebook Page
3. **developers.facebook.com** → My Apps → Create App → type "Business"
4. Add the product **"Instagram Graph API"**
5. Graph API Explorer (Tools menu): select your app, add permissions
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `business_management`, generate an access token
6. Make the token long-lived (60 days):
   ```
   https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN
   ```
7. Get your Instagram user ID — in Graph API Explorer, GET `me/accounts`
   to get your Page id, then GET `{page-id}?fields=instagram_business_account`
   — that number is `IG_USER_ID`.

The long-lived token expires after ~60 days. Set a phone reminder to
regenerate it.

### Step 5 — Turn on real click-to-vote on the blog (10 min)
Instagram feed posts can't have a clickable vote button — a platform
limitation, not something this project can work around. The real, counted
vote happens on your blog page. Comments ("YES"/"NO") are the Instagram-side
engagement signal; the blog click is the informed vote that gets counted.

1. **supabase.com** → sign up free → New Project
2. SQL Editor → run:
   ```sql
   create table votes (
     id bigint generated always as identity primary key,
     poll_id text not null,
     choice text not null check (choice in ('yes','no')),
     voter_id text not null,
     created_at timestamptz default now(),
     unique (poll_id, voter_id)
   );
   create index votes_poll_id_idx on votes (poll_id);
   alter table votes enable row level security;
   create policy "anyone can vote" on votes for insert with check (true);
   create policy "anyone can read counts" on votes for select using (true);
   ```
3. Settings → API → copy the **Project URL** and the **anon public** key.

### Step 6 — Add your secrets to GitHub (5 min)
Repo → Settings → Secrets and variables → Actions

**Secrets:**
| Name | Value |
|---|---|
| `GEMINI_API_KEY` | your Gemini API key |
| `IG_ACCESS_TOKEN` | your long-lived Instagram token |
| `IG_USER_ID` | your Instagram business account id |
| `SUPABASE_ANON_KEY` | your Supabase anon public key |

**Variables:**
| Name | Value |
|---|---|
| `BLOG_URL` | https://YOURUSERNAME.github.io/india-thinks-bot/blog/ |
| `SUPABASE_URL` | your Supabase project URL |

### Step 7 — Test it (5 min)
Repo → Actions tab → "India Thinks — Twice-Daily Post" → **Run workflow**
→ pick a slot (morning or evening) → Run. In a couple of minutes you
should see a new blog article with working vote buttons, and one image
post on Instagram. Run it once more with the other slot to confirm the
second run picks a genuinely different topic.

If it fails, the error messages are specific (missing keys, Instagram's
actual rejection reason, malformed AI output) rather than bare tracebacks.
A failed run also automatically opens a GitHub Issue in your repo.

---

## After setup: your only jobs
- Glance at both posts each day (quality check — AI can make factual
  mistakes, and one wrong fact that goes viral can sink the brand's trust)
- Reply to comments (the algorithm rewards it heavily — and this whole
  system is designed to generate comments)
- Post the generated Story image manually if you want it live
- Refresh the Instagram token every ~60 days

## Known limitations (by design, not oversights)
- **No clickable vote on the Instagram post itself.** Comments are the
  Instagram-side signal; the blog vote is the real, counted one.
- **Stories are generated but not auto-published.** Instagram's Graph API
  does not support publishing interactive story stickers programmatically.
  The story image has a reserved blank zone for you to drop the Poll
  sticker on manually — a 30-second job if you choose to do it.
- **Duplicate voting is discouraged, not prevented.** A determined person
  can clear browser storage and vote again. The database's unique
  constraint stops accidental duplicates, not deliberate abuse.
- **Images are pruned automatically** after 3 days (`IMAGE_RETENTION_DAYS`
  in `config.py`). Blog articles and topic-scoring JSON are kept forever.
- **A bad news day could mean a missed post.** If every one of the 20
  candidates fails the brand-safety or news-anchor gate (rare), the
  pipeline fails loudly rather than posting something unsafe or stale —
  you'll get a GitHub Issue about it, not a silent gap.

## Changing the schedule
Edit the two `cron` lines in `.github/workflows/daily.yml`. Times are UTC;
use crontab.guru to convert.

## Changing the topic-scoring weights or priority categories
Edit `SCORE_WEIGHTS` (must sum to 1.0) and `PRIORITY_CATEGORIES` in
`generate_content.py`.

## Adding or changing a post template
Add a new entry to `TEMPLATE_CONTENT_SCHEMA` and `CTA_BY_TEMPLATE`, add
the field descriptions to `ELABORATE_PROMPT_TEMPLATE`, and write a
matching `_render_<name>` function in `make_image.py`, then register it
in `_TEMPLATE_RENDERERS`.

## Changing the visual design
`make_image.py` — colors are all in `config.py` (`YELLOW`, `BG_COLOR`, etc.)
so a rebrand doesn't require touching layout code.

## Optional: real AI-generated photo backgrounds (Gemini 2.5 Flash Image)

By default, every post image is rendered entirely for free with PIL — no
API cost, works instantly, never fails. You can optionally switch to real
AI-generated editorial photography as the background, with the headline,
India Thinks logo, and CTA overlaid on top of it.

**This costs real money per image** (roughly $0.02-$0.06/image as of mid
2026 — check Google's current pricing before enabling, this space moves
fast). At 2 posts/day that's a few dollars a month, but it's not free like
the default path, so it's off unless you turn it on.

To enable it:

**Variables** (add alongside the existing ones):
| Name | Value |
|---|---|
| `USE_AI_IMAGES` | `true` |
| `GEMINI_IMAGE_MODEL` | `gemini-2.5-flash-image` (default if unset) |

No new secret is needed — it reuses your existing `GEMINI_API_KEY`.

**What happens under the hood**: the pipeline asks Gemini's image model for
an editorial-style photo (dark background, warm yellow accent lighting,
cinematic, explicitly instructed to contain zero text/logos/watermarks —
AI models reliably mangle rendered text, so all real text is added
afterward with crisp PIL typography, not generated by the image model).
The overlay is deliberately simpler than the full PIL templates — just the
kicker, headline, CTA, and logo, magazine-cover style — since a busy
bulleted comparison chart doesn't read well on top of a photo.

**If image generation fails for any reason** — missing key, network error,
safety block, quota exceeded, malformed response, anything — the pipeline
automatically falls back to the free PIL renderer for that post and logs
a warning. A bad day for the image API never means a missed post. This
fallback is unconditional: there's no scenario where a post simply fails
to generate because AI images didn't work.

To go back to the free-only renderer, set `USE_AI_IMAGES` to `false` (or
just delete the variable — that's the default).

## Changing the Gemini model
Set the `GEMINI_MODEL` environment variable (default `gemini-2.5-flash`).
