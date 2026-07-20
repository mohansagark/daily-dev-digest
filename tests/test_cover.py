import os
import generate_digest as gd

GEN = {"headline": "Great Post",
       "tags": ["css"],
       "image_brief": {"subject": "a glowing prism", "composition": "centered",
                       "mood": "calm", "palette": "indigo, amber"}}


def test_save_cover_image_writes_and_returns_rel(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "IMAGES_SUBDIR", str(tmp_path / "images"))
    rel = gd.save_cover_image(b"JPEGDATA", "my-slug")
    assert rel == "/blog-images/my-slug.jpg"
    assert (tmp_path / "images" / "my-slug.jpg").read_bytes() == b"JPEGDATA"


def test_dry_run_returns_none(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(gd.image_client, "generate", lambda *a, **k: called.__setitem__("n", 1))
    assert gd.maybe_generate_cover(GEN, "slug", dry_run=True) is None
    assert called["n"] == 0                       # no network in dry-run


def test_success_returns_cover_dict(monkeypatch):
    monkeypatch.setattr(gd.image_client, "generate", lambda prompt, **k: b"IMG")
    monkeypatch.setattr(gd, "save_cover_image", lambda b, slug: f"/blog-images/{slug}.jpg")
    cover = gd.maybe_generate_cover(GEN, "slug")
    assert cover["image"] == "/blog-images/slug.jpg"
    assert cover["alt"] == "a glowing prism"      # subject slot
    assert "prism" in cover["prompt"] and "Surfaces:" in cover["prompt"]


def test_failure_soft_returns_none(monkeypatch):
    monkeypatch.delenv("IMAGE_REQUIRED", raising=False)
    def boom(*a, **k):
        raise RuntimeError("cf down")
    monkeypatch.setattr(gd.image_client, "generate", boom)
    assert gd.maybe_generate_cover(GEN, "slug") is None


def test_failure_hard_when_required(monkeypatch):
    monkeypatch.setenv("IMAGE_REQUIRED", "true")
    def boom(*a, **k):
        raise RuntimeError("cf down")
    monkeypatch.setattr(gd.image_client, "generate", boom)
    import pytest
    with pytest.raises(RuntimeError):
        gd.maybe_generate_cover(GEN, "slug")


def _real_jpeg(px, colour=(120, 90, 200)):
    from PIL import Image
    import io as _io
    buf = _io.BytesIO()
    Image.new("RGB", (px, px), colour).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_downscale_shrinks_a_large_cover():
    from PIL import Image
    import io as _io
    big = _real_jpeg(1024)
    out = gd.downscale_cover(big)
    assert len(out) < len(big)
    assert max(Image.open(_io.BytesIO(out)).size) <= 800


def test_downscale_passes_undecodable_bytes_through():
    # a resize bug must never cost us the cover
    assert gd.downscale_cover(b"NOT-A-JPEG") == b"NOT-A-JPEG"


def test_downscale_never_returns_something_bigger():
    small = _real_jpeg(64)
    assert len(gd.downscale_cover(small)) <= len(small)


def test_save_cover_image_writes_the_downscaled_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "IMAGES_SUBDIR", str(tmp_path / "images"))
    big = _real_jpeg(1024)
    gd.save_cover_image(big, "big-slug")
    written = (tmp_path / "images" / "big-slug.jpg").read_bytes()
    assert len(written) < len(big)
