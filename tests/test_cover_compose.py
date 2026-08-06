from PIL import Image
import io

import cover_compose as cc
import generate_digest as gd

HOOK = {
    "headline": "THE DETAIL HIDING IN PLAIN SIGHT",
    "subtitle": "WHAT THE SUMMARY NEVER MENTIONS",
    "pill": ["Clarity", "Depth", "Craft"],
    "photo_brief": "desk scene",
    "tone": "muted_color",
}


def test_compose_cover_returns_png_canvas():
    png = cc.compose_cover(HOOK, photo_bytes=None)
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (1200, 630)


def test_save_cover_single_jpeg_encode_from_png(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "IMAGES_SUBDIR", str(tmp_path / "images"))
    png = cc.compose_cover(HOOK, photo_bytes=None)
    rel = gd.save_cover_image(png, "single-encode")
    written = (tmp_path / "images" / "single-encode.jpg").read_bytes()
    assert rel.endswith(".jpg")
    assert written[:3] == b"\xff\xd8\xff"
    assert Image.open(io.BytesIO(written)).size == (1200, 630)


def test_pill_text_format():
    assert "✓ Clarity" in cc._pill_text(HOOK)


def test_stage_template_uses_private_tempdir():
    photo = cc._placeholder_photo_bytes()
    work = cc._stage_template(photo)
    try:
        assert work != cc.TEMPLATE_DIR
        assert (work / "photo.jpg").is_file()
        assert (work / "index.html").is_file()
        assert "cover_compose_" in work.name
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
