"""Publishes the article to the blog (GitHub Pages, served from /blog).

Each article page includes a real click-to-vote widget. Votes are stored
in Supabase (free tier) via its REST API, called directly from the
visitor's browser with a public "anon" key — no server needed.

Duplicate-vote mitigation (best-effort, no login required):
- A random voter_id (UUID) is generated once per browser and stored in
  localStorage alongside the vote.
- The Supabase table has a UNIQUE(poll_id, voter_id) constraint, so
  network retries or accidental double-submits from the same browser
  can't create duplicate rows.
- This does NOT stop a determined person from clearing storage or using
  incognito mode to vote again — that requires login or IP-based tracking,
  which is out of scope for a no-login voting page. It's documented as a
  known limitation in README.md.

Vote counting uses two lightweight `count=exact` HEAD-style requests
(one per choice) instead of downloading every row, so it stays fast as
vote volume grows into the thousands.
"""
import html
import json
import os
import re
from datetime import date

from config import BRAND_NAME, BRAND_TAGLINE
from utils import logger, slugify

BLOG_DIR = os.path.join(os.path.dirname(__file__), "blog")
POSTS_DIR = os.path.join(BLOG_DIR, "posts")

# Filled in by the workflow from GitHub Variables (safe to expose — anon key
# is designed to be public; Supabase Row Level Security controls what it can do)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {brand_name}</title>
<style>
:root{{--bg:#0a0a0f;--card:#13131a;--card2:#1c1c26;--border:rgba(255,255,255,.08);--acc:#6c63ff;--text:#f0f0ff;--muted:#8585a8;--yes:#2ecc71;--no:#ff4757}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.75}}
.wrap{{max-width:680px;margin:0 auto;padding:32px 20px 80px}}
.brand{{color:var(--acc);font-weight:700;font-size:18px;text-decoration:none}}
.tagline{{color:var(--muted);font-size:13px;margin-top:2px}}
h1{{font-size:30px;line-height:1.3;margin:28px 0 8px;letter-spacing:-.5px}}
.date{{color:var(--muted);font-size:13px;margin-bottom:28px}}
h2{{font-size:20px;margin:32px 0 12px;color:var(--acc)}}
p{{margin:0 0 16px;color:#c9c9e0;font-size:16px}}
ul{{margin:0 0 16px 22px;color:#c9c9e0}}
li{{margin-bottom:8px}}
a{{color:var(--acc)}}

.vote-card{{background:var(--card);border:2px solid var(--acc);border-radius:18px;padding:26px 24px;margin-top:40px}}
.vote-card h3{{font-size:19px;margin-bottom:4px}}
.vote-card .sub{{color:var(--muted);font-size:13px;margin-bottom:20px}}
.vote-btn{{display:flex;align-items:center;gap:14px;width:100%;text-align:left;background:var(--card2);
  border:2px solid var(--border);border-radius:14px;padding:16px 18px;margin-bottom:12px;cursor:pointer;
  color:var(--text);font-size:16px;font-weight:600;font-family:inherit;transition:border-color .15s,transform .1s}}
.vote-btn:hover{{transform:translateY(-1px)}}
.vote-btn:active{{transform:scale(.98)}}
.vote-btn.yes:hover{{border-color:var(--yes)}}
.vote-btn.no:hover{{border-color:var(--no)}}
.dot{{width:14px;height:14px;border-radius:50%;flex-shrink:0}}
.dot.yes{{background:var(--yes)}}
.dot.no{{background:var(--no)}}

.results{{display:none;margin-top:8px}}
.results.show{{display:block}}
.bar-row{{margin-bottom:14px}}
.bar-label{{display:flex;justify-content:space-between;font-size:14px;margin-bottom:6px}}
.bar-track{{height:12px;background:var(--card2);border-radius:6px;overflow:hidden}}
.bar-fill{{height:100%;border-radius:6px;width:0;transition:width .8s cubic-bezier(.4,0,.2,1)}}
.bar-fill.yes{{background:var(--yes)}}
.bar-fill.no{{background:var(--no)}}
.total{{color:var(--muted);font-size:12px;margin-top:6px}}
.thanks{{color:var(--yes);font-size:13px;font-weight:600;margin-bottom:16px;display:none}}
.thanks.show{{display:block}}
.err{{color:var(--muted);font-size:12px;margin-top:8px;display:none}}
.err.show{{display:block}}
</style>
</head>
<body>
<div class="wrap">
<a class="brand" href="../index.html">{brand_name}</a>
<div class="tagline">{brand_tagline}</div>
<h1>{title}</h1>
<div class="date">{date_str} · 3 min read</div>
{body_html}

<div class="vote-card">
<h3>{poll_question}</h3>
<div class="sub">You've read both sides. Cast your informed vote below.</div>
<div class="thanks" id="thanks">Thanks — your informed vote has been counted.</div>

<div id="vote-buttons">
<button class="vote-btn yes" id="btn-yes" onclick="castVote('yes')">
  <span class="dot yes"></span>{option_yes}
</button>
<button class="vote-btn no" id="btn-no" onclick="castVote('no')">
  <span class="dot no"></span>{option_no}
</button>
</div>

<div class="results" id="results">
<div class="bar-row">
  <div class="bar-label"><span>{option_yes}</span><span id="pct-yes">0%</span></div>
  <div class="bar-track"><div class="bar-fill yes" id="fill-yes"></div></div>
</div>
<div class="bar-row">
  <div class="bar-label"><span>{option_no}</span><span id="pct-no">0%</span></div>
  <div class="bar-track"><div class="bar-fill no" id="fill-no"></div></div>
</div>
<div class="total" id="total-votes"></div>
</div>
<div class="err" id="err">Could not reach the vote server. Your vote is saved locally — try refreshing.</div>
</div>

</div>
<script>
const POLL_ID = {poll_id_json};
const SUPABASE_URL = {supabase_url_json};
const SUPABASE_KEY = {supabase_key_json};
const VOTE_KEY = "it_vote_" + POLL_ID;
const VOTER_KEY = "it_voter_id";

function getVoterId() {{
  let id = localStorage.getItem(VOTER_KEY);
  if (!id) {{
    id = (crypto.randomUUID ? crypto.randomUUID() :
      "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {{
        const r = Math.random() * 16 | 0;
        return (c === "x" ? r : (r & 0x3 | 0x8)).toString(16);
      }}));
    localStorage.setItem(VOTER_KEY, id);
  }}
  return id;
}}

async function fetchCounts() {{
  if (!SUPABASE_URL) return {{yes: 0, no: 0}};
  const headers = {{ apikey: SUPABASE_KEY, Authorization: "Bearer " + SUPABASE_KEY, Prefer: "count=exact" }};
  try {{
    const [yesRes, noRes] = await Promise.all([
      fetch(SUPABASE_URL + "/rest/v1/votes?poll_id=eq." + encodeURIComponent(POLL_ID) + "&choice=eq.yes&select=id&limit=1", {{ headers }}),
      fetch(SUPABASE_URL + "/rest/v1/votes?poll_id=eq." + encodeURIComponent(POLL_ID) + "&choice=eq.no&select=id&limit=1", {{ headers }}),
    ]);
    const parseCount = (res) => {{
      const range = res.headers.get("content-range");
      if (range && range.includes("/")) return parseInt(range.split("/")[1], 10) || 0;
      return 0;
    }};
    return {{ yes: parseCount(yesRes), no: parseCount(noRes) }};
  }} catch (e) {{
    return {{yes: 0, no: 0}};
  }}
}}

async function castVote(choice) {{
  if (localStorage.getItem(VOTE_KEY)) return;
  localStorage.setItem(VOTE_KEY, choice);

  let ok = true;
  if (SUPABASE_URL) {{
    try {{
      const res = await fetch(SUPABASE_URL + "/rest/v1/votes", {{
        method: "POST",
        headers: {{
          apikey: SUPABASE_KEY,
          Authorization: "Bearer " + SUPABASE_KEY,
          "Content-Type": "application/json",
          Prefer: "return=minimal,resolution=ignore-duplicates"
        }},
        body: JSON.stringify({{ poll_id: POLL_ID, choice: choice, voter_id: getVoterId() }})
      }});
      ok = res.ok;
    }} catch (e) {{ ok = false; }}
  }}
  showResults(ok);
}}

async function showResults(networkOk) {{
  document.getElementById("vote-buttons").style.display = "none";
  document.getElementById("thanks").classList.add("show");
  document.getElementById("results").classList.add("show");
  if (!networkOk) document.getElementById("err").classList.add("show");

  const counts = await fetchCounts();
  const total = counts.yes + counts.no || 1;
  const yesPct = Math.round(counts.yes / total * 100);
  const noPct = 100 - yesPct;

  document.getElementById("pct-yes").textContent = yesPct + "%";
  document.getElementById("pct-no").textContent = noPct + "%";
  document.getElementById("total-votes").textContent = total.toLocaleString() + " informed votes so far";
  setTimeout(() => {{
    document.getElementById("fill-yes").style.width = yesPct + "%";
    document.getElementById("fill-no").style.width = noPct + "%";
  }}, 50);
}}

(function init() {{
  const existing = localStorage.getItem(VOTE_KEY);
  if (existing) showResults(true);
}})();
</script>
</body>
</html>"""

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{brand_name} — {brand_tagline}</title>
<style>
:root{{--bg:#0a0a0f;--card:#13131a;--border:rgba(255,255,255,.08);--acc:#6c63ff;--text:#f0f0ff;--muted:#8585a8}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text)}}
.wrap{{max-width:680px;margin:0 auto;padding:40px 20px}}
h1{{color:var(--acc);font-size:28px;letter-spacing:-.5px}}
.tagline{{color:var(--muted);margin:4px 0 32px}}
.post{{display:block;background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px 20px;margin-bottom:12px;text-decoration:none;color:var(--text);transition:border-color .15s}}
.post:hover{{border-color:var(--acc)}}
.post .t{{font-size:16px;font-weight:600;line-height:1.4}}
.post .d{{font-size:12px;color:var(--muted);margin-top:6px}}
</style>
</head>
<body>
<div class="wrap">
<h1>{brand_name}</h1>
<div class="tagline">{brand_tagline} A balanced explainer every morning and evening.</div>
{posts_html}
</div>
</body>
</html>"""


def _md_to_html(md: str) -> str:
    """Minimal markdown -> HTML (headings, bullets, paragraphs, bold).

    HTML-escapes every line of raw text BEFORE wrapping in tags, since the
    source is AI-generated and could contain '<', '>', or '&' that would
    otherwise break the page (e.g. "cost < benefit" silently vanishing).
    Bold markers (**text**) are converted after escaping so they still work.
    """
    html_lines, in_list = [], False
    for raw_line in md.split("\n"):
        line = html.escape(raw_line.rstrip())
        if line.startswith("## "):
            if in_list:
                html_lines.append("</ul>"); in_list = False
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith(("- ", "* ")):
            if not in_list:
                html_lines.append("<ul>"); in_list = True
            html_lines.append(f"<li>{line[2:]}</li>")
        elif line == "":
            if in_list:
                html_lines.append("</ul>"); in_list = False
        else:
            if in_list:
                html_lines.append("</ul>"); in_list = False
            html_lines.append(f"<p>{line}</p>")
    if in_list:
        html_lines.append("</ul>")
    out = "\n".join(html_lines)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    return out


def publish_post(package: dict) -> str:
    today = date.today()
    # topic_slug comes from the model — sanitize it before it becomes a
    # filename, a URL path, AND a JS string literal on the vote page.
    # The slot is included so a morning and evening post on the same day
    # can never collide even if the model produces a similar slug for both.
    safe_slug = slugify(package["topic_slug"])
    slot = package.get("slot", "post")
    slug = f"{today.isoformat()}-{slot}-{safe_slug}"[:90]
    filename = f"{slug}.html"

    os.makedirs(POSTS_DIR, exist_ok=True)

    page = PAGE_TEMPLATE.format(
        title=html.escape(package["article_title"]),
        brand_name=BRAND_NAME,
        brand_tagline=BRAND_TAGLINE,
        date_str=today.strftime("%B %d, %Y"),
        body_html=_md_to_html(package["article_markdown"]),
        poll_question=html.escape(package["poll_question"]),
        option_yes=html.escape(package["option_yes"]),
        option_no=html.escape(package["option_no"]),
        poll_id_json=json.dumps(slug),
        supabase_url_json=json.dumps(SUPABASE_URL),
        supabase_key_json=json.dumps(SUPABASE_ANON_KEY),
    )
    with open(os.path.join(POSTS_DIR, filename), "w") as f:
        f.write(page)

    manifest_path = os.path.join(BLOG_DIR, "manifest.json")
    manifest = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except json.JSONDecodeError:
            logger.warning("blog/manifest.json was corrupt — starting a fresh one.")
            manifest = []

    manifest.insert(0, {
        "file": f"posts/{filename}",
        "title": package["article_title"],
        "date": today.strftime("%B %d, %Y"),
    })
    manifest = manifest[:120]
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=1)

    posts_html = "\n".join(
        f'<a class="post" href="{html.escape(p["file"])}"><div class="t">{html.escape(p["title"])}</div>'
        f'<div class="d">{html.escape(p["date"])}</div></a>'
        for p in manifest
    )
    with open(os.path.join(BLOG_DIR, "index.html"), "w") as f:
        f.write(INDEX_TEMPLATE.format(
            brand_name=BRAND_NAME, brand_tagline=BRAND_TAGLINE, posts_html=posts_html,
        ))

    logger.info("Blog post published: blog/posts/%s", filename)
    return f"blog/posts/{filename}"
