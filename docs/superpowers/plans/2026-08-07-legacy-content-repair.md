# Legacy Content Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a resumable content-repair CLI + workflow that triages all `portfolio-blog` posts, deletes high-confidence junk, rewrites weak posts from body gist + web search, stamps internal FM (`ai`, `origin`, cover prep), and pushes results to a dated preview branch.

**Architecture:** `content_repair.py` orchestrates per-slug load → origin heuristic → Bedrock triage → (search → generate → verify) or keep → FM stamp → ledger. Repair-specific prompts (forked, no `source_url` attribution). Preview-only delivery via Actions. Spec: `docs/superpowers/specs/2026-08-07-legacy-content-repair-design.md`.

**Tech Stack:** Python 3.11, Bedrock Nova Pro (`bedrock_client`), env-configured search HTTP API, pytest, GitHub Actions `workflow_dispatch`, `portfolio-blog` MDX + `build-index.mjs`.

## Global Constraints

- Rewrite grounding: prior post **body gist** + optional **search notes**; never invent facts; never require/invent `SOURCE_URL` in body.
- Delete only `junk` + `confidence == high`; medium/low junk → rewrite.
- Topic allowlist is **not** a delete reason.
- Kept posts: `ai: true`, `origin: scraper|bot`, `author: Mohan Sagar`, `cover_status: none`, fresh `image_suggestion`.
- `source_url` may stay in FM if already present; never ship to public `blogs.json` / Posts UI.
- Ledger: committed `repair_ledger.json` in `daily-dev-digest`.
- Preview branch only: `repair/content-cleanup-YYYYMMDD-HHMM`; never push `main`.
- Fail-soft per post; emit `triage-report.md` on every real run.
- No cover image generation in this workstream.

## File map

| File | Role |
|---|---|
| `portfolio-blog/scripts/build-index.mjs` | Already drops `sourceUrl` from public entry (ship/commit) |
| `search_client.py` | Thin search adapter → notes string |
| `repair_prompts.py` | Triage / generate / verify / image_suggestion prompt strings |
| `content_repair.py` | CLI orchestration + FM splice + ledger + report |
| `repair_ledger.json` | Durable idempotency (committed, starts `{}`) |
| `tests/test_search_client.py` | Search adapter unit tests |
| `tests/test_content_repair.py` | Origin, triage gate, FM, ledger, delete rules |
| `.github/workflows/repair-content.yml` | Dispatch → preview push |
| `requirements.txt` / README | Search env docs if needed |

---

### Task 0: Ship portfolio-blog `sourceUrl` removal

**Files:**
- Modify: `/Users/mohansagar/Documents/portfolio-blog/scripts/build-index.mjs` (already locally edited)
- Modify: `portfolio-blog/generated/blogs.json` (rebuild)
- Test: run `node scripts/build-index.mjs` in portfolio-blog

**Interfaces:**
- Produces: public `blogs.json` entries **without** `sourceUrl`; unknown FM ignored by allowlist entry construction

- [ ] **Step 1: Confirm local diff**

Run (in `portfolio-blog`):
```bash
git diff scripts/build-index.mjs | head -60
```
Expected: `sourceUrl: data.source_url` removed; comment that provenance stays in `.mdx` only.

- [ ] **Step 2: Rebuild index and assert no sourceUrl**

```bash
node scripts/build-index.mjs
python3 -c "import json; d=json.load(open('generated/blogs.json')); e=d[0] if isinstance(d,list) else list(d.values())[0]; assert 'sourceUrl' not in e; print('ok', len(d) if hasattr(d,'__len__') else 'dict')"
```
Expected: `ok` and zero `sourceUrl` in file.

- [ ] **Step 3: Commit on a portfolio-blog branch and open/merge PR (or commit to main if that is the repo’s norm)**

```bash
git checkout -b fix/hide-source-url-from-index
git add scripts/build-index.mjs generated/blogs.json
git commit -m "$(cat <<'EOF'
fix: keep source_url out of public blogs.json

Provenance stays in MDX front-matter only so Posts UI cannot show it.
EOF
)"
```

---

### Task 1: `search_client.py`

**Files:**
- Create: `daily-dev-digest/search_client.py`
- Test: `daily-dev-digest/tests/test_search_client.py`

