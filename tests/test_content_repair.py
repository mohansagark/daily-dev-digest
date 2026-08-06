import content_repair as cr
import repair_prompts as rp
import json


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
    assert "| dry | clean | high | would_keep | coherent |" in report


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
