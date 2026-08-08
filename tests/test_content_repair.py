import builtins
import json

import bedrock_client as bc
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


def test_generate_and_verify_prompts_frame_search_notes_as_untrusted():
    needle = "untrusted reference data"
    assert needle in rp.GENERATE_SYSTEM_PROMPT.lower()
    assert needle in rp.VERIFY_SYSTEM_PROMPT.lower()


def test_generate_prompts_depersonalize_first_person_journals():
    sys_l = rp.GENERATE_SYSTEM_PROMPT.lower()
    user_l = rp.GENERATE_USER_TEMPLATE.lower()
    assert "knowledge article" in sys_l
    assert "first-person journal" in sys_l
    assert "never present someone else's" in sys_l
    assert "knowledge article, not a personal diary" in user_l
    assert "depersonalize" in user_l


def test_repair_generate_prompts_require_seo_structure():
    user = rp.GENERATE_USER_TEMPLATE
    assert "answer-first" in user
    assert "## Key Takeaways" in user
    assert "## FAQ" in user
    assert "question-style" in user
    assert "cohesive article" in user.lower() or "slide deck" in user.lower()


def test_triage_prompt_flags_fragmented_outline():
    user = rp.TRIAGE_USER_TEMPLATE.lower()
    assert "slide outline" in user or "h2" in user
    assert "key takeaways" in user


def test_needs_structure_rewrite_detects_thin_h2_outline():
    body = """## Intro
In 2026 choosing models is hard.

## The Landscape
One thin paragraph about open-source and commercial models available now.

## TCO Analysis
One thin paragraph about monthly token cost versus GPU hosting overhead.

## Performance
One thin paragraph about benches closing the gap this year for many teams.

## Deployment
One thin paragraph about APIs versus self-hosting trade-offs in production.

## Takeaways
- The market offers many options with different cost profiles for teams.
- TCO beats brand loyalty when you plan for sustained production traffic.
"""
    assert cr.needs_structure_rewrite(body) is True


def test_needs_structure_rewrite_accepts_cohesive_key_takeaways():
    para = (
        "This section explains the trade-offs in enough depth that a working "
        "engineer can act on it. " * 8
    )
    body = f"""Choosing between open-source and commercial LLMs in 2026 comes down to
TCO, ops burden, and model quality for your workload — not brand loyalty alone.

## Key Takeaways
- First takeaway with enough words to count.
- Second takeaway with enough words to count.
- Third takeaway with enough words to count.

## How should you compare TCO?
{para}

## What about performance gaps?
{para}

## How do you deploy either option?
{para}
"""
    assert cr.needs_structure_rewrite(body) is False


def test_verify_prompts_strip_fabricated_autobiography():
    sys_l = rp.VERIFY_SYSTEM_PROMPT.lower()
    user_l = rp.VERIFY_USER_TEMPLATE.lower()
    assert "first-person autobiography" in sys_l
    assert "knowledge-article" in sys_l
    assert "depersonalize" in user_l


def test_triage_prompt_routes_technical_journals_to_rewrite():
    user_l = rp.TRIAGE_USER_TEMPLATE.lower()
    assert "first-person" in user_l
    assert "even if otherwise coherent" in user_l
    assert "never keep someone else's lived experience as clean" in user_l
    # Must not use daily-digest "reject" vocabulary — repair uses junk/rewrite/clean.
    assert "not a reject by themselves" not in user_l


def test_is_valid_slug_rejects_path_traversal():
    assert cr.is_valid_slug("queues-in-practice") is True
    assert cr.is_valid_slug("10-truly-mind-blowing-javascript-tricks-") is True
    assert cr.is_valid_slug("../evil") is False
    assert cr.is_valid_slug("foo/bar") is False
    assert cr.is_valid_slug("foo.bar") is False
    assert cr.is_valid_slug("") is False


def test_apply_kept_frontmatter_sets_required_fields():
    fm = {"title": "T", "source_url": "https://old.example"}
    out = cr.apply_kept_frontmatter(fm, origin="scraper", image_suggestion="desk photo")
    assert out["ai"] is True
    assert out["origin"] == "scraper"
    assert out["author"] == "Mohan Sagar"
    assert out["cover_status"] == "none"
    assert out["image_suggestion"] == "desk photo"
    assert out["source_url"] == "https://old.example"  # preserved, not invented