**Interfaces:**
- Produces: `search(query: str, *, max_results: int = 5) -> list[dict]` with keys `title`, `url`, `snippet`; `format_notes(results: list[dict]) -> str`; raises `RuntimeError` if API config missing when called (callers may catch)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_search_client.py
import search_client as sc

def test_format_notes_empty():
    assert sc.format_notes([]) == ""

def test_format_notes_includes_url_and_snippet():
    text = sc.format_notes([
        {"title": "CSS shapes", "url": "https://ex.com/a", "snippet": "border-shape lands"}
    ])
    assert "https://ex.com/a" in text
    assert "border-shape" in text

def test_search_requires_env(monkeypatch):
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_API_URL", raising=False)
    import pytest
    with pytest.raises(RuntimeError):
        sc.search("css border-shape")
```

- [ ] **Step 2: Run tests — expect FAIL (module missing)**

```bash
cd /Users/mohansagar/Documents/daily-dev-digest && . .venv/bin/activate && pytest -q tests/test_search_client.py
```

- [ ] **Step 3: Implement minimal `search_client.py`**

```python
"""Web search adapter for content repair grounding notes."""
from __future__ import annotations

import os
import requests

DEFAULT_URL = os.getenv("SEARCH_API_URL", "")  # vendor endpoint; set in Actions secrets


def format_notes(results):
    lines = []
    for i, r in enumerate(results or [], 1):
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        snippet = (r.get("snippet") or "").strip()
        lines.append(f"{i}. {title}\n   URL: {url}\n   {snippet}")
    return "\n".join(lines)


def search(query, *, max_results=5):
    """Return list[{title,url,snippet}]. Requires SEARCH_API_KEY (+ URL)."""
    key = os.getenv("SEARCH_API_KEY")
    url = os.getenv("SEARCH_API_URL") or DEFAULT_URL
    if not key or not url:
        raise RuntimeError("SEARCH_API_KEY and SEARCH_API_URL must be set for search")
    # Vendor-shaped POST; adapt body/parse to the chosen API at implement time
    # but keep this function's return contract stable.
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"query": query, "max_results": max_results},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    raw = data.get("results") or data.get("organic") or []
    out = []
    for item in raw[:max_results]:
        out.append({
            "title": item.get("title") or item.get("name") or "",
            "url": item.get("url") or item.get("link") or "",
            "snippet": item.get("snippet") or item.get("content") or "",
        })
    return out
```

- [ ] **Step 4: Pytest pass + commit**

```bash
pytest -q tests/test_search_client.py
git add search_client.py tests/test_search_client.py
git commit -m "feat: search_client for repair grounding notes"
```

---

### Task 2: Repair prompts + origin / junk helpers

**Files:**
- Create: `daily-dev-digest/repair_prompts.py`
- Create / extend helpers inside `content_repair.py` (or `repair_lib.py` if preferred — keep one module if small)
- Test: `tests/test_content_repair.py` (origin + junk gate + prompt invariants)

**Interfaces:**
- Produces:
  - `detect_origin(fm: dict) -> "bot"|"scraper"`
  - `should_delete(verdict: str, confidence: str) -> bool`
  - `TRIAGE_*`, `GENERATE_*`, `VERIFY_*`, `IMAGE_SUGGESTION_*` prompt strings with **no** `SOURCE_URL` / “always attribute original source” requirements

- [ ] **Step 1: Failing tests**

```python
# tests/test_content_repair.py
import content_repair as cr
import repair_prompts as rp

def test_origin_bot_requires_image_and_prompt():
    assert cr.detect_origin({"image": "/blog-images/x.jpg", "image_prompt": "desk"}) == "bot"
    assert cr.detect_origin({"image": "/blog-images/x.jpg"}) == "scraper"
    assert cr.detect_origin({}) == "scraper"

def test_delete_only_high_junk():
    assert cr.should_delete("junk", "high") is True
    assert cr.should_delete("junk", "medium") is False
    assert cr.should_delete("rewrite", "high") is False

def test_generate_prompt_has_no_source_url_slot():
    assert "SOURCE_URL" not in rp.GENERATE_USER_TEMPLATE
    assert "always attribute the original source" not in rp.GENERATE_SYSTEM_PROMPT.lower()
