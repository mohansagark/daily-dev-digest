# Hybrid Candidate Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Soft weekday theme + smarter deterministic shortlist + one Bedrock batch triage, with `selection-report.md` artifact upload.

**Architecture:** `topic_focus` owns packs, hard rejects (listicle+thin), and hit/score helpers. New `selection_triage.py` owns prompts + parse/validate. `generate_digest.main` wires shortlist → triage → generate loop and writes `selection-report.md`. `digest.yml` uploads the report.

**Tech Stack:** Python 3.11, existing `bedrock_client`, GitHub Actions `upload-artifact`.

**Spec:** `docs/superpowers/specs/2026-08-07-hybrid-candidate-selection-design.md`

## Global Constraints

- K=5; +1 batch triage call; one post/day; theme hard allowlist removed
- `selection-report.md` at workspace root + artifact (not portfolio-blog)
- Invalid triage winner → deterministic #1; content-filter skips `reject: true`

## File map

| File | Role |
|---|---|
| `topic_focus.py` | Revised packs; `filter_hard_rejects`; title/body hits; theme score helpers |
| `selection_triage.py` | Triage prompts, Bedrock call, validate, order fallbacks |
| `generate_digest.py` | New scoring/shortlist/main wiring + report writer |
| `.github/workflows/digest.yml` | Upload `selection-report.md` |
| `tests/test_topic_focus.py` | Soft theme + packs + thin |
| `tests/test_selection_triage.py` | Validate/fallback/reject ordering |
| `tests/test_content_filter.py` | Adjust if main path changes |

## Tasks

### Task 1: topic_focus hard rejects + packs + scoring helpers
- [x] Update `STRATEGIES` packs per spec §4.2
- [x] Replace keyword gate with `filter_hard_rejects` (listicle + thin); keep `filter_allowlisted` as alias
- [x] Add `matched_keywords`, `title_body_hits`, `theme_score` helpers
- [x] Rewrite/add tests; `pytest tests/test_topic_focus.py`

### Task 2: selection_triage module
- [x] Prompts + `triage_shortlist` + `validate_triage` + `ordered_attempt_ids`
- [x] Tests for valid/invalid winner, reject exclusion, none_good_enough
- [x] `pytest tests/test_selection_triage.py`

### Task 3: Wire generate_digest + report + workflow
- [x] New `score_article` / shortlist; main uses triage then generate loop
- [x] Write `selection-report.md`; dry-run mock triage
- [x] Artifact step in `digest.yml`
- [x] Full `pytest` (115 passed)