def test_apply_kept_frontmatter_does_not_invent_source_url():
    fm = {"title": "T"}
    out = cr.apply_kept_frontmatter(fm, origin="bot", image_suggestion="x")
    assert "source_url" not in out


def test_apply_kept_frontmatter_does_not_downgrade_done():
    fm = {"title": "T", "cover_status": "done", "image": "/blog-images/t.jpg"}
    out = cr.apply_kept_frontmatter(fm, origin="bot", image_suggestion="schematic isometric art")
    assert out["cover_status"] == "done"


def test_apply_kept_frontmatter_marks_editorial_cover_done(tmp_path):
    from PIL import Image

    slug = "nav"
    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGB", (1200, 630), (1, 2, 3)).save(images / f"{slug}.jpg", "JPEG")
    fm = {
        "title": "T",
        "slug": slug,
        "image": f"/blog-images/{slug}.jpg",
        "image_prompt": "An off-center soft-focus photo of a vintage computer",
        "cover_status": "none",
    }
    out = cr.apply_kept_frontmatter(
        fm,
        origin="bot",
        image_suggestion="Isometric technical illustration schematic diagram",
        blog_root=str(tmp_path),
        slug=slug,
    )
    assert out["cover_status"] == "done"
    # repair suggestion must not be forced onto editorial posts
    assert out.get("image_suggestion") != "Isometric technical illustration schematic diagram"


def test_apply_kept_frontmatter_wrong_size_stays_none(tmp_path):
    from PIL import Image

    slug = "square"
    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGB", (800, 800), (1, 2, 3)).save(images / f"{slug}.jpg", "JPEG")
    fm = {
        "title": "T",
        "slug": slug,
        "image": f"/blog-images/{slug}.jpg",
        "image_prompt": "soft-focus photo without schematic keywords",
        "cover_status": "none",
    }
    out = cr.apply_kept_frontmatter(
        fm,
        origin="bot",
        image_suggestion="desk photo",
        blog_root=str(tmp_path),
        slug=slug,
    )
    assert out["cover_status"] == "none"
    assert out["image_suggestion"] == "desk photo"


def test_load_dump_mdx_roundtrip(tmp_path):
    path = tmp_path / "post.mdx"
    body = "# Hello\n\nParagraph.\n"
    path.write_text(
        '---\ntitle: "T"\ntags: ["a"]\n---\n' + body,
        encoding="utf-8",
    )
    fm, loaded_body = cr.load_mdx(str(path))
    assert fm["title"] == "T"
    assert loaded_body == body
    out_path = tmp_path / "out.mdx"
    out_path.write_text(cr.dump_mdx(fm, loaded_body), encoding="utf-8")
    fm2, body2 = cr.load_mdx(str(out_path))
    assert fm2["title"] == "T"
    assert body2 == body


def test_maybe_delete_local_cover_skips_external(tmp_path):
    blog = tmp_path
    (blog / "images").mkdir()
    fm = {"image": "https://cdn.example/x.jpg"}
    assert cr.maybe_delete_local_cover(str(blog), fm, "slug") is False


def test_maybe_delete_local_cover_deletes_blog_images_path(tmp_path):
    blog = tmp_path
    images = blog / "images"
    images.mkdir()
    cover = images / "my-post.jpg"
    cover.write_bytes(b"jpeg")
    fm = {"image": "/blog-images/my-post.jpg"}
    assert cr.maybe_delete_local_cover(str(blog), fm, "my-post") is True
    assert not cover.exists()


def test_maybe_delete_local_cover_deletes_images_rel_path(tmp_path):
    blog = tmp_path
    images = blog / "images"
    images.mkdir()
    cover = images / "other.jpg"
    cover.write_bytes(b"jpeg")
    fm = {"image": "images/other.jpg"}
    assert cr.maybe_delete_local_cover(str(blog), fm, "other") is True
    assert not cover.exists()


def test_ledger_skip_when_same_body_hash(tmp_path):
    path = tmp_path / "repair_ledger.json"
    ledger = cr.Ledger(str(path))
    body = "same body"
    ledger.record("slug-a", body, verdict="clean", action="kept")
    assert ledger.should_skip("slug-a", body) is True
    assert ledger.should_skip("slug-a", "different body") is False


def test_ledger_force_bypasses_skip(tmp_path):
    path = tmp_path / "repair_ledger.json"
    ledger = cr.Ledger(str(path))
    body = "same body"
    ledger.record("slug-a", body, verdict="clean", action="kept")
    assert ledger.should_skip("slug-a", body, force=True) is False