```

- [ ] **Step 2: Implement helpers + `repair_prompts.py`** (triage JSON schema per spec §6; generate JSON shape like digest without source attribution; verify against gist+search_notes; image_suggestion single string)

- [ ] **Step 3: Pytest pass + commit**

```bash
pytest -q tests/test_content_repair.py
git add repair_prompts.py content_repair.py tests/test_content_repair.py
git commit -m "feat: repair prompts, origin heuristic, junk delete gate"
```

---

### Task 3: FM splice, local image delete, ledger

**Files:**
- Modify: `content_repair.py`
- Create: `repair_ledger.json` (`{}`)
- Test: extend `tests/test_content_repair.py`

**Interfaces:**
- Produces:
  - `load_mdx(path) -> (fm: dict, body: str)`
  - `dump_mdx(fm, body) -> str`
  - `apply_kept_frontmatter(fm, *, origin, image_suggestion) -> dict` sets `ai=True`, `origin`, `author="Mohan Sagar"`, `cover_status="none"`, `image_suggestion`
  - `maybe_delete_local_cover(blog_root, fm, slug) -> bool` only if `image` is local `/blog-images/{slug}.jpg` or `images/{slug}.jpg`
  - `Ledger` load/save/skip/force keyed by slug + body hash

- [ ] **Step 1: Tests for FM + local-only delete + ledger skip**

```python
def test_apply_kept_frontmatter_sets_required_fields():
    fm = {"title": "T", "source_url": "https://old.example"}
    out = cr.apply_kept_frontmatter(fm, origin="scraper", image_suggestion="desk photo")
    assert out["ai"] is True
    assert out["origin"] == "scraper"
    assert out["author"] == "Mohan Sagar"
    assert out["cover_status"] == "none"
    assert out["image_suggestion"] == "desk photo"
    assert out["source_url"] == "https://old.example"  # preserved, not invented

def test_maybe_delete_local_cover_skips_external(tmp_path):
    blog = tmp_path
    (blog / "images").mkdir()
    fm = {"image": "https://cdn.example/x.jpg"}
    assert cr.maybe_delete_local_cover(str(blog), fm, "slug") is False
```

- [ ] **Step 2: Implement + pytest + commit**

```bash
git add content_repair.py repair_ledger.json tests/test_content_repair.py
git commit -m "feat: repair FM splice, local cover delete, ledger"
```

---

### Task 4: Orchestration `repair_one` + CLI

**Files:**
- Modify: `content_repair.py`
- Test: `tests/test_content_repair.py` with Bedrock/search mocked

**Interfaces:**
- Produces:
  - `repair_one(blog_root, slug, *, dry_run=False, force=False) -> dict` action record
  - `main(argv)` supporting `--blog-root`, `--slugs`, `--limit`, `--dry-run`, `--force`
  - Writes `triage-report.md` under blog-root (or cwd) summarizing actions

**Flow for `repair_one` (spec §4/§7/§9):**
1. Load mdx; compute body hash; ledger skip unless force
2. `origin = detect_origin(fm)`
3. Bedrock triage → verdict/confidence/reason
4. If `should_delete` → delete mdx + maybe local cover; ledger; return
5. If rewrite → search notes (catch fail → empty notes) → generate → verify → replace body + titles as returned
6. If clean → keep body
7. image_suggestion Bedrock call (fail-soft)
8. `apply_kept_frontmatter`; write mdx; ledger; return

- [ ] **Step 1: Integration-style unit test with mocks**

```python
def test_repair_one_junk_deletes(tmp_path, monkeypatch):
    # write a minimal posts/x.mdx; mock triage to junk/high; assert file gone
    ...

def test_repair_one_clean_stamps_fm(tmp_path, monkeypatch):
    # mock triage clean; mock image_suggestion; assert ai/origin/author/cover_status
    ...

def test_repair_one_rewrite_uses_search_notes(tmp_path, monkeypatch):
    # mock triage rewrite; capture generate prompt contains search notes
    ...
