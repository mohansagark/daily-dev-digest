# daily-dev-digest

An **AI rewrite pipeline** that produces one polished developer blog post per day.
It scrapes fresh dev articles, cleans and de-duplicates them, keeps only the single
best candidate, rewrites it with **Amazon Bedrock**, fact-verifies the result, and
exports a ready-to-publish `.mdx` file with front-matter.

The output feeds the [`portfolio-blog`](https://github.com/mohansagark/portfolio-blog)
repo, which is consumed at build time by
[`next-gen-portfolio`](https://github.com/mohansagark/next-gen-portfolio) —
the blog on [devmohan.in](https://devmohan.in).

## Pipeline

```
scrape → content-clean → dedupe → topic allowlist          [deterministic]
   → LLM #1 (structured generate) → LLM #2 (fact-verify)   [LLM / Bedrock]
   → cover_hook → FLUX photo → Playwright 1200×630 cover   [cover]
   → markdown export (.mdx + front-matter)                 [deterministic]
```

Volume is capped at **exactly one post per run**: after cleaning, de-duplication,
and topic filtering, candidates are ranked and only the single best is kept.

Topic packs (allowlist): AI, frontend, architecture, tools, AI news, biz ideas for
software engineers, client websites. Listicle / “top N” noise is denylisted pre-LLM.

## Tech stack

`Python` · **Amazon Bedrock** (`boto3`) · **Cloudflare Workers AI** (FLUX schnell photo) ·
**Playwright** (editorial cover template) · `trafilatura` + `beautifulsoup4` + `lxml`
(scraping/cleaning) · `feedparser` (RSS) · `python-slugify` · **GitHub Actions**
(scheduled, AWS OIDC)

## Running locally

```bash
pip install -r requirements.txt
playwright install chromium

# Dry run — Bedrock/FLUX mocked; still composes a cover JPG with a placeholder photo:
python generate_digest.py --dry-run

# Full run (requires AWS Bedrock + Cloudflare credentials):
python generate_digest.py
```

## Automation

`.github/workflows/digest.yml` runs the pipeline on a daily cron
(`30 2 * * *` UTC ≈ 8:00 AM IST) and via **workflow_dispatch**. It authenticates to
AWS with **OIDC** (`id-token: write`, least-privilege) — no long-lived AWS keys are
stored. `.github/workflows/ci.yml` runs pytest on push/PR.

### Content repair

`.github/workflows/repair-content.yml` triages and repairs legacy posts in
[`portfolio-blog`](https://github.com/mohansagark/portfolio-blog) via
**workflow_dispatch**. Defaults to **dry-run** (writes `triage-report.md` only).
Real runs push a dated preview branch `repair/content-cleanup-YYYYMMDD-HHMM` — never
`main` — and commit any `repair_ledger.json` updates back to this repo. Start with
`limit=10`, review the report, then re-run with `dry_run=false`; use `full_run=true`
for the remaining backlog.

## Cover images

Each new post gets a best-effort **editorial cover** (1200×630): Bedrock `cover_hook`
copy + FLUX photo + Playwright HTML template (`cover_template/`). Brand lock:
**Mohan Sagar** / `<devmohan.in>`.

Required for FLUX: `CF_ACCOUNT_ID`, `CF_API_TOKEN`.
Optional: `CF_IMAGE_MODEL` (default: `@cf/black-forest-labs/flux-1-schnell`),
`IMAGE_STEPS` (default: `8` in Actions), `IMAGE_REQUIRED` (default: `false`).

Look for `COVER_STATUS=ok` or `COVER_STATUS=failed:<reason>` in logs. If cover
generation fails, the post still publishes as text-only.

## Files

| File | Role |
|------|------|
| `generate_digest.py` | Orchestrates the full pipeline |
| `topic_focus.py` | Allowlist strategies + listicle denylist |
| `cover_hook.py` | Bedrock cover copy + FLUX photo prompt |
| `cover_compose.py` | Playwright compositor → JPEG |
| `cover_template/` | Editorial HTML/CSS/fonts |
| `bedrock_client.py`  | Amazon Bedrock LLM calls |
| `image_client.py` | Cloudflare Workers AI FLUX |
| `yaml_utils.py`      | Safe YAML front-matter helpers |
| `processed_articles.json` | Dedupe ledger of already-published sources |