def test_ledger_does_not_skip_error_entry_with_matching_body_hash(tmp_path):
    path = tmp_path / "repair_ledger.json"
    ledger = cr.Ledger(str(path))
    body = "same body"

    ledger.record("slug-a", body, verdict="error", action="error")

    assert ledger.should_skip("slug-a", body) is False


def test_converse_retries_retryable_bedrock_failures_with_exponential_backoff(monkeypatch):
    class RetryableError(Exception):
        response = {"Error": {"Code": "ThrottlingException"}, "ResponseMetadata": {"HTTPStatusCode": 429}}

    class Client:
        def __init__(self):
            self.calls = 0

        def converse(self, **_kwargs):
            self.calls += 1
            if self.calls < 3:
                raise RetryableError("throttled")
            return {"usage": {}, "output": {"message": {"content": [{"text": "recovered"}]}}}

    client = Client()
    delays = []
    monkeypatch.setattr(bc, "_client", lambda: client)
    monkeypatch.setattr(bc.time, "sleep", delays.append)

    assert bc.converse("system", "user") == "recovered"
    assert client.calls == 3
    assert delays == [0.1, 0.2]


def test_ledger_records_bedrock_and_search_call_counts(tmp_path):
    path = tmp_path / "repair_ledger.json"
    ledger = cr.Ledger(str(path))

    ledger.record(
        "slug-a",
        "same body",
        verdict="rewrite",
        action="rewritten",
        bedrock_calls=4,
        search_calls=1,
        search_failed=False,
    )

    entry = ledger.load()["slug-a"]
    assert entry["bedrock_calls"] == 4
    assert entry["search_calls"] == 1
    assert entry["search_failed"] is False


def _write_post(blog_root, slug, *, title="Legacy post", body="Original body.\n", **fm):
    posts = blog_root / "posts"
    posts.mkdir(exist_ok=True)
    frontmatter = {"title": title, "slug": slug, **fm}
    (posts / f"{slug}.mdx").write_text(
        cr.dump_mdx(frontmatter, body), encoding="utf-8"
    )


def _mock_bedrock(monkeypatch, responses, prompts):
    def converse(_system, prompt, **_kwargs):
        prompts.append(prompt)
        response = responses.pop(0)
        return response if isinstance(response, str) else json.dumps(response)

    monkeypatch.setattr("bedrock_client.converse", converse)


def test_repair_one_junk_deletes(tmp_path, monkeypatch):
    _write_post(tmp_path, "junk", body="cookie banner")
    prompts = []
    _mock_bedrock(
        monkeypatch,
        [{"verdict": "junk", "confidence": "high", "reason": "boilerplate"}],
        prompts,
    )
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))

    result = cr.repair_one(str(tmp_path), "junk")

    assert result["action"] == "deleted"
    assert not (tmp_path / "posts" / "junk.mdx").exists()


def test_repair_one_dry_run_junk_delete_is_would_delete(tmp_path, monkeypatch):
    _write_post(tmp_path, "junk", body="cookie banner")
    prompts = []
    _mock_bedrock(
        monkeypatch,
        [{"verdict": "junk", "confidence": "high", "reason": "boilerplate"}],
        prompts,
    )
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))

    result = cr.repair_one(str(tmp_path), "junk", dry_run=True)

    assert result["action"] == "would_delete"
    assert (tmp_path / "posts" / "junk.mdx").exists()
    assert not (tmp_path / "ledger.json").exists()


def test_repair_one_clean_stamps_frontmatter(tmp_path, monkeypatch):
    _write_post(tmp_path, "clean", body="Coherent existing body.\n")
    prompts = []
    _mock_bedrock(
        monkeypatch,
        [
            {"verdict": "clean", "confidence": "high", "reason": "coherent"},
            "An abstract set of linked service nodes.",
        ],
        prompts,
    )
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))

    result = cr.repair_one(str(tmp_path), "clean")
    fm, body = cr.load_mdx(str(tmp_path / "posts" / "clean.mdx"))

    assert result["action"] == "kept"
    assert body == "Coherent existing body.\n"
    assert fm["ai"] is True
    assert fm["origin"] == "scraper"
    assert fm["author"] == "Mohan Sagar"
    assert fm["cover_status"] == "none"
    assert fm["image_suggestion"] == "An abstract set of linked service nodes."
    entry = cr.Ledger(str(tmp_path / "ledger.json")).load()["clean"]
    assert entry["bedrock_calls"] == 2
    assert entry["search_calls"] == 0
    assert entry["search_failed"] is False


