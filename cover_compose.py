"""Playwright compositor: editorial HTML template + photo → 1200×630 JPEG."""

from __future__ import annotations

import io
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


def compose_cover(hook, photo_bytes=None) -> bytes:
    """Render the editorial cover. Returns JPEG bytes (1200×630).

    Uses a local static server (never file://) so @font-face loads reliably.
    """
    from playwright.sync_api import sync_playwright

    if not photo_bytes:
        photo_bytes = _placeholder_photo_bytes()

    h = cover_hook.normalize_hook(hook)
    server = None
    tmp_photo = None
    try:
        # Serve template dir; write photo into a temp name inside it for same-origin.
        work = TEMPLATE_DIR
        tmp_photo = work / "_runtime_photo.jpg"
        tmp_photo.write_bytes(photo_bytes)

        server, origin = _start_server(work)
        qs = urlencode(
            {
                "headline": h["headline"],
                "subtitle": h["subtitle"],
                "pill": _pill_text(h),
                "photo": "/_runtime_photo.jpg",
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
            # Ensure fonts applied
            page.evaluate("() => document.fonts.ready")
            png = page.screenshot(type="png", clip={"x": 0, "y": 0, "width": COVER_W, "height": COVER_H})
            browser.close()

        img = Image.open(io.BytesIO(png)).convert("RGB")
        if img.size != (COVER_W, COVER_H):
            img = img.resize((COVER_W, COVER_H), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=88, optimize=True, progressive=True)
        return out.getvalue()
    finally:
        if server is not None:
            server.shutdown()
        if tmp_photo is not None and tmp_photo.exists():
            try:
                tmp_photo.unlink()
            except OSError:
                pass
