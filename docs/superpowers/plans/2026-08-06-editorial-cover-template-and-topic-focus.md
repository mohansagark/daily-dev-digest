# Editorial Cover Template + Topic Focus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship allowlisted topic selection plus Approach A editorial covers (Bedrock cover_hook → FLUX photo → Playwright 1200×630 template) for new digest posts.

**Architecture:** Selection filters candidates with §14.1 strategies + pre-LLM denylist on title/content. After generate/verify, `cover_hook` produces hook JSON; FLUX renders a photo-only image; Playwright serves `cover_template/` over a local static server and screenshots JPEG. Fail-soft with `COVER_STATUS=` markers. Spec: `docs/superpowers/specs/2026-08-06-editorial-cover-template-and-topic-focus-design.md` (§14 locked).

**Tech Stack:** Python 3.11, Bedrock Nova Pro, Cloudflare FLUX schnell, Playwright Chromium, Pillow, pytest, GitHub Actions.

## Global Constraints

- Brand: `Mohan Sagar` / `<devmohan.in>`; fonts Playfair Display + DM Sans (vendored).
- Canvas 1200×630; local static server only (no `file://`); photo `object-fit: cover`; artifact-only / no faces.
- Strip `image_brief` from LLM#1 new-post path; cover_backfill keeps its own brief.
- Pill one line; shorten longest beat if overflow; log `COVER_STATUS=ok|failed:<reason>`.
- Cite §14 decisions; do not re-open.

## File map

| File | Role |
|---|---|
| `topic_focus.py` | STRATEGIES §14.1, weekday rotation, denylist, filter helpers |
| `cover_hook.py` | Bedrock cover_hook + pill shorten + photo prompt assembly |
| `cover_compose.py` | Static server + Playwright screenshot → JPEG bytes |
| `cover_template/index.html` (+ css/fonts) | Editorial layout |
| `generate_digest.py` | Wire strategies, strip image_brief, new maybe_generate_cover |
| `image_client.py` | unchanged API (square OK; crop in template) |
| `.github/workflows/digest.yml` | Playwright install + cache |
| `.github/workflows/ci.yml` | pytest on PR/push |
| `tests/test_topic_focus.py`, `test_cover_hook.py`, `test_cover_compose.py` | Unit/integration |
| `requirements.txt` / `requirements-dev.txt` | playwright |

### Task 1: Topic allowlist + denylist

**Files:** Create `topic_focus.py`, `tests/test_topic_focus.py`; Modify `generate_digest.py` (replace STRATEGIES / get_content_strategy / select path)

- [ ] TDD denylist (`top 5`, roundup) and allowlist scoring filter
- [ ] Implement `topic_focus.py` with §14.1 table + deterministic weekday map (any complete Mon–Sun over the 7 keys)
- [ ] Wire `generate_digest` to use it; fail clearly when zero candidates
- [ ] Commit

### Task 2: Strip image_brief from LLM#1

**Files:** Modify `generate_digest.py` GENERATE template + dry-run mock; update tests that expect image_brief in generate path

- [ ] Remove image_brief from prompt/JSON; keep GENERATE_KEYS without it
- [ ] Dry-run mock drops image_brief
- [ ] Commit

### Task 3: cover_hook

**Files:** Create `cover_hook.py`, `tests/test_cover_hook.py`

- [ ] `generate_cover_hook(title, tags, body, *, dry_run)` → dict
- [ ] `shorten_pill_beats(pill, max_chars)` / measure helper for one-line
- [ ] `build_flux_photo_prompt(hook)` with tone + off-center + no-faces rules
- [ ] Commit

### Task 4: Template + compositor

**Files:** Create `cover_template/`, `cover_compose.py`, `tests/test_cover_compose.py`; add playwright dep; vendor font files

- [ ] HTML/CSS matching locked visual system
- [ ] `compose_cover(hook, photo_bytes) -> jpeg_bytes` via local HTTP server + Playwright
- [ ] Dry-run placeholder photo path
- [ ] Commit

### Task 5: Orchestration + CI

**Files:** Modify `maybe_generate_cover` / `main`; `.github/workflows/digest.yml`; create `.github/workflows/ci.yml`; README note

- [ ] Wire cover_hook → FLUX → compose → save; COVER_STATUS logs
- [ ] Playwright install + cache on digest; pytest CI workflow
- [ ] `python generate_digest.py --dry-run` produces cover JPG
- [ ] Commit

---

**Execution:** User requested build immediately — implement tasks inline in order (executing-plans style) after this plan is saved.