def test_repair_one_upgrades_clean_triage_with_unclosed_fence_to_rewrite(tmp_path, monkeypatch):
    _write_post(tmp_path, "broken", body="# Legacy code\n\n```python\nprint('unfinished')\n")
    prompts = []
    _mock_bedrock(
        monkeypatch,
        [
            {"verdict": "clean", "confidence": "high", "reason": "coherent"},
            {
                "headline": "Fixed code",
                "subtitle": "A complete example",
                "meta_description": "A repaired post.",
                "tags": ["python"],
                "body_markdown": "Generated body.\n",
            },
            {"verdict": "pass", "issues": [], "corrected_body_markdown": "Verified body.\n"},
            "An abstract code workspace.",
        ],
        prompts,
    )
    monkeypatch.setattr("search_client.search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))

    result = cr.repair_one(str(tmp_path), "broken")

    assert result["action"] == "rewritten"
    assert result["verdict"] == "rewrite"
    assert "unclosed code fence" in result["reason"]


def test_repair_one_upgrades_junk_triage_with_unclosed_fence_to_rewrite(tmp_path, monkeypatch):
    _write_post(tmp_path, "mangled", body="# Scraped\n\n```js\nconsole.log('oops')\n")
    prompts = []
    _mock_bedrock(
        monkeypatch,
        [
            {"verdict": "junk", "confidence": "high", "reason": "unreadable scrape"},
            {
                "headline": "Recovered post",
                "subtitle": "From a broken scrape",
                "meta_description": "A repaired post.",
                "tags": ["javascript"],
                "body_markdown": "Generated body.\n",
            },
            {"verdict": "pass", "issues": [], "corrected_body_markdown": "Verified body.\n"},
            "An abstract code workspace.",
        ],
        prompts,
    )
    monkeypatch.setattr("search_client.search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))

    result = cr.repair_one(str(tmp_path), "mangled")

    assert result["action"] == "rewritten"
    assert result["verdict"] == "rewrite"
    assert "unclosed code fence" in result["reason"]
    assert (tmp_path / "posts" / "mangled.mdx").exists()


def test_repair_one_load_failure_is_fail_soft(tmp_path, monkeypatch):
    posts = tmp_path / "posts"
    posts.mkdir()
    (posts / "broken.mdx").write_text("not valid front matter\n", encoding="utf-8")
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))

    result = cr.repair_one(str(tmp_path), "broken")

    assert result["action"] == "error"
    assert result["reason"].startswith("load failed:")
    entry = cr.Ledger(str(tmp_path / "ledger.json")).load()["broken"]
    assert entry["action"] == "error"


def test_repair_one_rejects_invalid_slug_before_path_join(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))

    result = cr.repair_one(str(tmp_path), "../evil")

    assert result["action"] == "error"
    assert "invalid slug" in result["reason"]
    assert not (tmp_path / "ledger.json").exists()


def test_repair_one_clears_stale_image_suggestion_after_rewrite_failure(tmp_path, monkeypatch):
    _write_post(
        tmp_path,
        "stale-cover",
        body="Thin body.\n",
        image_suggestion="Old cover about cookies",
    )
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setattr("search_client.search", lambda *_args, **_kwargs: [])
    responses = [
        {"verdict": "rewrite", "confidence": "high", "reason": "too thin"},
        {
            "headline": "Queues",
            "subtitle": "Better",
            "meta_description": "A better post.",
            "tags": ["queues"],
            "body_markdown": "Generated body.\n",
        },
        {"verdict": "pass", "issues": [], "corrected_body_markdown": "Verified body.\n"},
        RuntimeError("image suggestion unavailable"),
    ]

    def converse(_system, _prompt, **_kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, str) else json.dumps(response)

    monkeypatch.setattr("bedrock_client.converse", converse)

    result = cr.repair_one(str(tmp_path), "stale-cover")
    fm, _body = cr.load_mdx(str(tmp_path / "posts" / "stale-cover.mdx"))

    assert result["action"] == "rewritten"
    assert result["image_suggestion_error"] == "RuntimeError"
    assert fm["image_suggestion"] == ""
    assert fm["title"] == "Queues"


