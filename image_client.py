"""
Thin wrapper around the Cloudflare Workers AI text-to-image REST API.

Mirrors bedrock_client.py: a single-purpose provider adapter. Config comes from
env, `requests` is the only dependency (already used by the pipeline), and errors
are raised so the caller owns dry-run and best-effort fallback decisions. This
module intentionally knows nothing about Bedrock or the orchestrator.
"""

import os
import base64

import requests

DEFAULT_MODEL = "@cf/black-forest-labs/flux-1-schnell"
API_BASE = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
DEFAULT_STEPS = 4
MAX_PROMPT_CHARS = 2048
REQUEST_TIMEOUT = 60


def _config():
    account_id = os.getenv("CF_ACCOUNT_ID")
    api_token = os.getenv("CF_API_TOKEN")
    if not account_id or not api_token:
        raise RuntimeError(
            "CF_ACCOUNT_ID and CF_API_TOKEN must be set for image generation"
        )
    model = os.getenv("CF_IMAGE_MODEL", DEFAULT_MODEL)
    return account_id, api_token, model


def generate(prompt, *, steps=None):
    """Text-to-image via Cloudflare Workers AI. Returns raw image bytes (JPEG).

    Raises RuntimeError on missing config or an unsuccessful response; propagates
    requests exceptions on transport/HTTP failure.
    """
    account_id, api_token, model = _config()
    if steps is None:
        steps = int(os.getenv("IMAGE_STEPS", DEFAULT_STEPS))

    url = API_BASE.format(account_id=account_id, model=model)
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
        json={"prompt": prompt[:MAX_PROMPT_CHARS], "steps": steps},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()

    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"Cloudflare image generation failed: {data.get('errors')}")
    image_b64 = (data.get("result") or {}).get("image")
    if not image_b64:
        raise RuntimeError("Cloudflare response missing result.image")
    return base64.b64decode(image_b64)
