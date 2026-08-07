import generate_digest as gd

GEN = {
    "headline": "Great Post",
    "tags": ["css"],
}
VERIFIED = {"corrected_body_markdown": "## Body\n\nSome verified content about CSS."}

HOOK = {
    "headline": "CSS IS NOT DONE",
    "subtitle": "THE CASCADE STILL WINS",
    "pill": ["Cascade", "Layers", "Craft"],
    "photo_brief": "angled keyboard and monitor, soft light, no people",
    "tone": "muted_color",
}


def test_save_cover_image_writes_and_returns_rel(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "IMAGES_SUBDIR", str(tmp_path / "images"))
    rel = gd.save_cover_image(b"JPEGDATA", "my-slug")
    assert rel == "/blog-images/my-slug.jpg"
    assert (tmp_path / "images" / "my-slug.jpg").read_bytes() == b"JPEGDATA"


def test_dry_run_composes_without_flux(monkeypatch):
    called = {"flux": 0, "compose": 0}
    monkeypatch.setattr(gd.cover_hook, "generate_cover_hook", lambda *a, **k: HOOK)
    monkeypatch.setattr(
        gd.image_client,
        "generate",
        lambda *a, **k: called.__setitem__("flux", 1) or b"IMG",
    )
    monkeypatch.setattr(
        gd.cover_compose,
        "compose_cover",
        lambda hook, photo: (called.__setitem__("compose", 1), b"JPG")[1],
    )
    monkeypatch.setattr(gd, "save_cover_image", lambda b, slug: f"/blog-images/{slug}.jpg")
    cover = gd.maybe_generate_cover(GEN, VERIFIED, "slug", dry_run=True)
    assert called["flux"] == 0
    assert called["compose"] == 1
    assert cover["image"] == "/blog-images/slug.jpg"
    assert cover["alt"] == HOOK["headline"]


def test_success_returns_cover_dict(monkeypatch):
    monkeypatch.setattr(gd.cover_hook, "generate_cover_hook", lambda *a, **k: HOOK)
    monkeypatch.setattr(gd.image_client, "generate", lambda prompt, **k: b"IMG")
    monkeypatch.setattr(gd.cover_compose, "compose_cover", lambda hook, photo: b"JPG")
    monkeypatch.setattr(gd, "save_cover_image", lambda b, slug: f"/blog-images/{slug}.jpg")
    cover = gd.maybe_generate_cover(GEN, VERIFIED, "slug")
    assert cover["image"] == "/blog-images/slug.jpg"
    assert cover["alt"] == HOOK["headline"]
    assert "off-center" in cover["prompt"].lower() or "right" in cover["prompt"].lower()


def test_failure_soft_returns_none(monkeypatch):
    monkeypatch.delenv("IMAGE_REQUIRED", raising=False)

    def boom(*a, **k):
        raise RuntimeError("cf down")

    monkeypatch.setattr(gd.cover_hook, "generate_cover_hook", boom)
    assert gd.maybe_generate_cover(GEN, VERIFIED, "slug") is None


def test_failure_hard_when_required(monkeypatch):
    monkeypatch.setenv("IMAGE_REQUIRED", "true")

    def boom(*a, **k):
        raise RuntimeError("cf down")

    monkeypatch.setattr(gd.cover_hook, "generate_cover_hook", boom)
    import pytest

    with pytest.raises(RuntimeError):
        gd.maybe_generate_cover(GEN, VERIFIED, "slug")


def _real_jpeg(px, colour=(120, 90, 200)):
    from PIL import Image
    import io as _io

    buf = _io.BytesIO()
    Image.new("RGB", (px, px), colour).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_downscale_shrinks_a_large_cover():
    from PIL import Image
    import io as _io

    big = _real_jpeg(1600)
    out = gd.downscale_cover(big)
    assert len(out) < len(big)
    assert max(Image.open(_io.BytesIO(out)).size) <= 1200


def test_downscale_passes_undecodable_bytes_through():
    assert gd.downscale_cover(b"NOT-A-JPEG") == b"NOT-A-JPEG"


def test_downscale_never_returns_something_bigger():
    small = _real_jpeg(64)
    assert len(gd.downscale_cover(small)) <= len(small)


def test_save_cover_image_writes_the_downscaled_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "IMAGES_SUBDIR", str(tmp_path / "images"))
    big = _real_jpeg(1600)
    gd.save_cover_image(big, "big-slug")
    written = (tmp_path / "images" / "big-slug.jpg").read_bytes()
    assert len(written) < len(big)