def test_repair_one_rewrite_uses_search_notes(tmp_path, monkeypatch):
    _write_post(tmp_path, "rewrite", title="Queues", body="Queues buffer work.\n")
    prompts = []
    _mock_bedrock(
        monkeypatch,
        [
            {"verdict": "rewrite", "confidence": "medium", "reason": "too thin"},
            {
                "headline": "Queues in practice",
                "subtitle": "Handling bursts",
                "meta_description": "A practical guide to queues.",
                "tags": ["queues"],
                "body_markdown": "Generated body.\n",
            },
            {
                "verdict": "pass",
                "issues": [],
                "corrected_body_markdown": "Verified body.\n",
            },
            "An abstract buffering pipeline.",
        ],
        prompts,
    )
    monkeypatch.setattr(
        "search_client.search",
        lambda query, max_results=5: [
            {"title": "Queue docs", "url": "https://example.test/queues", "snippet": "FIFO"}
        ],
    )
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))

    result = cr.repair_one(str(tmp_path), "rewrite")
    fm, body = cr.load_mdx(str(tmp_path / "posts" / "rewrite.mdx"))

    assert result["action"] == "rewritten"
    assert body == "Verified body.\n"
    assert fm["title"] == "Queues in practice"
    assert "Queue docs" in prompts[1]
    assert "https://example.test/queues" in prompts[1]
    entry = cr.Ledger(str(tmp_path / "ledger.json")).load()["rewrite"]
    assert entry["bedrock_calls"] == 4
    assert entry["search_calls"] == 1
    assert entry["search_failed"] is False


