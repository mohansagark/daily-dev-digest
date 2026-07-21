import pytest
import cover_backfill as cb

SAMPLE = """---
title: "Some Post"
subtitle: "A dek"
summary: "A summary with: a colon"
slug: "some-post"
date: "2026-07-20"
time: "14:53"
content_strategy: "Frontend and JavaScript engineering"
writing_style: "energetic and practical"
tags: ["react", "hooks"]
source_url: "https://example.com/article"
published_date: "Fri, 18 Jul 2026 20:31:41 +0000"
author: "Mohan Sagar"
---

## The Body

Real content here. Do not touch me.
"""


def _split(text):
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return text[4:end], text[end:]


def test_inserts_three_image_lines_after_tags():
    out = cb.attach_image_frontmatter(
        SAMPLE, "/blog-images/some-post.jpg", "alt text", "the full prompt"
    )
    fm, _ = _split(out)
    lines = fm.split("\n")
    tags_i = next(i for i, l in enumerate(lines) if l.startswith("tags:"))
    assert lines[tags_i + 1].startswith("image:")
    assert lines[tags_i + 2].startswith("image_alt:")
    assert lines[tags_i + 3].startswith("image_prompt:")
    # source_url stays immediately after the image block (adjacency preserved)
    assert lines[tags_i + 4].startswith("source_url:")


def test_body_is_byte_identical():
    out = cb.attach_image_frontmatter(SAMPLE, "/blog-images/some-post.jpg", "a", "p")
    _, body_in = _split(SAMPLE)
    _, body_out = _split(out)
    assert body_out == body_in


def test_result_is_valid_yaml_with_expected_values():
    yaml = pytest.importorskip("yaml")
    out = cb.attach_image_frontmatter(
        SAMPLE, "/blog-images/some-post.jpg", 'alt with "quotes"', "prompt: with colon"
    )
    fm, _ = _split(out)
    d = yaml.safe_load(fm)
    assert d["image"] == "/blog-images/some-post.jpg"
    assert d["image_alt"] == 'alt with "quotes"'
    assert d["image_prompt"] == "prompt: with colon"
    # untouched fields survive
    assert d["source_url"] == "https://example.com/article"
    assert d["slug"] == "some-post"


def test_idempotent_when_image_already_present():
    once = cb.attach_image_frontmatter(SAMPLE, "/blog-images/some-post.jpg", "a", "p")
    twice = cb.attach_image_frontmatter(once, "/blog-images/OTHER.jpg", "b", "q")
    assert twice == once  # already has image: -> unchanged, no double-splice


def test_raises_on_malformed_frontmatter():
    with pytest.raises(ValueError):
        cb.attach_image_frontmatter("no front matter here", "/x.jpg", "a", "p")


def test_missing_tags_line_still_inserts_before_source_url():
    no_tags = SAMPLE.replace('tags: ["react", "hooks"]\n', "")
    out = cb.attach_image_frontmatter(no_tags, "/blog-images/x.jpg", "a", "p")
    fm, _ = _split(out)
    lines = fm.split("\n")
    img_i = next(i for i, l in enumerate(lines) if l.startswith("image:"))
    assert lines[img_i + 3].startswith("source_url:")


def _real_jpeg(px=1024):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (px, px), (60, 90, 160)).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_regenerate_cover_attaches_and_keeps_body(tmp_path, monkeypatch):
    root = tmp_path / "blog"
    (root / "posts").mkdir(parents=True)
    (root / "images").mkdir()
    post = root / "posts" / "some-post.mdx"
    post.write_text(SAMPLE)

    monkeypatch.setattr(cb, "generate_image_brief",
                        lambda *a, **k: {"subject": "a node graph", "palette": "blue"})
    monkeypatch.setattr(cb.image_client, "generate", lambda prompt, **k: _real_jpeg())

    r = cb.regenerate_cover(str(root), "some-post",
                            dry_run=False, review_dir=str(tmp_path / "review"))
    assert r["status"] == "attached"

    import yaml
    out = post.read_text()
    end = out.index("\n---\n", 4)
    d = yaml.safe_load(out[4:end])
    assert d["image"] == "/blog-images/some-post.jpg"
    assert d["image_alt"] == "a node graph"
    assert "isometric technical illustration" in d["image_prompt"]
    # body untouched
    assert "Real content here. Do not touch me." in out[end:]
    # image file written + downscaled
    assert (root / "images" / "some-post.jpg").exists()


def test_dry_run_writes_no_post_or_image(tmp_path, monkeypatch):
    root = tmp_path / "blog"
    (root / "posts").mkdir(parents=True)
    (root / "images").mkdir()
    post = root / "posts" / "some-post.mdx"
    original = SAMPLE
    post.write_text(original)

    monkeypatch.setattr(cb, "generate_image_brief", lambda *a, **k: {"subject": "x"})
    monkeypatch.setattr(cb.image_client, "generate", lambda prompt, **k: _real_jpeg())

    r = cb.regenerate_cover(str(root), "some-post",
                            dry_run=True, review_dir=str(tmp_path / "review"))
    assert r["status"] == "rendered"
    assert post.read_text() == original           # post untouched
    assert not (root / "images" / "some-post.jpg").exists()  # no committed image
    assert (tmp_path / "review" / "some-post.jpg").exists()  # preview written