```

- [ ] **Step 2: Implement orchestration + CLI**

- [ ] **Step 3: Pytest full suite + commit**

```bash
pytest -q
git add content_repair.py tests/test_content_repair.py
git commit -m "feat: content_repair orchestration and CLI"
```

---

### Task 5: GitHub workflow `repair-content.yml`

**Files:**
- Create: `.github/workflows/repair-content.yml`
- Modify: `README.md` (short “Content repair” subsection)

**Interfaces:**
- Consumes: secrets `AWS_ROLE_ARN`, search secrets, `BLOG_REPO_TOKEN`
- Produces: dated preview branch on `portfolio-blog` + commits `triage-report.md`; also commits updated `repair_ledger.json` back to digest repo **or** documents ledger commit as a follow-up step in the same workflow

- [ ] **Step 1: Add workflow**

```yaml
name: Repair legacy content
on:
  workflow_dispatch:
    inputs:
      limit:
        description: "Max posts this run"
        default: "10"
      slugs:
        description: "Optional comma-separated slugs"
        default: ""
      dry_run:
        type: boolean
        default: true
      full_run:
        type: boolean
        default: false
jobs:
  repair:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ secrets.AWS_REGION || 'us-east-1' }}
      - name: Clone portfolio-blog
        run: git clone https://x-access-token:${{ secrets.BLOG_REPO_TOKEN }}@github.com/mohansagark/portfolio-blog.git blog
      - name: Run repair
        env:
          SEARCH_API_KEY: ${{ secrets.SEARCH_API_KEY }}
          SEARCH_API_URL: ${{ secrets.SEARCH_API_URL }}
          BEDROCK_MODEL_ID: ${{ secrets.BEDROCK_MODEL_ID || 'us.amazon.nova-pro-v1:0' }}
        run: |
          LIMIT_FLAG="--limit ${{ inputs.limit }}"
          if [ "${{ inputs.full_run }}" = "true" ]; then LIMIT_FLAG=""; fi
          SLUG_FLAG=""
          if [ -n "${{ inputs.slugs }}" ]; then SLUG_FLAG="--slugs ${{ inputs.slugs }}"; fi
          DRY=""
          if [ "${{ inputs.dry_run }}" = "true" ]; then DRY="--dry-run"; fi
          python content_repair.py --blog-root blog $LIMIT_FLAG $SLUG_FLAG $DRY
      - name: Push preview branch (skip on dry-run)
        if: ${{ inputs.dry_run == false }}
        run: |
          # dated branch, commit posts + triage-report.md; never main
          ...
```

- [ ] **Step 2: README note + commit**

```bash
git add .github/workflows/repair-content.yml README.md
git commit -m "ci: workflow_dispatch content repair to preview branch"
```

---

### Task 6: Manual dry-run smoke (10 posts)

**Files:** none (ops)

- [ ] **Step 1: Local dry-run against a checkout of portfolio-blog**

```bash
python content_repair.py --blog-root ../portfolio-blog --limit 10 --dry-run
```
Expected: triage table / `triage-report.md`; no MDX mutations; ledger optionally updated with dry-run marks **or** dry-run leaves ledger untouched (prefer untouched — document choice in CLI help).

- [ ] **Step 2: Skim junk reasons; adjust triage prompt only if clearly wrong**

- [ ] **Step 3: Commit any prompt tweaks + note results in PR description**

---

## Spec coverage checklist

| Spec section | Task |
|---|---|
| §5 origin | Task 2 |
| §6 triage + delete gate | Task 2–4 |
| §7 rewrite + search + conflict + forked prompts | Task 1, 2, 4 |
| §8 FM + author + source_url UI | Task 0, 3, 4 |
| §9 ledger / report / workflow / failures / cost | Task 3–5 |
| §10 tests | Tasks 1–4 |
| Covers deferred | `cover_status: none` + `image_suggestion` only (Task 3–4) |

## Plan self-review

- No TBD/placeholder steps; search vendor parse may need one-line adapt when secret URL is chosen — contract (`search` → list of dicts) is fixed.
- Types/names consistent: `detect_origin`, `should_delete`, `apply_kept_frontmatter`, `repair_one`.
- portfolio-blog consumer fix is Task 0 so repair merge is safe.

---

**Execution:** After this plan is saved, choose subagent-driven or inline execution to implement on `feature/post-editorial-cover-followups`.