def test_repair_one_records_failed_search_attempt_in_ledger(tmp_path, monkeypatch):
    _write_post(tmp_path, "search-failure")
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setattr("search_client.search", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    prompts = []
    _mock_bedrock(
        monkeypatch,
        [
            {"verdict": "rewrite", "confidence": "high", "reason": "needs work"},
            {
                "headline": "Rewritten",
                "subtitle": "Better",
                "meta_description": "A better post.",
                "tags": ["repair"],
                "body_markdown": "Generated body.\n",
            },
            {"verdict": "pass", "issues": [], "corrected_body_markdown": "Verified body.\n"},
            "An abstract technical cover.",
        ],
        prompts,
    )

    assert cr.repair_one(str(tmp_path), "search-failure")["action"] == "rewritten"

    entry = cr.Ledger(str(tmp_path / "ledger.json")).load()["search-failure"]
    assert entry["bedrock_calls"] == 4
    assert entry["search_calls"] == 1
    assert entry["search_failed"] is True


def test_repair_one_retries_after_triage_failure_without_ledger_skip(tmp_path, monkeypatch):
    _write_post(tmp_path, "triage-failure")
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    responses = [
        RuntimeError("Bedrock unavailable"),
        {"verdict": "clean", "confidence": "high", "reason": "coherent"},
        "An abstract technical cover.",
    ]

    def converse(_system, _prompt, **_kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, str) else json.dumps(response)

    monkeypatch.setattr("bedrock_client.converse", converse)

    assert cr.repair_one(str(tmp_path), "triage-failure")["action"] == "error"
    entry = cr.Ledger(str(tmp_path / "ledger.json")).load()["triage-failure"]
    assert entry["action"] == "error"
    assert entry["bedrock_calls"] == 1
    assert entry["search_calls"] == 0
    assert cr.repair_one(str(tmp_path), "triage-failure")["action"] == "kept"


def test_repair_one_retries_after_rewrite_failure_without_ledger_skip(tmp_path, monkeypatch):
    _write_post(tmp_path, "rewrite-failure")
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setattr("search_client.search", lambda *_args, **_kwargs: [])
    responses = [
        {"verdict": "rewrite", "confidence": "high", "reason": "needs work"},
        RuntimeError("Bedrock unavailable"),
        {"verdict": "rewrite", "confidence": "high", "reason": "needs work"},
        {
            "headline": "Rewritten",
            "subtitle": "Better",
            "meta_description": "A better post.",
            "tags": ["repair"],
            "body_markdown": "Generated body.\n",
        },
        {"verdict": "pass", "issues": [], "corrected_body_markdown": "Verified body.\n"},
        "An abstract technical cover.",
    ]

    def converse(_system, _prompt, **_kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, str) else json.dumps(response)

    monkeypatch.setattr("bedrock_client.converse", converse)

    assert cr.repair_one(str(tmp_path), "rewrite-failure")["action"] == "error"
    entry = cr.Ledger(str(tmp_path / "ledger.json")).load()["rewrite-failure"]
    assert entry["action"] == "error"
    assert entry["bedrock_calls"] == 2
    assert entry["search_calls"] == 1
    assert cr.repair_one(str(tmp_path), "rewrite-failure")["action"] == "rewritten"


def test_repair_one_retries_after_write_failure_without_ledger_skip(tmp_path, monkeypatch):
    _write_post(tmp_path, "write-failure")
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    original_open = builtins.open
    write_attempts = 0

    def failing_once_open(path, mode="r", *args, **kwargs):
        nonlocal write_attempts
        is_post_write = str(path).endswith("write-failure.mdx") and mode == "w"
        if is_post_write:
            write_attempts += 1
        if is_post_write and write_attempts == 1:
            raise OSError("disk full")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(cr, "open", failing_once_open, raising=False)
    prompts = []
    _mock_bedrock(
        monkeypatch,
        [
            {"verdict": "clean", "confidence": "high", "reason": "coherent"},
            "An abstract technical cover.",
            {"verdict": "clean", "confidence": "high", "reason": "coherent"},
            "An abstract technical cover.",
        ],
        prompts,
    )

    assert cr.repair_one(str(tmp_path), "write-failure")["action"] == "error"
    entry = cr.Ledger(str(tmp_path / "ledger.json")).load()["write-failure"]
    assert entry["action"] == "error"
    assert entry["bedrock_calls"] == 2
    assert entry["search_calls"] == 0
    assert cr.repair_one(str(tmp_path), "write-failure")["action"] == "kept"


def test_main_dry_run_writes_report_without_mdx_or_ledger_changes(tmp_path, monkeypatch):
    _write_post(tmp_path, "dry", body="Existing content.\n")
    original = (tmp_path / "posts" / "dry.mdx").read_text(encoding="utf-8")
    prompts = []
    _mock_bedrock(
        monkeypatch,
        [{"verdict": "clean", "confidence": "high", "reason": "coherent"}],
        prompts,
    )
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(ledger_path))

    records = cr.main(["--blog-root", str(tmp_path), "--dry-run"])

    assert records[0]["action"] == "would_keep"
    assert (tmp_path / "posts" / "dry.mdx").read_text(encoding="utf-8") == original
    assert not ledger_path.exists()
    report = (tmp_path / "triage-report.md").read_text(encoding="utf-8")
    assert "| dry | clean | high | would_keep | coherent |  |" in report
    assert "image_suggestion_error" in report


def test_main_continues_past_malformed_mdx(tmp_path, monkeypatch):
    posts = tmp_path / "posts"
    posts.mkdir()
    (posts / "aaa-broken.mdx").write_text("---\ntitle: [unterminated\n", encoding="utf-8")
    _write_post(tmp_path, "zzz-ok", body="Coherent body.\n")
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    prompts = []
    _mock_bedrock(
        monkeypatch,
        [
            {"verdict": "clean", "confidence": "high", "reason": "coherent"},
            "An abstract technical cover.",
        ],
        prompts,
    )

    records = cr.main(["--blog-root", str(tmp_path)])

    assert records[0]["slug"] == "aaa-broken"
    assert records[0]["action"] == "error"
    assert records[1]["slug"] == "zzz-ok"
    assert records[1]["action"] == "kept"


def test_main_limit_counts_only_unfinished_posts(tmp_path, monkeypatch):
    _write_post(tmp_path, "already", body="Already repaired.\n")
    _write_post(tmp_path, "next", body="Needs processing.\n")
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setattr(cr, "DEFAULT_LEDGER_PATH", str(ledger_path))
    cr.Ledger(str(ledger_path)).record("already", "Already repaired.\n", action="kept")
    prompts = []
    _mock_bedrock(
        monkeypatch,
        [
            {"verdict": "clean", "confidence": "high", "reason": "coherent"},
            "An abstract technical cover.",
        ],
        prompts,
    )

    records = cr.main(["--blog-root", str(tmp_path), "--limit", "1"])

    assert [record["slug"] for record in records] == ["already", "next"]
    assert records[-1]["action"] == "kept"
