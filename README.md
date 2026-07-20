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
scrape → content-clean → dedupe → citation-extract        [deterministic]
   → LLM #1 (structured generate) → LLM #2 (fact-verify)   [LLM / Bedrock]
   → markdown export (.mdx + front-matter)                 [deterministic]
```

Volume is capped at **exactly one post per run**: after cleaning and de-duplication,
all candidates are ranked and only the single best is kept.

## Tech stack

`Python` · **Amazon Bedrock** (`boto3`) · **Cloudflare Workers AI** (FLUX schnell, cover images) · `trafilatura` + `beautifulsoup4` + `lxml`
(scraping/cleaning) · `feedparser` (RSS) · `pydantic` (structured output) ·
`python-slugify` · **GitHub Actions** (scheduled, AWS OIDC)

## Running locally

```bash
pip install -r requirements.txt

# Dry run — exercises the entire deterministic path with the two LLM
# stages mocked, so no AWS calls are made:
python generate_digest.py --dry-run

# Full run (requires AWS Bedrock credentials in the environment):
python generate_digest.py
```

## Automation

`.github/workflows/*.yml` runs the pipeline on a daily cron
(`30 2 * * *` UTC ≈ 8:00 AM IST) and via **workflow_dispatch**. It authenticates to
AWS with **OIDC** (`id-token: write`, least-privilege) — no long-lived AWS keys are
stored.

## Cover images

Each post gets one best-effort cover image generated with
[Cloudflare Workers AI](https://developers.cloudflare.com/workers-ai/) (FLUX schnell).
Required environment variables: `CF_ACCOUNT_ID`, `CF_API_TOKEN`.
Optional: `CF_IMAGE_MODEL` (default: `@cf/black-forest-labs/flux-1-schnell`),
`IMAGE_STEPS` (default: `4`), `IMAGE_REQUIRED` (default: `false`).

If image generation fails, the post is still published as text-only (no image front-matter field).

## Files

| File | Role |
|------|------|
| `generate_digest.py` | Orchestrates the full pipeline |
| `bedrock_client.py`  | Amazon Bedrock LLM calls (generate + verify) |
| `yaml_utils.py`      | Safe YAML front-matter helpers |
| `processed_articles.json` | Dedupe ledger of already-published sources |
