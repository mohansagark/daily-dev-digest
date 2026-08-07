# Hybrid Candidate Selection — Design

**Date:** 2026-08-07  
**Repo:** `daily-dev-digest`  
**Status:** Implemented on `feature/hybrid-candidate-selection` (2026-08-07)  
**Supersedes (partial):** hard topic allowlist gate in `2026-08-06-editorial-cover-template-and-topic-focus-design.md` §14.1 (weekday packs + keyword *keep* rule). Listicle denylist, one post/day, cover pipeline, and generate/verify stay.  
**Motivation:** Live audit (2026-08-07, `ai_news`) showed weak keyword gates (e.g. bare `industry`) admitting junk, strong AI posts skipped for 0 hits, and near-ties (#1 vs #2) where only top-1 ever reached Bedrock rewrite.

## 1. Purpose

Change daily candidate selection so that:

1. **Weekday theme is a soft preference** (boosts ranking), not a hard kill for every off-keyword article.
2. **Quality / rewrite-worthiness is the real gate** via one cheap Bedrock triage over a shortlist.
3. **Deterministic ranking gets smarter** so the shortlist is less noisy before triage burns tokens.

Still ship **exactly one** post per successful run (or zero if nothing is good enough).

## 2. Goals and non-goals

### Goals

- Prefer the best rewrite target among scraped candidates, steered by the day’s theme.
- Keep Bedrock cost bounded: **+1 small triage call** + existing generate + verify (and cover path unchanged).
- Log the shortlist + triage decision every run for auditability (stdout **and** a lightweight report file).
- Fail soft: if triage fails or returns an invalid winner, fall back to deterministic #1, never crash the job solely on triage errors.
- Content-filter skip loop (already on master) remains: if generate is filter-blocked, try next eligible shortlist member without re-triaging.

### Non-goals

- Multiple published posts per day.
- Full rewrite bake-off of top 3 (3× generate cost).
- Per-candidate triage calls (up to 5) — batch one call only.
- Changing cover template, repair CLI, or portfolio-blog.
- Replacing RSS sources.

## 3. Pipeline (new select path)

```
scrape → clean → dedupe → listicle denylist + thin-body floor
                         → deterministic score + soft theme boost
                         → top K shortlist (K=5)
                         → Bedrock triage (batch, 1 call)
                         → winner → generate → verify → cover → MDX
```

| Stage | Owner | Hard drop? |
|---|---|---|
| Dedupe | existing | yes (exact + near-dup) |
| Listicle denylist | existing patterns via denylist-only filter | yes |
| Thin-body floor | new | yes (below min chars) |
| Theme keywords | revised packs | **no** (boost only) |
| Rank | revised score | no — orders shortlist |
| Triage | Bedrock JSON | picks winner or `none` |
| Generate/verify | existing | content-filter → try next eligible |

Dry-run: mock triage (pick shortlist[0] or first with theme_hits≥1); no Bedrock; still write `selection-report.md`.

## 4. Deterministic stage

### 4.1 Hard filters (only these)

1. Exact / near-duplicate (unchanged).
2. Listicle denylist (unchanged patterns on title + first 2k body).
3. **Thin body:** `len(content) < MIN_BODY_CHARS` (default **400**) → skip. Stops “Introducing Myself”-class keepers.

Off-theme articles are **not** hard-dropped.

**API change (explicit):** Today `topic_focus.filter_allowlisted()` does denylist **and** a hard `hits < 1 → skip` keyword gate. That keyword-hit gate is **deleted**. The function becomes denylist (+ thin-body) only — rename to something like `filter_hard_rejects` in implementation is fine; behavior must not reject solely for zero theme hits.

**Tests to update as part of this work:**

- `test_off_strategy_skipped` — rewrite to assert off-theme articles are **kept** for ranking (zero hits OK).
- `test_tools_strategy_rejects_css_clip_path_false_positive` — keep the word-boundary assertion on `count_focus_hits`; drop any assertion that `filter_*` hard-rejects the article. Thin/listicle cases stay as hard rejects.

### 4.2 Keyword packs (revised)

Whole-word / whole-phrase matching (existing `count_focus_hits` style). Title hits count **2×** body hits for scoring.

| Pack | Keep / add | Remove or narrow |
|---|---|---|
| `ai` | existing + `rag`, `fine-tuning` | — |
| `frontend` | existing + `html`, `dom`, `browser` | — |
| `architecture` | existing | — |
| `tools` | existing | — |
| `ai_news` | **`ai`**, `llm`, `chatgpt`, `claude`, `gemini`, `model release`, `openai`, `anthropic` | remove bare **`industry`** and the phrase **`ai news`** (redundant once bare `ai` exists) |
| `biz_ideas` | existing | — |
| `client_websites` | existing | — |

Weekday → pack map unchanged (`WEEKDAY_STRATEGY`).

### 4.3 Score (replace current composite)

```
theme_score   = min(1.0, (2*title_hits + body_hits) / 4.0)
recency_score = existing 0..1 decay
length_score  = min(1.0, len(content) / 2500.0)
thin_penalty  = 0.15 if len(content) < 800 else 0.0

total = 0.45*theme_score + 0.30*recency_score + 0.25*length_score - thin_penalty
```

**Hit windows:** `title_hits` are distinct focus keywords matched in the **full title**; `body_hits` are distinct focus keywords matched in the **full cleaned body**. Do **not** truncate either window for scoring (same full-body convention as current `score_article` / allowlist scoring). Triage gists may still truncate for prompt size — that is separate from deterministic hits.

**Matcher:** Ranking already uses word-boundary `topic_focus.count_focus_hits` (landed in PR #3). This work does **not** re-fix a substring-`in` bug. New scoring work is title/body split, weights, thin penalty, and pack edits above.

### 4.4 Shortlist

- Sort by `total` descending.
- Take **top K = 5** (or fewer if not enough survivors).
- Log each: rank, title, link, score breakdown, title_hits, body_hits, matched keywords.

If shortlist is empty → exit cleanly (no post), same spirit as “no candidates.”

## 5. Triage stage (Bedrock, 1 call)

### 5.1 Input

For each shortlist item, send bounded gist:

- `id`: stable index `1..K`
- `title`
- `url`
- `theme_hits` / matched keywords
- `deterministic_score`
- `body_gist`: first ~1200 chars of cleaned body

Plus: today’s `strategy_key`, `strategy_description`, `focus` list.

### 5.2 System intent

You are selecting **one** source for an original technical blog rewrite.

Priorities (in order):

1. Substantial, specific technical or industry substance worth a 700–1000 word rewrite.
2. Fit to today’s theme (soft) — prefer on-theme when quality is comparable.
3. Reject thin intros, pure linkdump, off-topic fluff, or pieces that are mostly attack/exploit walkthroughs likely to trip safety filters.

### 5.3 Output JSON (only)

```json
{
  "winner_id": 1,
  "reason": "short why this wins",
  "rankings": [
    {
      "id": 1,
      "quality": 0.0,
      "theme_fit": 0.0,
      "rewrite_worthiness": 0.0,
      "reject": false,
      "note": "optional"
    }
  ],
  "none_good_enough": false
}
```

Rules:

- Scores are 0.0–1.0.
- `winner_id` must be one of the shortlist ids, or `null` when `none_good_enough` is true.
- After parse, **validate** the winner:
  - `winner_id` ∈ shortlist ids
  - that item is **not** marked `reject: true` in `rankings`
  - if `none_good_enough` is true, `winner_id` must be null / omitted
  - Any validation failure → same path as bad JSON after retry: **deterministic fallback** (§6), log `triage_fallback=invalid_winner`.
- If `none_good_enough`, do not run generate; exit cleanly and **do not** mark all shortlist hashes as processed. Mark only items with `reject: true` **and** `rewrite_worthiness < 0.3` as `skipped: triage_reject`; leave borderline items free for a later day.

### 5.4 Model / tokens

- Same `BEDROCK_MODEL_ID` as generate.
- `max_tokens` ~800, temperature ~0.2.
- Single retry on JSON parse failure; then fallback (§6).

## 6. Fallback and interaction with content filter

| Failure | Behavior |
|---|---|
| Triage Bedrock error / bad JSON after retry | Use deterministic shortlist[0]; log `triage_fallback=deterministic` |
| Valid JSON but invalid `winner_id` / winner marked `reject: true` | Same as above; log `triage_fallback=invalid_winner` |
| `none_good_enough` | No post; exit 0 |
| Winner hits content filter on generate | Mark `skipped: content_filter`; try next among **non-rejected** shortlist members only (`reject: true` excluded), ordered by triage `rewrite_worthiness` then deterministic rank; do not re-call triage |
| All eligible shortlist members exhausted via filter | Exit 0 (existing clean exit) |

## 7. Observability

Every run writes **both**:

1. A stdout selection report block (Actions logs), and  
2. **`selection-report.md`** at the **digest repo workspace root** (v1 required — same lesson as content-repair’s `triage-report.md`).

**Delivery (locked — option b):** Do **not** commit the report into `portfolio-blog` (it is ops audit, not blog content). Do **not** rely on `digests/` alone (`digests/` is gitignored and today is only copied as `.mdx` / `images/*` into the blog clone). Add an `actions/upload-artifact` step to `.github/workflows/digest.yml` mirroring `repair-content.yml`’s triage-report upload:

- path: `selection-report.md` (workspace root)
- `if-no-files-found: ignore` is unacceptable for successful runs that reached selection — write the file even on “no post” / `none_good_enough` / triage fallback so the artifact always exists when the job got past scrape
- Upload on every job conclusion that ran `generate_digest.py` (success or soft no-post exit 0)

Report contents:

1. Strategy key + focus  
2. Counts: fetched / after dedupe / after hard filters / shortlist size  
3. Shortlist table (deterministic)  
4. Triage winner + reason + per-id scores (or fallback note)  
5. Final published slug or “no post”

Dry-run: still write + upload the same artifact.

## 8. Tests

- Keyword pack: `ai_news` matches `ai` / `chatgpt`; bare `industry` alone does **not** increase `theme_score` (article can still shortlist via recency+length).
- Title weighting: title-only hit ranks above body-only same keyword when other factors equal.
- Thin body hard-drop below `MIN_BODY_CHARS`.
- Soft theme: an article with zero keyword hits can still appear in top K when its recency+length score beats weaker on-theme rows — assert via fixture scores.
- `filter_*` no longer hard-rejects zero-hit articles; listicle/thin still rejected.
- Triage parse → winner path; triage failure / invalid `winner_id` / reject-winner → deterministic fallback; `none_good_enough` → no generate.
- Content-filter on winner → next **non-rejected** shortlist member attempted; rejected ids skipped.

## 9. Rollout

1. Land behind no flag (single path) — behavior change is the point.  
2. Watch 2–3 scheduled runs’ `selection-report.md` + logs.  
3. Tune `K`, weights, or packs if shortlist still noisy.

## 10. Open decisions (locked for v1)

| Item | Lock |
|---|---|
| K | 5 |
| Extra Bedrock calls | 1 batch triage |
| Theme hard allowlist | **removed** (`filter_*` denylist/thin only) |
| Listicle denylist | kept |
| Posts/day | 1 |
| Triage failure / invalid winner | deterministic #1 |
| `none_good_enough` | no post, exit 0 |
| `selection-report.md` | **required in v1** — workspace root + `digest.yml` artifact upload (not portfolio-blog) |

## 11. Claude review remediations (applied)

| # | Severity | Resolution |
|---|---|---|
| 1 | Blocking | Removed stale substring-`in` claim; noted word-boundary matcher already shipped in PR #3. |
| 2 | Blocking | §4.1 now explicitly deletes `filter_allowlisted` keyword gate; names the two tests to rewrite. |
| 3 | Blocking | §5.3/§6 validate `winner_id` ∈ shortlist and not `reject: true`; invalid → deterministic fallback. |
| 4 | Non-blocking | Content-filter fallback excludes `reject: true` members. |
| 5 | Non-blocking | §4.3 states full-title / full-body hit windows (no truncation mismatch). |
| 6 | Non-blocking | Promoted `selection-report.md` to **v1 required**. |
| 7 | Blocking | Locked delivery: write `selection-report.md` at digest workspace root; upload via `actions/upload-artifact` in `digest.yml` (option b). Not committed to portfolio-blog; not left only under gitignored `digests/`. |

## 12. Approval

- Approach hybrid (smarter deterministic + batch triage): **approved by Mohan 2026-08-07**  
- Claude review remediations (#1–#7) folded into this file: **2026-08-07**  
- Spec ready for implementation plan pending Mohan re-ack
