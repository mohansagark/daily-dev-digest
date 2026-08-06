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
