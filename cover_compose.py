"""Playwright compositor: editorial HTML template + photo → 1200×630 PNG."""

from __future__ import annotations

import io
import shutil
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

from PIL import Image

import cover_hook

TEMPLATE_DIR = Path(__file__).resolve().parent / "cover_template"
COVER_W, COVER_H = 1200, 630


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A003
        return


def _start_server(directory: Path):
    handler = partial(_QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}"


def _placeholder_photo_bytes():
    """Muted placeholder when FLUX is skipped (dry-run)."""
    img = Image.new("RGB", (1024, 1024), (90, 96, 105))
    # Soft right-side accent so cover-crop isn't flat (avoid per-pixel loops).
    accent = Image.new("RGB", (512, 1024), (130, 126, 125))
    img.paste(accent, (512, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _pill_text(hook):
    h = cover_hook.normalize_hook(hook)
    return " | ".join(f"✓ {b}" for b in h["pill"])


def _stage_template(photo_bytes: bytes) -> Path:
    """Copy template + photo into a private temp dir (safe for concurrent renders)."""
    work = Path(tempfile.mkdtemp(prefix="cover_compose_"))
    for name in ("index.html", "cover.css", "cover.js"):
        shutil.copy2(TEMPLATE_DIR / name, work / name)
    fonts_src = TEMPLATE_DIR / "fonts"
    if fonts_src.is_dir():
        shutil.copytree(fonts_src, work / "fonts")
    (work / "photo.jpg").write_bytes(photo_bytes)
    return work


def compose_cover(hook, photo_bytes=None) -> bytes:
    """Render the editorial cover. Returns PNG bytes (1200×630).

    JPEG encoding is left to ``downscale_cover`` / ``save_cover_image`` so the
    cover is lossy-compressed once. Uses a local static server (never file://)
    so @font-face loads reliably.
    """
    from playwright.sync_api import sync_playwright

    if not photo_bytes:
        photo_bytes = _placeholder_photo_bytes()

    h = cover_hook.normalize_hook(hook)
    server = None
    work = None
    try:
        work = _stage_template(photo_bytes)
        server, origin = _start_server(work)
        qs = urlencode(
            {
                "headline": h["headline"],
                "subtitle": h["subtitle"],
                "pill": _pill_text(h),
                "photo": "/photo.jpg",
            }
        )
        url = f"{origin}/index.html?{qs}"

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(
                viewport={"width": COVER_W, "height": COVER_H},
                device_scale_factor=1,
            )
            page.goto(url, wait_until="networkidle")
            page.wait_for_function("() => window.__COVER_READY__ === true", timeout=15000)
            page.evaluate("() => document.fonts.ready")
            png = page.screenshot(
                type="png",
                clip={"x": 0, "y": 0, "width": COVER_W, "height": COVER_H},
            )
            browser.close()

        img = Image.open(io.BytesIO(png)).convert("RGB")
        if img.size != (COVER_W, COVER_H):
            img = img.resize((COVER_W, COVER_H), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue()
    finally:
        if server is not None:
            server.shutdown()
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
