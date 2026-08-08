# daily-dev-digest — Content / Slug / FLUX / SEO Backlog

**Date:** 2026-08-08  
**Status:** Open — recorded for resolution (not yet implemented)  
**Repo:** `daily-dev-digest` only (content pipeline; may rewrite `portfolio-blog` MDX/slugs/images)  
**GitHub:** https://github.com/mohansagark/daily-dev-digest/issues/12  

**Sister backlog (portfolio UI):** https://github.com/mohansagark/next-gen-portfolio/issues/26  
`next-gen-portfolio` → `docs/superpowers/specs/2026-08-08-blog-ux-content-hygiene-backlog.md`

IDs below are stable cross-repo numbers (gaps are intentional — those IDs live in portfolio).

## Summary (this repo)

| # | Issue |
|---|---|
| 1 | Valid slug generation + cleanup |
| 2 | Consolidate Takeaways → **Key Takeaways** |
| 8 | FLUX cover quality consistency |
| 14 | SEO: answer-first opener + Key Takeaways high on page |
| 15 | SEO: question-style H2s + FAQ section in generate/repair |

---

## 1. Valid slug generation and cleanup

**Problem:** Some published slugs are truncated, trailing-hyphen, or otherwise invalid/unstable (e.g. `from-zero-to-chat-my-journey-building-a-`, `what-is-o4-mini-high-all-you-need-to-kno`).

**Desired:** Deterministic, URL-safe slug rules (length, charset, no trailing `-`); one-time cleanup of existing bad slugs with redirects or index rewrites on `portfolio-blog` as needed.

## 2. Consolidate takeaways sections → Key Takeaways

**Problem:** Posts can contain both a “Takeaways” and a “Key Takeaways” section (or near-duplicates).

**Desired:** Single section titled **Key Takeaways** everywhere (new posts via generate + repair/hygiene for legacy MDX).

## 8. FLUX image quality consistency

**Problem:** Editorial photo quality varies — sometimes strong, sometimes weak — for the same pipeline.

**Desired:** Tighter prompt/seed/steps (or model) policy so heal/create covers are more consistently good; document knobs and any A/B findings.

## 14. SEO — answer-first + Key Takeaways placement

**Problem:** Posts may bury the main answer under long preamble.

**Desired:** Generate/repair emit a **40–60 word direct answer** first, then a single **Key Takeaways** block near the top (ties to #2). Portfolio only renders what digest writes.

## 15. SEO — question H2s + FAQ

**Problem:** Flat/label-style H2s and missing FAQ reduce passage ranking and AI-overview citation odds.

**Desired:** Prefer **question-style H2s** (PAA-shaped); add a short **FAQ** section when natural; keep strict H2→H3 hierarchy (no skipped levels, **no body H1**). Portfolio FAQPage schema (#17) consumes this when present.

---

## Out of scope (this repo)

- Portfolio UI/UX, typography, schema, TOC, voice bot, socials → sister backlog.
- Cover heal schedule / daily limit 20 (shipped).

## Suggested execution order (this repo)

1. Content structure: #2, #14, #15 (prompt + repair)  
2. Slug rules + corpus cleanup: #1  
3. FLUX consistency experiments: #8  
